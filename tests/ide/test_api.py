"""HTTP surface of /api/ide that needs no DB: presets, unknown-session errors, and the answer endpoint."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from git0.ide.api import PRESETS, router


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_presets_cover_both_agents_and_the_three_scenarios() -> None:
    with client() as c:
        body = c.get("/api/ide/presets").json()
    assert [p["id"] for p in body] == ["A-regional-tax", "B-free-shipping", "B-gift-cards"]
    assert body == PRESETS


def test_unknown_session_is_404_session_expired() -> None:
    with client() as c:
        for url in ("/api/ide/sessions/nope/graph", "/api/ide/sessions/nope/files?agent=A"):
            r = c.get(url)
            assert r.status_code == 404
            assert r.json() == {"detail": "session expired"}
        r = c.post("/api/ide/sessions/nope/end")
        assert r.status_code == 404


def test_answer_and_message_validate_input_before_any_session_work() -> None:
    with client() as c:
        r = c.post("/api/ide/sessions/nope/questions/q1/answer", json={"choice": "adopt"})
        assert r.status_code == 404
        r = c.post("/api/ide/sessions/nope/agents/A/messages", json={"text": ""})
        assert r.status_code == 422  # empty text is rejected by the model, before the session lookup
