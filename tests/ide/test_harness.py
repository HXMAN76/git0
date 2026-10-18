"""The harness tool loop, with a scripted pydantic-ai FunctionModel (no network) and a fake hooks object.

Covers: an allowed write, the conflict path (override / adopt / pause) where the harness asks the human,
a sandbox escape that never reaches the hooks, and the per-agent turn budget.
"""

import asyncio
from pathlib import Path

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from git0.code.relay import ConflictInfo
from git0.ide import session as session_mod
from git0.ide.harness import AgentBusy, CodingAgent, TurnLimitReached
from git0.ide.hooks import HookDecision
from git0.ide.session import Session


class FakeClock:
    def __call__(self) -> float:
        return 0.0


class FakeHooks:
    def __init__(self, decision: HookDecision | None = None) -> None:
        self.decision = decision or HookDecision()
        self.pre: list[tuple[str, dict]] = []
        self.posted: list[str] = []
        self.acked: list[str] = []
        self.recorded: list[list[dict]] = []
        self.resolved: list[tuple[list[str], str]] = []

    async def pre_tool_use(self, tool: str, args: dict) -> HookDecision:
        self.pre.append((tool, args))
        return self.decision if tool == "write_file" else HookDecision()

    async def post_tool_use(self, tool: str, args: dict, result: str) -> None:
        self.posted.append(tool)

    async def announce_intent(self, task: str) -> None:
        return None

    async def peer_changes(self) -> list[dict]:
        return []

    async def unseen_notices(self) -> list[str]:
        return []

    async def acknowledge(self, ids: list[str]) -> None:
        self.acked.extend(ids)

    async def record_conflicts(self, conflicts: list[dict]) -> list[str]:
        self.recorded.append(conflicts)
        return [f"cf{i}" for i, _ in enumerate(conflicts)]

    async def resolve_conflicts(self, ids: list[str], resolution: str) -> None:
        self.resolved.append((ids, resolution))

    async def close(self) -> None:
        return None


def write_call(path: str, content: str) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart("write_file", {"path": path, "content": content, "summary": "edit"})]
    )


def scripted(*responses: ModelResponse) -> FunctionModel:
    queue = list(responses)

    def respond(messages, info):  # pydantic-ai calls this once per model request
        return queue.pop(0)

    return FunctionModel(respond)


def build(tmp_path: Path, hooks: FakeHooks, *responses: ModelResponse) -> tuple[CodingAgent, Session]:
    sid = "t" + tmp_path.name[-6:]
    root = tmp_path / "root"
    workspaces = {"A": root / "a", "B": root / "b"}
    for ws in workspaces.values():
        (ws / "shop").mkdir(parents=True)
        (ws / "shop" / "pricing.py").write_text(
            "def apply_tax(amount):\n    return amount\n", encoding="utf-8"
        )
    session = Session(sid=sid, root=root, workspaces=workspaces, relay=None, clock=FakeClock())  # type: ignore[arg-type]
    session.agents = {}
    agent = CodingAgent(
        agent_id="A",
        label="Alice",
        workspace=workspaces["A"],
        session=session,
        hooks=hooks,  # type: ignore[arg-type]
        model_factory=lambda name: scripted(*responses),
    )
    session.agents["A"] = agent
    return agent, session


def events(session: Session, kind: str) -> list[dict]:
    return [e for e in session._buffer if e["type"] == kind]


async def answer_when_asked(session: Session, choice: str) -> None:
    # Poll the replay buffer: the harness emits ask_user, then waits on the future we resolve here.
    while not events(session, "ask_user"):  # noqa: ASYNC110 - test helper; a short poll reads clearer than an Event
        await asyncio.sleep(0.01)
    session.answer(events(session, "ask_user")[-1]["question_id"], choice)


async def test_allowed_write_lands_and_is_recorded(tmp_path: Path) -> None:
    hooks = FakeHooks()
    agent, session = build(
        tmp_path,
        hooks,
        write_call("shop/pricing.py", "def apply_tax(amount, region):\n    return amount\n"),
        ModelResponse(parts=[TextPart("Added region to apply_tax.")]),
    )
    agent.send("add region tax")
    await agent._task  # type: ignore[misc]

    written = (agent.workspace / "shop" / "pricing.py").read_text(encoding="utf-8")
    assert "region" in written
    assert hooks.posted == ["write_file"]
    assert [e["ok"] for e in events(session, "tool_result")] == [True]
    assert events(session, "file_changed")[0]["path"] == "shop/pricing.py"
    assert events(session, "agent_message")[-1]["text"] == "Added region to apply_tax."
    assert [e["status"] for e in events(session, "agent_status")][-1] == "idle"


