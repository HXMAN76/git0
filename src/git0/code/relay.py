"""CodeRelay: the shared code-context graph of one IDE demo session (one FalkorDB graph, `ide_<session>`).

Each agent works in its own clone. Every write the agent makes is recorded here, so the graph is the team's
shared view of symbols, calls and who changed what. Conflict detection is deterministic: Python diffs the
parsed sources, Cypher finds the clashing Changes, and the LLM never decides anything.

Every write is ONE query (FalkorDB has no multi-query transactions). The Cypher lives in cypher/code_*.cypher.
"""

from __future__ import annotations

import re
import time
import uuid
from typing import Literal

from falkordb.asyncio.graph import AsyncGraph
from pydantic import BaseModel, Field

from git0.code.parse import EditDiff, SymbolInfo, diff_symbols, parse_file, parse_project
from git0.core.db import get_db
from git0.core.queries import Q

_TENANT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
RESOLUTIONS = frozenset({"adopt", "override", "pause"})  # the three human choices on a blocked write


def _gist(text: str, limit: int = 90) -> str:
    """Intent tasks are whole user prompts; a conflict card only needs the gist."""
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class ConflictInfo(BaseModel):
    kind: Literal["same_symbol", "dependency", "reverse_dependency", "intent"]
    severity: Literal["block", "warn"]  # intent = warn, others = block
    symbol: str  # the symbol the CHECKING agent touches or calls
    peer: str  # other agent id
    peer_change_id: str | None
    peer_summary: str  # e.g. "Alice changed signature: apply_tax(amount) -> apply_tax(amount, region)"
    path: list[str]  # symbol ids along the graph path, for highlighting
    message: str  # one human sentence, no jargon


class CheckResult(BaseModel):
    conflicts: list[ConflictInfo] = Field(default_factory=list)
    touched: list[str] = Field(default_factory=list)  # symbol ids this edit would add, modify or remove

    @property
    def blocking(self) -> bool:
        return any(c.severity == "block" for c in self.conflicts)


class ChangeRecord(BaseModel):
    change_ids: list[str]
    touched: list[str]
    summary: str


class PeerNotice(BaseModel):
    change_id: str
    agent: str
    symbol: str
    kind: str
    summary: str
    ts: int


def code_graph_for(tenant: str) -> AsyncGraph:
    """The IDE session's graph. Named ide_<tenant> so it never collides with the team_* memory graphs."""
    if not _TENANT_RE.match(tenant):
        raise ValueError(f"invalid tenant id: {tenant!r}")
    return get_db().select_graph(f"ide_{tenant}")


def _rows(result) -> list[dict]:
    cols = [c[1] if isinstance(c, list | tuple) else c for c in result.header]
    return [dict(zip(cols, row, strict=True)) for row in result.result_set]


def _name(symbol_id: str) -> str:
    """'shop/cart.py::calculate_total' -> 'calculate_total' (human text only; ids stay full elsewhere)."""
    return symbol_id.split("::")[-1]


def _short(signature: str) -> str:
    """'def apply_tax(amount)' -> 'apply_tax(amount)': the form humans read in a conflict message."""
    return signature.removeprefix("async ").removeprefix("def ").removeprefix("class ")


def _sym_row(s: SymbolInfo) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "path": s.path,
        "kind": s.kind,
        "signature": s.signature,
        "body_hash": s.body_hash,
        "line": s.line,
        "end_line": s.end_line,
    }


def _gone_row(s: SymbolInfo) -> dict:
    return {"id": s.id, "name": s.name, "path": s.path, "kind": s.kind}


def _diff_for(path: str, old_source: str, new_source: str) -> tuple[EditDiff, list[SymbolInfo]]:
    """Diff of one file's write, plus the new file's symbols. Raises SyntaxError on bad new source."""
    old = parse_file(path, old_source)
    new = parse_file(path, new_source)
    return diff_symbols(old, new), new


