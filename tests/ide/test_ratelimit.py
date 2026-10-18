"""Gemini free-tier rate limits in the IDE harness, with scripted models (no network, no real sleeps).

Covers: a 429 across the whole chain waits the API's retryDelay then completes; the wait is capped; retries
run out into the friendly error; other errors are summarised, not dumped as JSON; chain order per agent.
"""

from pathlib import Path

from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import FunctionModel

from git0.config import get_settings
from git0.ide import harness as harness_mod
from git0.ide.harness import RATE_LIMIT_MESSAGE, CodingAgent
from git0.ide.session import Session


class FakeClock:
    def __call__(self) -> float:
        return 0.0


class FakeHooks:
    async def announce_intent(self, task: str) -> None:
        return None


def gemini_429(delay: str = "25s") -> ModelHTTPError:
    """The shape GoogleModel raises: the JSON error body, with RetryInfo.retryDelay inside."""
    body = {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "Quota exceeded for metric generate_content_free_tier_requests per minute per model.",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": delay}],
        }
    }
    return ModelHTTPError(status_code=429, model_name="gemini-test", body=body)


class Quota:
    """Shared by every model in the chain, like the real per-model quota: the first `fail_calls` get a 429."""

    def __init__(self, fail_calls: int, delay: str = "25s") -> None:
        self.fail_calls = fail_calls
        self.delay = delay
        self.calls = 0

    def respond(self, messages, info) -> ModelResponse:  # pydantic-ai calls this once per model request
        self.calls += 1
        if self.calls <= self.fail_calls:
            raise gemini_429(self.delay)
        return ModelResponse(parts=[TextPart("done")])


def build(tmp_path: Path, model_factory) -> tuple[CodingAgent, Session]:
    root = tmp_path / "root"
    workspaces = {"A": root / "a", "B": root / "b"}
    session = Session(
        sid="rl" + tmp_path.name[-6:], root=root, workspaces=workspaces, relay=None, clock=FakeClock()
    )  # type: ignore[arg-type]
    agent = CodingAgent(
        agent_id="A",
        label="Alice",
        workspace=workspaces["A"],
        session=session,
        hooks=FakeHooks(),  # type: ignore[arg-type]
        model_factory=model_factory,
    )
    session.agents = {"A": agent}
    return agent, session


def events(session: Session, kind: str) -> list[dict]:
    return [e for e in session._buffer if e["type"] == kind]


def record_pauses(monkeypatch) -> list[float]:
    """Replace the real sleep: the test records each pause and returns at once."""
    pauses: list[float] = []

    async def fake_pause(seconds: float) -> None:
        pauses.append(seconds)

    monkeypatch.setattr(harness_mod, "_pause", fake_pause)
    return pauses


async def test_429_on_every_model_waits_the_retry_delay_then_completes(tmp_path: Path, monkeypatch) -> None:
    pauses = record_pauses(monkeypatch)
    quota = Quota(fail_calls=4)  # the 4-model chain 429s once each, then the retry succeeds
    agent, session = build(tmp_path, lambda name: FunctionModel(quota.respond))

    agent.send("make the change")
    await agent._task  # type: ignore[misc]

    assert pauses == [25.0]  # RetryInfo.retryDelay "25s"
    assert quota.calls == 5
    assert events(session, "error") == []
    assert events(session, "agent_message")[-1]["text"] == "done"
    statuses = [e["status"] for e in events(session, "agent_status")]
    rate = [e for e in events(session, "agent_status") if e["status"] == "rate_limited"]
    assert len(rate) == 1
    assert "waiting 25 s" in rate[0]["detail"]
    assert "15 requests/min per model" in rate[0]["detail"]
    assert statuses[statuses.index("rate_limited") + 1] == "thinking"  # back to thinking after the wait
    assert statuses[-1] == "idle"


async def test_retry_delay_is_capped_at_max_wait(tmp_path: Path, monkeypatch) -> None:
    pauses = record_pauses(monkeypatch)
    monkeypatch.setattr(get_settings(), "ide_rate_limit_max_wait_s", 10)
    quota = Quota(fail_calls=4, delay="60s")
    agent, session = build(tmp_path, lambda name: FunctionModel(quota.respond))

    agent.send("go")
    await agent._task  # type: ignore[misc]

    assert pauses == [10.0]
    assert events(session, "agent_message")[-1]["text"] == "done"


async def test_exhausted_retries_show_the_friendly_error_not_the_json(tmp_path: Path, monkeypatch) -> None:
    pauses = record_pauses(monkeypatch)
    monkeypatch.setattr(get_settings(), "ide_rate_limit_retries", 2)
    quota = Quota(fail_calls=10**6)  # never recovers
    agent, session = build(tmp_path, lambda name: FunctionModel(quota.respond))

    agent.send("go")
    await agent._task  # type: ignore[misc]

    assert pauses == [25.0, 25.0]  # two retries, then give up
    assert quota.calls == 4 * 3  # each attempt walks the whole 4-model chain
    errors = events(session, "error")
    assert [e["message"] for e in errors] == [RATE_LIMIT_MESSAGE]
    assert "RESOURCE_EXHAUSTED" not in errors[0]["message"]
    assert [e["status"] for e in events(session, "agent_status")][-1] == "error"


async def test_other_http_error_is_summarised_to_200_chars(tmp_path: Path) -> None:
    long_message = "x" * 500

    def refuse(messages, info) -> ModelResponse:
        raise ModelHTTPError(
            status_code=400,
            model_name="gemini-test",
            body={"error": {"code": 400, "message": long_message, "status": "INVALID_ARGUMENT"}},
        )

    agent, session = build(tmp_path, lambda name: FunctionModel(refuse))
    agent.send("go")
    await agent._task  # type: ignore[misc]

    [error] = events(session, "error")
    assert error["message"] == "Gemini error 400: " + "x" * 200
    assert [e["status"] for e in events(session, "agent_status")][-1] == "error"


async def test_chain_is_the_primary_then_the_rest_of_the_pool(tmp_path: Path) -> None:
    order: list[str] = []

    def factory(name: str) -> FunctionModel:
        order.append(name)
        return FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("ok")]))

    session = Session(sid="rlb", root=tmp_path, workspaces={}, relay=None, clock=FakeClock())  # type: ignore[arg-type]
    b_agent = CodingAgent(
        agent_id="B",
        label="Bob",
        workspace=tmp_path,
        session=session,
        hooks=FakeHooks(),  # type: ignore[arg-type]
        model_factory=factory,
    )
    assert b_agent.model_name == get_settings().ide_model_b
    assert order[0] == get_settings().ide_model_b  # B's primary is ide_model_b
    assert sorted(order) == sorted(get_settings().ide_model_pool)  # the rest of the pool is in the chain