async def test_conflict_override_writes_and_acknowledges(tmp_path: Path) -> None:
    block = ConflictInfo(
        kind="dependency",
        severity="block",
        symbol="shop/pricing.py::apply_tax",
        peer="B",
        peer_change_id="peer1",
        peer_summary="B changed apply_tax",
        path=[],
        message="Bob changed apply_tax.",
    )
    hooks = FakeHooks(HookDecision(action="deny", message=block.message, conflicts=[block.model_dump()]))
    agent, session = build(
        tmp_path,
        hooks,
        write_call("shop/pricing.py", "MINE\n"),
        ModelResponse(parts=[TextPart("ok")]),
    )
    session.workspaces["B"] = agent.workspace.parent / "b"  # present so adopt has somewhere to copy from
    asyncio.create_task(answer_when_asked(session, "override"))
    agent.send("go")
    await agent._task  # type: ignore[misc]

    assert (agent.workspace / "shop" / "pricing.py").read_text(encoding="utf-8") == "MINE\n"
    assert hooks.acked == ["peer1"]
    assert hooks.posted == ["write_file"]
    result = [e for e in events(session, "tool_result") if e["tool"] == "write_file"][-1]
    assert result["ok"] is True and "override" in result["summary"]
    assert events(session, "conflict")[0]["conflicts"][0]["peer"] == "B"
    assert events(session, "conflict")[0]["conflict_ids"] == ["cf0"]
    assert len(hooks.recorded) == 1 and hooks.resolved == [(["cf0"], "override")]


async def test_conflict_adopt_copies_peer_file_and_writes_nothing(tmp_path: Path) -> None:
    block = ConflictInfo(
        kind="same_symbol",
        severity="block",
        symbol="shop/pricing.py::apply_tax",
        peer="B",
        peer_change_id="peer2",
        peer_summary="B changed apply_tax",
        path=["shop/pricing.py::apply_tax"],
        message="Bob changed apply_tax.",
    )
    hooks = FakeHooks(HookDecision(action="deny", message=block.message, conflicts=[block.model_dump()]))
    agent, session = build(
        tmp_path,
        hooks,
        write_call("shop/pricing.py", "MINE\n"),
        ModelResponse(parts=[TextPart("re-read")]),
    )
    peer_ws = agent.workspace.parent / "b"
    (peer_ws / "shop").mkdir(parents=True, exist_ok=True)
    (peer_ws / "shop" / "pricing.py").write_text("PEER\n", encoding="utf-8")
    session.workspaces["B"] = peer_ws
    asyncio.create_task(answer_when_asked(session, "adopt"))
    agent.send("go")
    await agent._task  # type: ignore[misc]

    assert (agent.workspace / "shop" / "pricing.py").read_text(encoding="utf-8") == "PEER\n"
    assert hooks.acked == ["peer2"]
    assert hooks.posted == []  # adopt is not a write: nothing is recorded as Alice's edit
    assert hooks.resolved == [(["cf0"], "adopt")]
    result = [e for e in events(session, "tool_result") if e["tool"] == "write_file"][-1]
    assert result["ok"] is False and "BLOCKED" in result["summary"]


async def test_conflict_pause_writes_nothing(tmp_path: Path) -> None:
    block = ConflictInfo(
        kind="same_symbol",
        severity="block",
        symbol="shop/pricing.py::apply_tax",
        peer="B",
        peer_change_id="peer3",
        peer_summary="B changed apply_tax",
        path=[],
        message="Bob changed apply_tax.",
    )
    hooks = FakeHooks(HookDecision(action="deny", message=block.message, conflicts=[block.model_dump()]))
    agent, session = build(
        tmp_path,
        hooks,
        write_call("shop/pricing.py", "MINE\n"),
        ModelResponse(parts=[TextPart("stopped")]),
    )
    session.workspaces["B"] = agent.workspace.parent / "b"
    asyncio.create_task(answer_when_asked(session, "pause"))
    agent.send("go")
    await agent._task  # type: ignore[misc]

    assert (agent.workspace / "shop" / "pricing.py").read_text(
        encoding="utf-8"
    ) == "def apply_tax(amount):\n    return amount\n"
    assert hooks.posted == []
    assert hooks.resolved == [(["cf0"], "pause")]


async def test_path_escape_is_refused_before_any_hook(tmp_path: Path) -> None:
    hooks = FakeHooks()
    agent, session = build(
        tmp_path,
        hooks,
        write_call("../outside.py", "x"),
        ModelResponse(parts=[TextPart("sorry")]),
    )
    agent.send("escape")
    await agent._task  # type: ignore[misc]

    assert not (agent.workspace.parent / "outside.py").exists()
    assert all(tool != "write_file" for tool, _ in hooks.pre)  # the sandbox check ran first
    assert [e["ok"] for e in events(session, "tool_result")] == [False]


async def test_turn_budget_and_busy_guard(tmp_path: Path, monkeypatch) -> None:
    from git0.config import get_settings

    monkeypatch.setattr(get_settings(), "ide_max_turns_per_agent", 1)
    agent, _ = build(tmp_path, FakeHooks(), ModelResponse(parts=[TextPart("hi")]))
    agent.send("first")
    with pytest.raises(AgentBusy):
        agent.send("second while running")
    await agent._task  # type: ignore[misc]
    with pytest.raises(TurnLimitReached):
        agent.send("third")


def test_session_module_constants_are_sane() -> None:
    assert session_mod.EVENT_BUFFER == 500
    assert session_mod.PING_EVERY_S < 30