def _touched(diff: EditDiff) -> list[str]:
    ids = [s.id for s in diff.added] + [n.id for _, n in diff.modified] + [s.id for s in diff.removed]
    return list(dict.fromkeys(ids))  # unique, first-seen order


def _changes(diff: EditDiff) -> list[dict]:
    """One Change per touched symbol. Kind is 'signature' when the contract moved, not just the body."""
    out: list[dict] = []

    def add(kind: str, symbol: str, summary: str, old_sig: str = "", new_sig: str = "") -> None:
        out.append(
            {
                "id": uuid.uuid4().hex[:12],
                "symbol": symbol,
                "kind": kind,
                "summary": summary,
                "old_signature": old_sig,
                "new_signature": new_sig,
            }
        )

    for s in diff.added:
        add("added", s.id, f"added {s.name}", new_sig=s.signature)
    for old, new in diff.signature_changed:
        add(
            "signature",
            new.id,
            f"changed signature: {old.signature} -> {new.signature}",
            old.signature,
            new.signature,
        )
    sig_ids = {new.id for _, new in diff.signature_changed}
    for _, new in diff.modified:
        if new.id not in sig_ids:
            add("modified", new.id, f"modified body of {new.name}")
    for s in diff.removed:
        add("removed", s.id, f"removed {s.name}", old_sig=s.signature)
    return out


