"""Session event bus, SSE replay, the ask/answer future, and the sweeper's TTL logic (fake clock, no DB)."""

import asyncio
from pathlib import Path

import pytest

from git0.config import get_settings
from git0.ide import session as session_mod
from git0.ide.session import Session, SessionManager


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_session(root: Path, sid: str, clock: FakeClock) -> Session:
    workspaces = {"A": root / sid / "a", "B": root / sid / "b"}
    for ws in workspaces.values():
        ws.mkdir(parents=True)
    return Session(sid=sid, root=root / sid, workspaces=workspaces, relay=None, clock=clock)  # type: ignore[arg-type]


async def next_event(gen):
    return await asyncio.wait_for(gen.__anext__(), 2)


async def test_replay_then_live_events(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s1", FakeClock())
    s.emit("one", n=1)
    s.emit("two", n=2)
    gen = s.events()
    first = await next_event(gen)
    second = await next_event(gen)
    assert (first["type"], second["type"]) == ("one", "two")
    assert "ts" in first  # every event carries a ms timestamp
    s.emit("three", n=3)
    assert (await next_event(gen))["type"] == "three"
    await gen.aclose()


async def test_fanout_to_every_subscriber(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s2", FakeClock())
    g1, g2 = s.events(), s.events()
    s.emit("ping_me", k=7)
    assert (await next_event(g1))["k"] == 7
    assert (await next_event(g2))["k"] == 7
    await g1.aclose()
    await g2.aclose()


async def test_ring_buffer_keeps_last_events_only(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s3", FakeClock())
    for i in range(session_mod.EVENT_BUFFER + 25):
        s.emit("tick", i=i)
    gen = s.events()
    first = await next_event(gen)
    assert first["i"] == 25  # the oldest 25 fell out of the replay buffer
    await gen.aclose()


async def test_disconnect_marks_no_subscriber_since(tmp_path: Path) -> None:
    clock = FakeClock(10.0)
    s = make_session(tmp_path, "s4", clock)
    assert s.no_subscriber_since == 10.0
    gen = s.events()
    s.emit("x")
    await next_event(gen)
    assert s.no_subscriber_since is None
    clock.t = 42.0
    await gen.aclose()
    assert s.no_subscriber_since == 42.0


async def test_ask_returns_the_answer(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s5", FakeClock())
    options = [{"id": "adopt", "label": "a"}, {"id": "override", "label": "o"}]
    task = asyncio.create_task(s.ask("A", "clash?", options))
    await asyncio.sleep(0)
    qid = [e for e in s._buffer if e["type"] == "ask_user"][-1]["question_id"]
    s.answer(qid, "override")
    assert await task == "override"
    resolved = [e for e in s._buffer if e["type"] == "ask_resolved"][-1]
    assert resolved["choice"] == "override"


async def test_answer_rejects_unknown_question_and_bad_choice(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s6", FakeClock())
    task = asyncio.create_task(s.ask("A", "clash?", [{"id": "pause", "label": "p"}]))
    await asyncio.sleep(0)
    qid = [e for e in s._buffer if e["type"] == "ask_user"][-1]["question_id"]
    with pytest.raises(ValueError):
        s.answer(qid, "made-up")
    with pytest.raises(KeyError):
        s.answer("nope", "pause")
    s.answer(qid, "pause")
    assert await task == "pause"


async def test_unanswered_question_times_out_as_pause(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(session_mod, "QUESTION_TIMEOUT_S", 0.05)
    s = make_session(tmp_path, "s7", FakeClock())
    assert await s.ask("B", "clash?", [{"id": "adopt", "label": "a"}]) == "pause"


async def test_close_resolves_pending_questions_as_pause(tmp_path: Path) -> None:
    s = make_session(tmp_path, "s8", FakeClock())
    task = asyncio.create_task(s.ask("A", "clash?", [{"id": "adopt", "label": "a"}]))
    await asyncio.sleep(0)
    await s.close("test")
    assert await task == "pause"
    assert s.ended


async def test_sweeper_ttl_and_disconnect_grace(tmp_path: Path, monkeypatch) -> None:
    ended: list[str] = []

    async def fake_delete_graph(sid: str) -> None:
        ended.append(sid)

    monkeypatch.setattr(session_mod, "_delete_graph", fake_delete_graph)
    settings = get_settings()
    ttl, grace = settings.ide_session_ttl_s, settings.ide_disconnect_grace_s

    clock = FakeClock(0.0)
    manager = SessionManager(clock=clock)
    watched = make_session(tmp_path, "watch", clock)  # an SSE tab stays attached
    orphan = make_session(tmp_path, "orphan", clock)  # nobody ever connected
    manager._sessions = {"watch": watched, "orphan": orphan}

    gen = watched.events()
    watched.emit("hello")
    await next_event(gen)  # subscribed: the disconnect clock stops

    clock.t = grace + 1
    assert manager.expired() == {"orphan": "disconnected"}

    # Past the TTL with no API calls: idle wins over disconnected, and the attached tab is idle too.
    clock.t = ttl + 1
    assert manager.expired() == {"watch": "idle", "orphan": "idle"}

    swept = await manager.sweep()
    assert sorted(swept) == ["orphan", "watch"]
    assert sorted(ended) == ["orphan", "watch"]
    assert manager.live() == []
    await gen.aclose()


async def test_get_touches_last_seen_and_unknown_session_raises(tmp_path: Path) -> None:
    clock = FakeClock(0.0)
    manager = SessionManager(clock=clock)
    s = make_session(tmp_path, "touchme", clock)
    manager._sessions = {"touchme": s}
    clock.t = 500.0
    manager.get("touchme")
    assert s.last_seen == 500.0
    with pytest.raises(session_mod.SessionNotFound):
        manager.get("missing")
