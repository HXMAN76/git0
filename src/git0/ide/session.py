"""Relay IDE sessions: one per demo visitor.

A session owns its two clones (workspaces), its FalkorDB graph `ide_<sid>`, its two coding agents, and the
event bus the browser subscribes to over SSE. Everything is torn down on "End session", on page close
(sendBeacon), by the idle sweeper, and (orphans only) at process start.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import shutil
import time
from collections import deque
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from redis.exceptions import ResponseError

from git0.code.relay import CodeRelay, code_graph_for
from git0.config import get_settings
from git0.core.db import get_db
from git0.ide.harness import CodingAgent
from git0.ide.hooks import RelayHooks

logger = logging.getLogger(__name__)

AGENT_LABELS = {"A": "Alice", "B": "Bob"}
EVENT_BUFFER = 500  # replayed to a reconnecting browser (a page reload restores the whole chat)
PING_EVERY_S = 15.0
SWEEP_EVERY_S = 30.0
QUESTION_TIMEOUT_S = 300.0  # an unanswered conflict question pauses the agent
_END = object()  # sentinel that closes a subscriber's stream


class SessionBusy(RuntimeError):
    """The demo has max live sessions already (API maps to 503)."""


class SessionNotFound(KeyError):
    """Unknown or expired session id (API maps to 404 'session expired')."""


class Session:
    def __init__(
        self,
        *,
        sid: str,
        root: Path,
        workspaces: dict[str, Path],
        relay: CodeRelay,
        clock: Callable[[], float],
    ) -> None:
        self.id = sid
        self.root = root
        self.workspaces = workspaces
        self.relay = relay
        self.agents: dict[str, CodingAgent] = {}
        self.hooks: dict[str, RelayHooks] = {}
        self._clock = clock
        self.last_seen = clock()
        self.no_subscriber_since: float | None = clock()  # counts from creation until the first SSE connects
        self._buffer: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER)
        self._subscribers: list[asyncio.Queue[Any]] = []
        self._pending: dict[str, tuple[asyncio.Future[str], set[str]]] = {}
        self.ended = False
        # path -> the peer version an agent pulled on "adopt". After a pull that version is the two clones'
        # common ancestor (like the merge base after `git pull`), so merge-check must diff against it.
        self.pull_base: dict[str, bytes] = {}

    # ---- event bus ----

    def emit(self, event_type: str, /, **data: Any) -> None:
        event = {"type": event_type, "ts": int(time.time() * 1000), **data}
        self._buffer.append(event)
        for q in self._subscribers:
            q.put_nowait(event)

    async def events(self) -> AsyncIterator[dict[str, Any] | None]:
        """Replay the buffer, then stream live events. Yields None every PING_EVERY_S while idle."""
        q: asyncio.Queue[Any] = asyncio.Queue()
        # Snapshot and subscribe in one synchronous step: no event is missed or replayed twice.
        replay = list(self._buffer)
        self._subscribers.append(q)
        self.no_subscriber_since = None
        self.touch()
        try:
            for event in replay:
                yield event
            while True:
                try:
                    item = await asyncio.wait_for(q.get(), PING_EVERY_S)
                except TimeoutError:
                    yield None
                    continue
                if item is _END:
                    return
                yield item
        finally:
            self._subscribers.remove(q)
            if not self._subscribers:
                self.no_subscriber_since = self._clock()

    def touch(self) -> None:
        self.last_seen = self._clock()

    # ---- human-in-the-loop questions ----

    async def ask(self, agent: str, question: str, options: list[dict[str, str]]) -> str:
        """Pause until the human picks an option. Timeout or session end answers "pause"."""
        qid = secrets.token_hex(6)
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[qid] = (fut, {o["id"] for o in options})
        self.emit("ask_user", agent=agent, question_id=qid, question=question, options=options)
        try:
            choice = await asyncio.wait_for(fut, QUESTION_TIMEOUT_S)
        except TimeoutError:
            choice = "pause"
        finally:
            self._pending.pop(qid, None)
        self.emit("ask_resolved", agent=agent, question_id=qid, choice=choice)
        return choice

    def answer(self, qid: str, choice: str) -> None:
        """Raises KeyError for an unknown or already answered question, ValueError for a bad option."""
        if qid not in self._pending:
            raise KeyError(qid)
        fut, valid = self._pending[qid]
        if choice not in valid:
            raise ValueError(f"choice must be one of {sorted(valid)}")
        if not fut.done():
            fut.set_result(choice)

    # ---- queries ----

    def agent(self, agent_id: str) -> CodingAgent:
        if agent_id not in self.agents:
            raise KeyError(agent_id)
        return self.agents[agent_id]

    def file_list(self, agent_id: str = "A") -> list[str]:
        root = self.workspaces[agent_id]
        return sorted(
            p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts
        )

    # ---- teardown ----

    async def close(self, reason: str) -> None:
        if self.ended:
            return
        self.ended = True
        for agent in self.agents.values():
            agent.cancel()
        for fut, _ in self._pending.values():
            if not fut.done():
                fut.set_result("pause")  # an agent waiting on a question must not hang
        self.emit("session_ended", reason=reason)
        for q in self._subscribers:
            q.put_nowait(_END)
        for hooks in self.hooks.values():
            await hooks.close()


class SessionManager:
    """Owns every live session. Use `get_manager()` in the app; tests pass a fake clock."""

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._sessions: dict[str, Session] = {}
        self._clock = clock
        self._creating = 0  # slots reserved by creates still seeding, so the cap holds under concurrency
        # Set once the startup orphan cleanup has finished. create() waits for it, so a new session's
        # graph can never be deleted as an "orphan" by a cleanup that was still listing graphs.
        self._cleaned = asyncio.Event()

    def live(self) -> list[Session]:
        return list(self._sessions.values())

    def get(self, sid: str) -> Session:
        session = self._sessions.get(sid)
        if session is None:
            raise SessionNotFound(sid)
        session.touch()
        return session

    async def create(self) -> Session:
        await self._cleaned.wait()
        s = get_settings()
        if len(self._sessions) + self._creating >= s.ide_max_sessions:
            raise SessionBusy("Demo is busy, try again in a minute")
        self._creating += 1
        sid = secrets.token_hex(6)  # 12 hex chars: a valid tenant id (^[a-z0-9_]{1,40}$)
        root = Path(s.ide_workspace_root) / sid
        try:
            files, workspaces = await asyncio.to_thread(_prepare_clones, Path(s.ide_template_dir), root)
            session = Session(
                sid=sid,
                root=root,
                workspaces=workspaces,
                relay=CodeRelay(code_graph_for(sid)),
                clock=self._clock,
            )
            await session.relay.seed(files, dict(AGENT_LABELS))
            for agent_id, label in AGENT_LABELS.items():
                hooks = RelayHooks(
                    session_id=sid,
                    agent_id=agent_id,
                    workspace=workspaces[agent_id],
                    mcp_url=s.effective_ide_mcp_url,
                    emit=session.emit,
                )
                session.hooks[agent_id] = hooks
                session.agents[agent_id] = CodingAgent(
                    agent_id=agent_id,
                    label=label,
                    workspace=workspaces[agent_id],
                    session=session,
                    hooks=hooks,
                )
        except BaseException:
            # Partial creation: remove what exists so a failed seed leaves no graph or directory behind.
            await _delete_graph(sid)
            shutil.rmtree(root, ignore_errors=True)
            raise
        finally:
            self._creating -= 1

        self._sessions[sid] = session
        session.emit("session", session_id=sid, agents=self.agent_info(), files=session.file_list("A"))
        logger.info("IDE session %s created", sid)
        return session

    def agent_info(self) -> dict[str, dict[str, str]]:
        model = get_settings().ide_model
        return {aid: {"label": label, "model": model} for aid, label in AGENT_LABELS.items()}

    async def end(self, sid: str, reason: str = "ended") -> None:
        session = self._sessions.pop(sid, None)
        if session is None:
            raise SessionNotFound(sid)
        await session.close(reason)
        await _delete_graph(sid)
        shutil.rmtree(session.root, ignore_errors=True)
        logger.info("IDE session %s ended (%s)", sid, reason)

    def expired(self, now: float | None = None) -> dict[str, str]:
        """Sessions to end now, as {sid: reason}. Pure: the fake-clock tests call this directly."""
        s = get_settings()
        now = self._clock() if now is None else now
        out: dict[str, str] = {}
        for sid, session in self._sessions.items():
            if now - session.last_seen > s.ide_session_ttl_s:
                out[sid] = "idle"
            elif (
                session.no_subscriber_since is not None
                and now - session.no_subscriber_since > s.ide_disconnect_grace_s
            ):
                out[sid] = "disconnected"
        return out

    async def sweep(self, now: float | None = None) -> list[str]:
        ended = []
        for sid, reason in self.expired(now).items():
            try:
                await self.end(sid, reason=f"session {reason}")
                ended.append(sid)
            except Exception:  # keep sweeping the rest; the failure is logged loudly
                logger.exception("IDE sweep failed to end session %s", sid)
        return ended

    async def run_sweeper(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_EVERY_S)
            try:
                await self.sweep()
            except Exception:
                logger.exception("IDE sweeper pass failed")

    async def cleanup_orphans(self) -> None:
        """Process start: any ide_* graph and the workspace root belong to a dead process. Remove them."""
        try:
            db = get_db()
            for name in await db.list_graphs():
                if name.startswith("ide_"):
                    await _delete_graph(name.removeprefix("ide_"))
            shutil.rmtree(Path(get_settings().ide_workspace_root), ignore_errors=True)
        finally:
            self._cleaned.set()  # even on failure: a dead DB must not stop the demo from creating sessions

    async def shutdown(self) -> None:
        for sid in list(self._sessions):
            try:
                await self.end(sid, reason="server shutdown")
            except Exception:
                logger.exception("IDE shutdown failed to end session %s", sid)


_manager: SessionManager | None = None


def get_manager() -> SessionManager:
    global _manager
    if _manager is None:
        _manager = SessionManager()
    return _manager


def _prepare_clones(template: Path, root: Path) -> tuple[dict[str, str], dict[str, Path]]:
    """Blocking file work, run in a thread: read the template and make the two clones (A and B)."""
    if not template.is_dir():
        raise RuntimeError(f"demo template not found: {template}")
    files = _read_template(template)
    workspaces = {"A": root / "a", "B": root / "b"}
    for ws in workspaces.values():
        shutil.copytree(template, ws, ignore=shutil.ignore_patterns("__pycache__", ".git"))
    return files, workspaces


def _read_template(template: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for p in template.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            files[p.relative_to(template).as_posix()] = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            logger.warning("skipping non-utf8 template file %s", p)
    return files


async def _delete_graph(sid: str) -> None:
    """GRAPH.DELETE ide_<sid>. A graph that never got created is not an error (FalkorDB says 'empty key')."""
    try:
        await code_graph_for(sid).delete()
    except ResponseError as exc:
        if "empty key" not in str(exc):
            raise