class CodeRelay:
    def __init__(self, graph: AsyncGraph):
        self.graph = graph

    async def seed(self, files: dict[str, str], agents: dict[str, str]) -> dict:
        """Load the whole project once at session start. `files` is {path: source}; only *.py is indexed."""
        parsed = parse_project(files)
        symbols = [_sym_row(s) for syms in parsed.values() for s in syms]
        calls = [{"src": s.id, "dst": d} for syms in parsed.values() for s in syms for d in s.calls]
        await self.graph.query(
            Q["code_seed"],
            {
                "files": sorted(parsed),
                "symbols": symbols,
                "calls": calls,
                "agents": [{"id": k, "label": v} for k, v in agents.items()],
            },
        )
        return {"files": len(parsed), "symbols": len(symbols), "calls": len(calls), "agents": list(agents)}

    async def announce_intent(self, agent: str, task: str, symbols: list[str]) -> str:
        """Say what the agent is about to work on. Only its latest intent stays active."""
        intent_id = uuid.uuid4().hex[:12]
        rows = _rows(
            await self.graph.query(
                Q["code_announce_intent"],
                {"agent": agent, "task": task, "id": intent_id, "ts": _now_ms(), "symbols": symbols},
            )
        )
        if not rows:
            raise RuntimeError(f"announce_intent wrote nothing for agent {agent!r}")
        return rows[0]["id"]

    async def check_edit(self, agent: str, path: str, old_source: str, new_source: str) -> CheckResult:
        """Would this write clash with what the other agents changed and have not acknowledged? Read-only."""
        diff, _ = _diff_for(path, old_source, new_source)
        touched = _touched(diff)
        edges = list(
            dict.fromkeys((s.id, d) for s in [*diff.added, *(n for _, n in diff.modified)] for d in s.calls)
        )
        contract = list(
            dict.fromkeys([s.id for s in diff.removed] + [n.id for _, n in diff.signature_changed])
        )
        conflicts: list[ConflictInfo] = []
        # Each query gets only the parameters it reads; the four are independent, so a failure names the one.
        if touched:
            same = await self.graph.ro_query(
                Q["code_conflicts_same_symbol"], {"agent": agent, "touched": touched}
            )
            conflicts += [_same_conflict(r) for r in _rows(same)]
        if edges:
            dep_params = {"agent": agent, "edges": [{"src": a, "dst": b} for a, b in edges]}
            dep = await self.graph.ro_query(Q["code_conflicts_dependency"], dep_params)
            conflicts += [_dependency_conflict(r) for r in _rows(dep)]
        if contract:
            rev = await self.graph.ro_query(
                Q["code_conflicts_reverse"], {"agent": agent, "contract": contract}
            )
            conflicts += [_reverse_conflict(r) for r in _rows(rev)]
        if touched:
            intent = await self.graph.ro_query(
                Q["code_conflicts_intent"], {"agent": agent, "touched": touched}
            )
            conflicts += [_intent_conflict(r) for r in _rows(intent)]
        return CheckResult(conflicts=_dedupe(conflicts), touched=touched)

    async def record_edit(
        self, agent: str, path: str, old_source: str, new_source: str, summary: str = ""
    ) -> ChangeRecord:
        """Record a write that landed in the agent's clone. One query, one Change per touched symbol."""
        diff, new_syms = _diff_for(path, old_source, new_source)
        changes = _changes(diff)
        calls = [{"src": s.id, "dst": d} for s in new_syms for d in s.calls]
        params = {
            "path": path,
            "agent": agent,
            "ts": _now_ms(),
            "syms": [_sym_row(s) for s in new_syms],
            "ids": [s.id for s in new_syms],
            "gone": [_gone_row(s) for s in diff.removed],
            "calls": calls,
            "changes": changes,
        }
        rows = _rows(await self.graph.query(Q["code_record_edit"], params))
        if not rows:
            raise RuntimeError(f"record_edit wrote nothing for {path}")
        auto = "; ".join(c["summary"] for c in changes) or "no symbol changes"
        return ChangeRecord(
            change_ids=[c["id"] for c in changes],
            touched=_touched(diff),
            summary=summary or auto,
        )

    async def unseen_changes(self, agent: str) -> list[PeerNotice]:
        rows = _rows(await self.graph.ro_query(Q["code_unseen_changes"], {"agent": agent}))
        return [
            PeerNotice(
                change_id=r["change_id"],
                agent=r["agent"],
                symbol=r["symbol"],
                kind=r["kind"],
                summary=r["summary"],
                ts=r["ts"],
            )
            for r in rows
        ]

    async def acknowledge(self, agent: str, change_ids: list[str]) -> int:
        if not change_ids:
            return 0
        rows = _rows(await self.graph.query(Q["code_acknowledge"], {"agent": agent, "ids": change_ids}))
        return int(rows[0]["n"]) if rows else 0

    async def record_conflicts(self, agent: str, conflicts: list[ConflictInfo]) -> list[str]:
        """Write the conflicts a blocked edit raised as Conflict nodes (resolution 'pending'). One query.

        Returns the new Conflict ids in input order. Intent conflicts are recorded too, with no AGAINST link.
        """
        if not conflicts:
            return []
        ts = _now_ms()
        rows_in = [
            {
                "id": uuid.uuid4().hex[:12],
                "peer": c.peer,
                "kind": c.kind,
                "message": c.message,
                "ts": ts,
                "symbol": c.symbol,
                "change_id": c.peer_change_id or "",  # '' matches no Change; a null would need a special case
            }
            for c in conflicts
        ]
        rows = _rows(
            await self.graph.query(Q["code_record_conflicts"], {"agent": agent, "conflicts": rows_in})
        )
        found = {r["id"] for r in rows}
        missing = [r["id"] for r in rows_in if r["id"] not in found]
        if missing:  # fail loudly: the UI must not show a conflict node the graph does not have
            raise RuntimeError(
                f"record_conflicts: {len(missing)} of {len(rows_in)} conflicts were not written"
            )
        return [r["id"] for r in rows_in]

    async def resolve_conflicts(self, conflict_ids: list[str], resolution: str) -> int:
        """Set the human's choice on recorded conflicts. Returns how many Conflict nodes matched."""
        if resolution not in RESOLUTIONS:
            raise ValueError(f"resolution must be one of {sorted(RESOLUTIONS)}, got {resolution!r}")
        if not conflict_ids:
            return 0
        rows = _rows(
            await self.graph.query(
                Q["code_resolve_conflicts"], {"ids": conflict_ids, "resolution": resolution}
            )
        )
        return int(rows[0]["n"]) if rows else 0

    async def view(self) -> dict:
        """The whole session graph in the shape the IDE's graph panel draws."""
        nodes = []
        for r in _rows(await self.graph.ro_query(Q["code_view_nodes"])):
            props = {
                k: r[k]
                for k in (
                    "path",
                    "signature",
                    "summary",
                    "task",
                    "agent",
                    "active",
                    "removed",
                    "ts",
                    "peer",
                    "message",
                    "resolution",
                )
            }
            props = {k: v for k, v in props.items() if v is not None}
            if r["label"] == "Agent":
                props["label"] = r["agent_label"]
            name = (
                r["name"]
                or r["summary"]
                or r["task"]
                or (_gist(r["message"]) if r["message"] else None)
                or r["agent_label"]
                or r["id"]
            )
            nodes.append(
                {"id": r["id"], "label": r["label"], "name": name, "kind": r["kind"], "props": props}
            )
        links = [
            {"source": r["source"], "target": r["target"], "type": r["type"]}
            for r in _rows(await self.graph.ro_query(Q["code_view_links"]))
        ]
        return {"nodes": nodes, "links": links}

    async def symbol_ids(self) -> list[str]:
        return [r["id"] for r in _rows(await self.graph.ro_query(Q["code_symbol_ids"]))]


