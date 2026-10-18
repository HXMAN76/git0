"""CodingAgent: an open-source agent harness (pydantic-ai) whose tool calls go through the git0 relay hooks.

Why the harness, not the model, asks the human on a conflict: a cheap model can skip the question or word it
badly. The deny path is deterministic: hook says block -> harness asks -> harness applies the answer.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.models import Model
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.usage import UsageLimits

from git0.config import get_settings

if TYPE_CHECKING:  # runtime import would be circular (session builds CodingAgent)
    from git0.ide.hooks import HookDecision, RelayHooks
    from git0.ide.session import Session

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 400_000
MAX_WRITE_BYTES = 200_000
REQUEST_LIMIT_PER_TURN = 20  # model calls per user message; stops a looping model from burning quota
SKIP_DIRS = {".git", "__pycache__"}

SYSTEM_PROMPT = """You are a coding agent working in your own clone of the team's Python repo,
on {label}'s laptop. Make the smallest change that does what the user asks.
- Repo paths are relative with forward slashes, for example shop/cart.py.
- Always read_file a file before you edit it.
- write_file takes the FULL new content of the file plus a one-line summary.
- If a tool result says a write was BLOCKED, follow the user's decision written in that result. Do not retry
  the same write unchanged.
- When you are done, reply in at most two sentences saying what you changed."""


class SandboxError(ValueError):
    """A path escaped the workspace or was not a plain repo-relative path."""


class AgentBusy(RuntimeError):
    """A turn is already running for this agent (API maps to 409)."""


class TurnLimitReached(RuntimeError):
    """The per-agent message budget is used up (API maps to 429)."""


def resolve_in_workspace(workspace: Path, rel: str) -> Path:
    """Map a repo-relative path to an absolute path inside `workspace`, or raise SandboxError.

    Rejected before any filesystem access: absolute paths, drive letters, backslashes, '..', '.', and '.git'.
    The resolved path is checked again so a symlink inside the clone cannot point outside it.
    """
    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
        raise SandboxError("path must be a non-empty string")
    if "\\" in rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise SandboxError(f"path must be repo-relative with forward slashes: {rel!r}")
    # Split the raw string: PurePosixPath silently drops "." and "" parts, and the relay keys its graph on the
    # exact path string, so "./shop/cart.py" is refused rather than quietly normalised.
    raw_parts = rel.split("/")
    if any(p in ("..", ".", "") for p in raw_parts) or raw_parts[0] == ".git":
        raise SandboxError(f"path must be a clean repo-relative path: {rel!r}")
    parts = PurePosixPath(rel).parts
    root = workspace.resolve()
    target = (root / Path(*parts)).resolve()
    if target != root and root not in target.parents:
        raise SandboxError(f"path is outside the repo: {rel!r}")
    return target


def files_of_conflict(conflict: dict[str, Any]) -> set[str]:
    """Repo files a conflict touches: the file part of every symbol id ("<path>::<qualname>") in it."""
    ids = [conflict.get("symbol", ""), *conflict.get("path", [])]
    return {i.split("::", 1)[0] for i in ids if "::" in i}


def _model_for(name: str) -> Model:
    key = get_settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set: the IDE agents cannot run")
    return GoogleModel(name, provider=GoogleProvider(api_key=key))


class CodingAgent:
    def __init__(
        self,
        *,
        agent_id: str,
        label: str,
        workspace: Path,
        session: Session,
        hooks: RelayHooks,
        model_factory: Callable[[str], Model] | None = None,
    ) -> None:
        s = get_settings()
        self.agent_id = agent_id
        self.label = label
        self.workspace = workspace
        self.session = session
        self.hooks = hooks
        self.model_name = s.ide_model
        self.max_turns = s.ide_max_turns_per_agent
        self.turns_used = 0
        self._history: list[Any] = []
        self._task: asyncio.Task[None] | None = None
        self._last_error = ""
        make = model_factory or _model_for
        self._primary: Agent[None, str] = self._build(make(s.ide_model))
        self._fallback: Agent[None, str] = self._build(make(s.ide_fallback_model))

    # ---- tools: plain async methods so pydantic-ai reads their signatures and docstrings ----

    async def list_files(self) -> str:
        """List every file in the repo (repo-relative paths)."""
        return await self._run_tool("list_files", {}, self._do_list)

    async def read_file(self, path: str) -> str:
        """Read a repo file. Returns its content with line numbers."""
        return await self._run_tool("read_file", {"path": path}, lambda: self._do_read(path))

    async def write_file(self, path: str, content: str, summary: str) -> str:
        """Write the FULL new content of a repo file. summary is one line describing the change."""
        args = {"path": path, "content": content, "summary": summary}
        return await self._run_tool("write_file", args, lambda: self._do_write(path, content))

    async def team_context(self) -> str:
        """Show what teammates changed in the repo that you have not seen yet."""
        return await self._run_tool("team_context", {}, self._do_team)

    def _build(self, model: Model) -> Agent[None, str]:
        return Agent(
            model,
            instructions=SYSTEM_PROMPT.format(label=self.label),
            tools=[self.list_files, self.read_file, self.write_file, self.team_context],
        )

    # ---- the hook pipeline every tool call goes through ----

    async def _run_tool(self, name: str, args: dict[str, Any], fn: Callable[[], Any]) -> str:
        s = self.session
        call_id = uuid.uuid4().hex[:8]
        public_args = {k: v for k, v in args.items() if k != "content"}  # never echo file bodies in the chat
        s.emit("tool_call", agent=self.agent_id, call_id=call_id, tool=name, args=public_args)

        if "path" in args:
            try:
                resolve_in_workspace(self.workspace, args["path"])
            except SandboxError as exc:
                return self._finish(call_id, name, False, f"ERROR: {exc}")

        decision: HookDecision = await self.hooks.pre_tool_use(name, args)
        if decision.action == "deny":
            if not decision.conflicts:  # hard block (relay down): nothing for the human to choose
                return self._finish(call_id, name, False, decision.message)
            return await self._conflict(call_id, name, args, decision, fn)

        out = await self._exec(name, fn)
        if out is None:
            return self._finish(call_id, name, False, self._last_error)
        if decision.action == "context":  # a heads-up from a teammate rides along with the result
            out += f"\n\n[git0 relay] {decision.message}"
        if name == "write_file":
            s.emit("file_changed", agent=self.agent_id, path=args["path"], content=args["content"])
            warning = await self.hooks.post_tool_use(name, args, out)
            if warning:
                out += f"\n\n[git0 relay] {warning}"
        return self._finish(call_id, name, True, out)

    async def _exec(self, name: str, fn: Callable[[], Any]) -> str | None:
        """Run a tool body. Returns its text, or None with the error kept in self._last_error.

        Expected failures (bad path, missing file) go back to the model so it can recover. Anything else is
        also emitted as an `error` event, so the UI shows it instead of hiding it inside the chat.
        """
        try:
            result = fn()
            if inspect.isawaitable(result):
                result = await result
            return str(result)
        except (OSError, SandboxError, ValueError) as exc:
            self._last_error = f"ERROR: {exc}"
            return None
        except Exception as exc:
            logger.exception("IDE tool %s failed", name)
            self.session.emit("error", agent=self.agent_id, message=f"{name} failed: {exc}")
            self._last_error = f"ERROR: {name} failed: {exc}"
            return None

    def _finish(self, call_id: str, name: str, ok: bool, out: str) -> str:
        self.session.emit(
            "tool_result", agent=self.agent_id, call_id=call_id, tool=name, ok=ok, summary=out[:160]
        )
        return out

    async def _conflict(
        self, call_id: str, name: str, args: dict[str, Any], decision: HookDecision, fn: Callable[[], Any]
    ) -> str:
        s = self.session
        peer = sorted({c["peer"] for c in decision.conflicts})[0]
        peer_label = s.agents[peer].label if peer in s.agents else peer
        s.emit("conflict", agent=self.agent_id, conflicts=decision.conflicts)
        options = [
            {
                "id": "adopt",
                "label": f"Pull {peer_label}'s change and rework mine on top",
                "description": f"Copy {peer_label}'s current files into my clone, then redo my edit.",
            },
            {
                "id": "override",
                "label": f"Keep my version anyway (I'll talk to {peer_label})",
                "description": "Write my version now. The conflict stays visible in the graph.",
            },
            {
                "id": "pause",
                "label": f"Stop - let {peer_label} finish first",
                "description": "Stop this agent. Nothing is written.",
            },
        ]
        choice = await s.ask(self.agent_id, decision.message, options)

        if choice == "adopt":
            out = await self._adopt(peer, decision.conflicts)
            return self._finish(call_id, name, False, out)
        if choice == "override":
            await self.hooks.acknowledge(
                [c["peer_change_id"] for c in decision.conflicts if c.get("peer_change_id")]
            )
            out = await self._exec(name, fn)
            if out is None:
                return self._finish(call_id, name, False, self._last_error)
            s.emit("file_changed", agent=self.agent_id, path=args["path"], content=args["content"])
            warning = await self.hooks.post_tool_use(name, args, out)
            text = "Written (user override)" + (f"\n\n[git0 relay] {warning}" if warning else "")
            return self._finish(call_id, name, True, text)
        return self._finish(call_id, name, False, "BLOCKED. User paused you. Stop and summarise.")

    async def _adopt(self, peer: str, conflicts: list[dict[str, Any]]) -> str:
        """Simulated `git pull`: copy the peer's version of every file it changed that this agent has not
        absorbed yet (not only the conflicting one), then acknowledge all of those changes. Pulling only the
        conflicting file let later peer edits (cart.py after pricing.py) block the redo again."""
        s = self.session
        pending = [n for n in await self.hooks.peer_changes() if n.get("agent") == peer]
        rels = {p for c in conflicts for p in files_of_conflict(c)}
        rels |= {n["symbol"].split("::", 1)[0] for n in pending if "::" in n.get("symbol", "")}
        copied: list[str] = []
        for rel in sorted(rels):
            src = s.workspaces[peer] / rel
            if not src.is_file():
                continue
            dst = resolve_in_workspace(self.workspace, rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            data = src.read_bytes()
            dst.write_bytes(data)
            s.pull_base[rel] = data
            copied.append(rel)
            s.emit("file_changed", agent=self.agent_id, path=rel, content=data.decode("utf-8", "replace"))
        ids = {c["peer_change_id"] for c in conflicts if c.get("peer_change_id")}
        ids |= {n["change_id"] for n in pending}
        await self.hooks.acknowledge(sorted(ids))
        peer_label = s.agents[peer].label if peer in s.agents else peer
        summaries = "; ".join(
            dict.fromkeys([c["peer_summary"] for c in conflicts] + [n["summary"] for n in pending])
        )
        files = ", ".join(copied) or "the conflicting files"
        return (
            f"BLOCKED. User chose to adopt {peer_label}'s change. {peer_label}'s version of {files} "
            f"is now in your workspace. Re-read them and redo your edit on top so it works with: {summaries}."
        )

    # ---- the real tool bodies ----

    def _do_list(self) -> str:
        files = []
        for p in sorted(self.workspace.rglob("*")):
            rel = p.relative_to(self.workspace)
            if p.is_file() and not (SKIP_DIRS & set(rel.parts)):
                files.append(rel.as_posix())
        return "\n".join(files) or "(no files)"

    def _do_read(self, path: str) -> str:
        target = resolve_in_workspace(self.workspace, path)
        if not target.is_file():
            raise OSError(f"no such file: {path}")
        raw = target.read_bytes()
        if len(raw) > MAX_FILE_BYTES:
            raise OSError(f"{path} is too large to read ({len(raw)} bytes)")
        lines = raw.decode("utf-8", "replace").splitlines()
        return "\n".join(f"{i:>4}| {line}" for i, line in enumerate(lines, start=1)) or "(empty file)"

    def _do_write(self, path: str, content: str) -> str:
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise OSError(f"content too large ({len(data)} bytes)")
        target = resolve_in_workspace(self.workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)  # bytes, not text mode: no CRLF translation on Windows
        return f"Written {path} ({content.count(chr(10)) + 1} lines)."

    async def _do_team(self) -> str:
        notes = await self.hooks.unseen_notices()
        return "\n".join(notes) if notes else "No changes from teammates that you have not seen."

    # ---- turns ----

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def send(self, text: str) -> None:
        """Start one user turn in the background. Raises AgentBusy / TurnLimitReached before starting."""
        if self.busy:
            raise AgentBusy(f"agent {self.agent_id} is still working")
        if self.turns_used >= self.max_turns:
            raise TurnLimitReached(f"agent {self.agent_id} has used its {self.max_turns} messages")
        self.turns_used += 1
        self._task = asyncio.create_task(self._turn(text), name=f"ide-turn-{self.agent_id}")

    def cancel(self) -> None:
        if self.busy:
            self._task.cancel()  # type: ignore[union-attr]

    async def _turn(self, text: str) -> None:
        s = self.session
        s.emit("agent_message", agent=self.agent_id, role="user", text=text)
        s.emit("agent_status", agent=self.agent_id, status="thinking")
        try:
            await self.hooks.announce_intent(text)
            result = await self._run_with_fallback(text)
            self._history = list(result.all_messages())
            s.emit("agent_message", agent=self.agent_id, role="assistant", text=str(result.output))
            usage = result.usage
            s.emit(
                "usage",
                agent=self.agent_id,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                requests=usage.requests,
            )
            s.emit("agent_status", agent=self.agent_id, status="idle")
        except asyncio.CancelledError:
            raise  # session ended or the process is shutting down
        except Exception as exc:  # loud: the UI shows the error; never a canned reply
            logger.exception("IDE agent %s turn failed", self.agent_id)
            s.emit("error", agent=self.agent_id, message=f"{type(exc).__name__}: {exc}")
            s.emit("agent_status", agent=self.agent_id, status="error")

    async def _run_with_fallback(self, text: str) -> Any:
        limits = UsageLimits(request_limit=REQUEST_LIMIT_PER_TURN)
        try:
            return await self._primary.run(text, message_history=self._history, usage_limits=limits)
        except UsageLimitExceeded:
            raise  # the fallback model would hit the same per-turn budget
        except Exception as exc:
            fallback = get_settings().ide_fallback_model
            logger.warning("IDE model %s failed (%s); retrying once on %s", self.model_name, exc, fallback)
            return await self._fallback.run(text, message_history=self._history, usage_limits=limits)
