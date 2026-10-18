"""RelayHooks: the Pre/PostToolUse hooks every harness tool call goes through.

Each hook is a real MCP client call (streamable HTTP) to the code_* tools that git0 mounts at /mcp in this
same process, so the hook path is the one an external client would take. The relay decides; the hook only
maps the answer to allow / deny / context. No LLM is involved in any decision.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp_types import CallToolResult
from pydantic import BaseModel, Field

from git0.code.relay import CheckResult
from git0.ide.harness import resolve_in_workspace

logger = logging.getLogger(__name__)

CALL_TIMEOUT_S = 30.0
READ_TOOLS = {"read_file", "list_files", "team_context"}


class HookDecision(BaseModel):
    action: Literal["allow", "deny", "context"] = "allow"
    message: str = ""
    conflicts: list[dict[str, Any]] = Field(default_factory=list)


class RelayUnavailable(RuntimeError):
    """The git0 MCP server did not answer a relay call. Callers fail loudly, never allow silently."""


def decide_write(check: CheckResult) -> HookDecision:
    """Map the relay's CheckResult to a hook decision.

    block -> deny (the harness asks the human); warn only -> context (the write goes through with a note);
    nothing -> allow.
    """
    if not check.conflicts:
        return HookDecision(action="allow")
    dumps = [c.model_dump() for c in check.conflicts]
    if check.blocking:
        blocking = [c.message for c in check.conflicts if c.severity == "block"]
        return HookDecision(action="deny", message=" ".join(blocking), conflicts=dumps)
    return HookDecision(action="context", message=" ".join(c.message for c in check.conflicts))


def tool_payload(result: CallToolResult) -> Any:
    """The JSON the tool returned. FastMCP puts non-object returns (lists) under {"result": ...}."""
    if result.structured_content is not None:
        sc = result.structured_content
        if isinstance(sc, dict) and set(sc) == {"result"}:
            return sc["result"]
        return sc
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return json.loads(block.text)
    return None


def describe_notice(n: dict[str, Any], now_ms: float) -> str:
    age = max(0, int((now_ms - n["ts"]) / 1000))
    return f"Heads-up: {n['agent']} changed {n['symbol']} ({n['summary']}), {age}s ago."


class _McpConnection:
    """One streamable-HTTP MCP client session, owned by a single background task.

    Calls are queued to that task, so the connection's anyio cancel scopes are entered and exited in the same
    task. If the connection drops, the task ends and the next call opens a new one.
    """

    def __init__(self, url: str) -> None:
        self._url = url
        self._queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[CallToolResult]]] | None = None
        self._task: asyncio.Task[None] | None = None

    async def call(self, tool: str, arguments: dict[str, Any]) -> CallToolResult:
        if self._task is None or self._task.done():
            self._queue = asyncio.Queue()
            self._task = asyncio.create_task(self._run(self._queue), name="ide-mcp-client")
        fut: asyncio.Future[CallToolResult] = asyncio.get_running_loop().create_future()
        assert self._queue is not None
        await self._queue.put((tool, arguments, fut))
        return await asyncio.wait_for(fut, CALL_TIMEOUT_S)

    async def _run(
        self, queue: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future[CallToolResult]]]
    ) -> None:
        try:
            async with streamable_http_client(self._url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    while True:
                        tool, arguments, fut = await queue.get()
                        try:
                            result = await session.call_tool(tool, arguments)
                        except (
                            Exception
                        ) as exc:  # transport trouble: fail this call; the next call reconnects
                            if not fut.done():
                                fut.set_exception(exc)
                            return
                        if not fut.done():
                            fut.set_result(result)
        finally:
            # Callers already waiting on queued calls must see the failure, not wait for the timeout.
            while not queue.empty():
                _, _, fut = queue.get_nowait()
                if not fut.done():
                    fut.set_exception(RelayUnavailable("git0 relay connection closed"))

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None


class RelayHooks:
    """Pre/PostToolUse for one agent in one session. `emit` is the session's event bus (type, **data)."""

    def __init__(
        self,
        *,
        session_id: str,
        agent_id: str,
        workspace: Path,
        mcp_url: str,
        emit: Callable[..., None],
        now_ms: Callable[[], float] = lambda: time.time() * 1000,
    ) -> None:
        self.session_id = session_id  # the relay's tenant: graph ide_<session_id>
        self.agent_id = agent_id
        self.workspace = workspace
        self._emit = emit
        self._now_ms = now_ms
        self._conn = _McpConnection(mcp_url)
        self._surfaced: set[str] = set()  # peer change ids already shown to this agent
        self._old: dict[str, str] = {}  # path -> file content before the write, for code_record_edit

    async def close(self) -> None:
        await self._conn.close()

    # ---- relay calls ----

    async def _call(self, mcp_tool: str, arguments: dict[str, Any]) -> Any:
        try:
            result = await self._conn.call(mcp_tool, arguments)
        except Exception as exc:
            # TimeoutError has an empty str(), so always name the exception type too.
            raise RelayUnavailable(f"{mcp_tool}: {type(exc).__name__}: {exc}") from exc
        if result.is_error:
            raise RelayUnavailable(f"{mcp_tool} failed: {result.content}")
        return tool_payload(result)

    def _hook(self, phase: str, tool: str, mcp_tool: str, decision: str, detail: str, started: float) -> None:
        self._emit(
            "hook",
            agent=self.agent_id,
            phase=phase,
            tool=tool,
            mcp_tool=mcp_tool,
            decision=decision,
            detail=detail,
            ms=int((time.perf_counter() - started) * 1000),
        )

    # ---- hooks ----

    async def pre_tool_use(self, tool: str, args: dict[str, Any]) -> HookDecision:
        started = time.perf_counter()
        if tool == "write_file":
            return await self._pre_write(args, started)
        if tool in READ_TOOLS:
            return await self._pre_read(tool, started)
        return HookDecision()

    async def _pre_write(self, args: dict[str, Any], started: float) -> HookDecision:
        path = args["path"]
        target = resolve_in_workspace(self.workspace, path)  # the harness checked already; cheap to repeat
        old = target.read_bytes().decode("utf-8", "replace") if target.is_file() else ""
        self._old[path] = old
        try:
            payload = await self._call(
                "code_check_edit",
                {
                    "tenant": self.session_id,
                    "agent": self.agent_id,
                    "path": path,
                    "old_source": old,
                    "new_source": args["content"],
                },
            )
        except RelayUnavailable as exc:
            # Fail loudly and deny: a write we could not check is not allowed through silently.
            self._emit("error", agent=self.agent_id, message=f"relay check failed for {path}: {exc}")
            self._hook("PreToolUse", "write_file", "code_check_edit", "deny", str(exc), started)
            return HookDecision(
                action="deny", message=f"BLOCKED: the git0 relay could not check this write ({exc})."
            )

        decision = decide_write(CheckResult.model_validate(payload))
        detail = f"{len(decision.conflicts)} conflict(s)" if decision.conflicts else "no conflicts"
        self._hook("PreToolUse", "write_file", "code_check_edit", decision.action, detail, started)
        return decision

    async def _pre_read(self, tool: str, started: float) -> HookDecision:
        try:
            notices = await self._call(
                "code_peer_activity", {"tenant": self.session_id, "agent": self.agent_id}
            )
        except RelayUnavailable as exc:
            self._emit("error", agent=self.agent_id, message=f"relay peer check failed: {exc}")
            self._hook("PreToolUse", tool, "code_peer_activity", "allow", f"relay error: {exc}", started)
            return HookDecision()

        fresh = [n for n in notices or [] if n["change_id"] not in self._surfaced]
        # team_context returns the notices itself, so mark them surfaced instead of repeating them.
        if tool == "team_context":
            self._surfaced.update(n["change_id"] for n in fresh)
            self._hook("PreToolUse", tool, "code_peer_activity", "allow", f"{len(fresh)} new", started)
            return HookDecision()
        if not fresh:
            self._hook("PreToolUse", tool, "code_peer_activity", "allow", "no news", started)
            return HookDecision()

        now = self._now_ms()
        messages = []
        for n in fresh:
            self._surfaced.add(n["change_id"])
            text = describe_notice(n, now)
            messages.append(text)
            self._emit("peer_notice", agent=self.agent_id, **{"from": n["agent"]}, message=text)
        self._hook("PreToolUse", tool, "code_peer_activity", "context", f"{len(fresh)} new", started)
        return HookDecision(action="context", message=" ".join(messages))

    async def post_tool_use(self, tool: str, args: dict[str, Any], result: str) -> str | None:
        """Record a write in the graph. Returns a warning for the model if the record failed."""
        if tool != "write_file":
            return None
        started = time.perf_counter()
        path = args["path"]
        old = self._old.pop(path, "")
        try:
            record = await self._call(
                "code_record_edit",
                {
                    "tenant": self.session_id,
                    "agent": self.agent_id,
                    "path": path,
                    "old_source": old,
                    "new_source": args["content"],
                    "summary": args.get("summary", ""),
                },
            )
        except RelayUnavailable as exc:
            self._emit("error", agent=self.agent_id, message=f"could not record {path} in the graph: {exc}")
            return f"WARNING: this edit could not be recorded in the relay graph ({exc})."
        self._hook(
            "PostToolUse",
            tool,
            "code_record_edit",
            "recorded",
            f"{len(record.get('change_ids', []))} change(s)",
            started,
        )
        self._emit("graph_changed")
        return None

    # ---- relay operations the harness and session use directly ----

    async def announce_intent(self, task: str) -> None:
        """Tell the relay what this agent is about to touch. Symbols are the names the task mentions."""
        started = time.perf_counter()
        ids = await self._call("code_symbols", {"tenant": self.session_id}) or []
        by_name = {sid.split("::", 1)[-1].split(".")[-1]: sid for sid in ids}
        words = set(re.findall(r"[A-Za-z_]\w*", task))
        symbols = sorted(by_name[w] for w in words if w in by_name)
        await self._call(
            "code_announce_intent",
            {"tenant": self.session_id, "agent": self.agent_id, "task": task, "symbols": symbols},
        )
        self._hook(
            "PreToolUse",
            "announce_intent",
            "code_announce_intent",
            "recorded",
            f"{len(symbols)} symbol(s)",
            started,
        )

    async def peer_changes(self) -> list[dict[str, Any]]:
        """Raw PeerNotice dicts for every teammate change this agent has not acknowledged."""
        return (
            await self._call("code_peer_activity", {"tenant": self.session_id, "agent": self.agent_id}) or []
        )

    async def unseen_notices(self) -> list[str]:
        """Every teammate change this agent has not acknowledged, as readable lines (team_context tool)."""
        notices = (
            await self._call("code_peer_activity", {"tenant": self.session_id, "agent": self.agent_id}) or []
        )
        now = self._now_ms()
        return [describe_notice(n, now) for n in notices]

    async def record_conflicts(self, conflicts: list[dict[str, Any]]) -> list[str]:
        """Put the conflicts a blocked write raised into the graph. Returns the Conflict node ids."""
        started = time.perf_counter()
        payload = await self._call(
            "code_record_conflicts",
            {"tenant": self.session_id, "agent": self.agent_id, "conflicts": conflicts},
        )
        ids = list((payload or {}).get("conflict_ids", []))
        self._hook(
            "PreToolUse",
            "write_file",
            "code_record_conflicts",
            "recorded",
            f"{len(ids)} conflict(s)",
            started,
        )
        return ids

    async def resolve_conflicts(self, conflict_ids: list[str], resolution: str) -> None:
        """Store the human's choice (adopt | override | pause) on the Conflict nodes."""
        if not conflict_ids:
            return
        started = time.perf_counter()
        payload = await self._call(
            "code_resolve_conflicts",
            {"tenant": self.session_id, "conflict_ids": conflict_ids, "resolution": resolution},
        )
        resolved = int((payload or {}).get("resolved", 0))
        self._hook(
            "PreToolUse",
            "write_file",
            "code_resolve_conflicts",
            "resolved",
            f"{resolution}: {resolved}",
            started,
        )

    async def acknowledge(self, change_ids: list[str]) -> None:
        if not change_ids:
            return
        await self._call(
            "code_acknowledge",
            {"tenant": self.session_id, "agent": self.agent_id, "change_ids": change_ids},
        )