# ── helpers that turn query rows into contract models ────────────────────────


def _now_ms() -> int:
    return int(time.time() * 1000)


def _label(row: dict) -> str:
    return row.get("peer_label") or row["peer"]


def _same_conflict(r: dict) -> ConflictInfo:
    label, sym = _label(r), r["symbol"]
    return ConflictInfo(
        kind="same_symbol",
        severity="block",
        symbol=sym,
        peer=r["peer"],
        peer_change_id=r["change_id"],
        peer_summary=f"{label} {r['summary']}",
        path=[sym],
        message=f"{label} already changed {_name(sym)} ({r['summary']}), and this edit changes it too.",
    )


def _dependency_conflict(r: dict) -> ConflictInfo:
    label, src, dst = _label(r), r["src"], r["dst"]
    return ConflictInfo(
        kind="dependency",
        severity="block",
        symbol=src,
        peer=r["peer"],
        peer_change_id=r["change_id"],
        peer_summary=f"{label} {r['summary']}",
        path=[src, dst],
        message=f"{_name(src)} calls {_name(dst)}, and {label} {r['summary']}.",
    )


def _reverse_conflict(r: dict) -> ConflictInfo:
    label, target, caller = _label(r), r["symbol"], r["caller"]
    return ConflictInfo(
        kind="reverse_dependency",
        severity="block",
        symbol=target,
        peer=r["peer"],
        peer_change_id=r["change_id"],
        peer_summary=f"{label} {r['summary']}",
        path=list(r["path"]),
        message=(
            f"{label} wrote {_name(caller)}, which calls {_name(target)}. "
            "This edit changes that contract, so the new code would break."
        ),
    )


def _intent_conflict(r: dict) -> ConflictInfo:
    label, sym = _label(r), r["symbol"]
    return ConflictInfo(
        kind="intent",
        severity="warn",
        symbol=sym,
        peer=r["peer"],
        peer_change_id=None,
        peer_summary=r["task"],
        path=[sym],
        message=f"{label} announced they are working on {_name(sym)}: {_gist(r['task'])}",
    )


def _dedupe(conflicts: list[ConflictInfo]) -> list[ConflictInfo]:
    seen: set[tuple] = set()
    out: list[ConflictInfo] = []
    for c in conflicts:
        key = (c.kind, c.symbol, c.peer, tuple(c.path))
        if key not in seen:
            seen.add(key)
            out.append(c)
    return out
