"""MemoryRepo: git verbs over a tenant graph. Each method is one Cypher query from cypher/."""

import asyncio
import uuid

from falkordb.asyncio.graph import AsyncGraph

from git0.core.models import Commit, CommitRequest, Fact, Procedure
from git0.core.queries import Q


class CommitConflictError(RuntimeError):
    """HEAD kept moving and the CAS commit could not land within the retry budget."""


# Per-predicate merge strategy. Seeded into the graph (ON CREATE only) so humans can edit it later.
DEFAULT_RULES: dict[str, str] = {
    **dict.fromkeys(
        ["deadline", "owner", "budget", "decision", "location", "depends_on", "contact"], "needs-review"
    ),
    **dict.fromkeys(["preference", "status"], "latest-wins"),
}


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _rows(result) -> list[dict]:
    cols = [c[1] if isinstance(c, list | tuple) else c for c in result.header]
    return [dict(zip(cols, row, strict=True)) for row in result.result_set]


class MemoryRepo:
    def __init__(self, graph: AsyncGraph):
        self.graph = graph

    async def init(self) -> None:
        await self.graph.query(Q["init_repo"], {"root_id": new_id()})
        rules = [{"p": p, "strategy": s} for p, s in DEFAULT_RULES.items()]
        await self.graph.query(Q["seed_rules"], {"rules": rules})

    async def rules(self) -> dict[str, str]:
        return {r["p"]: r["strategy"] for r in _rows(await self.graph.ro_query(Q["rules"]))}

    async def create_branch(self, name: str, from_branch: str = "main") -> str:
        rows = _rows(await self.graph.query(Q["create_branch"], {"name": name, "from": from_branch}))
        if not rows:
            raise ValueError(f"cannot create branch {name!r} from {from_branch!r}")
        return rows[0]["head"]

    async def head(self, branch: str) -> str:
        res = await self.graph.ro_query(
            "MATCH (:Branch {name: $b})-[:HEAD]->(h:Commit) RETURN h.id", {"b": branch}
        )
        if not res.result_set:
            raise KeyError(f"no such branch: {branch}")
        return res.result_set[0][0]

    async def try_commit(self, req: CommitRequest, expected: str) -> Commit | None:
        """One CAS attempt. Returns None when HEAD != expected (someone else committed first)."""
        params = {
            "branch": req.branch,
            "expected": expected,
            "id": new_id(),
            "msg": req.msg,
            "kind": req.kind,
            "agent_id": req.agent_id,
            "facts": [f.model_dump() for f in req.facts],
            "removed": req.removed,
            "procedures": [p.model_dump() for p in req.procedures],
            "removed_procedures": req.removed_procedures,
            "derived": [d.model_dump() for d in req.derived],
            "episodes": [e.model_dump() for e in req.episodes],
        }
        rows = _rows(await self.graph.query(Q["commit_cas"], params))
        return Commit(id=rows[0]["id"], seq=rows[0]["seq"]) if rows else None

    async def commit(self, req: CommitRequest, retries: int = 8) -> tuple[Commit, int]:
        """Commit on top of the current HEAD, retrying the CAS if HEAD moves. Returns (commit, retries)."""
        for attempt in range(retries + 1):
            done = await self.try_commit(req, await self.head(req.branch))
            if done:
                return done, attempt
            await asyncio.sleep(0.002 * (2**attempt))
        raise CommitConflictError(f"{req.branch}: HEAD moved {retries + 1} times")

    async def checkout(self, branch: str) -> list[Fact]:
        return [Fact(**r) for r in _rows(await self.graph.ro_query(Q["checkout"], {"branch": branch}))]

    async def checkout_at(self, commit_id: str) -> list[Fact]:
        """Facts visible at any commit (e.g. a merge base), not only a branch HEAD."""
        rows = _rows(await self.graph.ro_query(Q["checkout_commit"], {"commit": commit_id}))
        return [Fact(**r) for r in rows]

    async def dependents_visible(self, fact_id: str, head: str) -> list[Fact]:
        """Dependents of a fact that are still visible at commit `head`."""
        rows = _rows(await self.graph.ro_query(Q["dependents_visible"], {"fid": fact_id, "head": head}))
        return [Fact(**r) for r in rows]

    async def precedent(self, p: str) -> tuple[str, int] | None:
        """(choice, count) of the most-chosen past resolution for predicate `p`, or None."""
        rows = _rows(await self.graph.ro_query(Q["precedent_lookup"], {"p": p}))
        return (rows[0]["choice"], rows[0]["count"]) if rows else None

    async def try_merge_commit(
        self,
        target: str,
        expected_target: str,
        source_head: str,
        removed: list[str],
        resolutions: list[dict],
        msg: str,
        agent_id: str,
    ) -> Commit | None:
        """One CAS attempt at a two-parent merge commit on `target`. None = target HEAD != expected_target."""
        params = {
            "target": target,
            "expected_target": expected_target,
            "source_head": source_head,
            "id": new_id(),
            "msg": msg,
            "agent_id": agent_id,
            "removed": removed,
            "resolutions": resolutions,
        }
        rows = _rows(await self.graph.query(Q["merge_commit"], params))
        return Commit(id=rows[0]["id"], seq=rows[0]["seq"]) if rows else None

    async def procedures(self, branch: str) -> list[Procedure]:
        rows = _rows(await self.graph.ro_query(Q["checkout_procedures"], {"branch": branch}))
        return [Procedure(**r) for r in rows]

    async def log(self, branch: str, limit: int = 50) -> list[Commit]:
        rows = _rows(await self.graph.ro_query(Q["log"], {"branch": branch, "limit": limit}))
        return [Commit(**r) for r in rows]

    async def merge_base(self, a: str, b: str) -> str:
        rows = _rows(await self.graph.ro_query(Q["merge_base"], {"a": a, "b": b}))
        if not rows:
            raise ValueError(f"no common ancestor for {a} and {b}")
        return rows[0]["id"]

    async def dependents(self, fact_id: str) -> list[dict]:
        return _rows(await self.graph.ro_query(Q["dependents"], {"fid": fact_id}))

    async def why(self, fact_id: str) -> list[dict]:
        return _rows(await self.graph.ro_query(Q["why_path"], {"fid": fact_id}))

    async def lookup(self, branch: str, key: str) -> list[dict]:
        """Empty list means 'not in memory' (no path from HEAD), which the agents must say verbatim."""
        return _rows(await self.graph.ro_query(Q["fact_lookup"], {"branch": branch, "key": key}))
