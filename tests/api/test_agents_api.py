import json

from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.agents.arbiter import ConflictExplanation, Explanations
from git0.agents.extract import ExtractedFact, ExtractedLink, Extraction
from git0.api.app import app, get_llm
from git0.config import get_settings
from git0.llm.client import LLMError, Usage


def parse_sse(text: str) -> dict:
    """Parse an SSE body into {event_name: data_dict} for the last occurrence of each event."""
    events: dict = {}
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name, data = "message", {}
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:].strip())
        events[name] = data
    return events

GRAPH = "team_ci_agents"


def test_kill_agent_hands_off_its_branch_on_a_seeded_tenant():
    t = "/api/ci_agents"
    try:
        with TestClient(app) as client:
            assert client.post(f"{t}/seed").status_code == 200

            r = client.post(f"{t}/agents/planner/kill")
            assert r.status_code == 200
            body = r.json()
            assert body["successor"] == "planner-2" and body["branch"] == "planner"
            assert len(body["inherited"]) > 0 and body["commits"] > 0

            log = client.get(f"{t}/branches/planner/log").json()
            assert log[0]["kind"] == "handoff" and log[0]["agent_id"] == "planner-2"
            assert client.get(f"{t}/scorecard").json()["handoffs"] == 1

            assert client.post(f"{t}/agents/ghost/kill").status_code == 404
    finally:
        FalkorDB.from_url(get_settings().falkordb_url).select_graph(GRAPH).delete()


MONDAY = {
    "branch": "planner",
    "agent_id": "planner",
    "msg": "move launch to monday",
    "facts": [{"id": "planner-launch-deadline", "s": "launch", "p": "deadline", "o": "monday"}],
}


def fake_llm(calls: list):
    """Stands in for the real client via app.dependency_overrides[get_llm]; answers by output schema."""

    async def llm(prompt, schema, *, system, tenant):
        calls.append(schema)
        usage = Usage(model="fake", prompt_tokens=5, completion_tokens=3, provider="fake")
        if schema is Explanations:
            return Explanations(
                items=[ConflictExplanation(key="launch|deadline", text="Planner and Scheduler disagree.")]
            ), usage
        return Extraction(
            reply="Re-planned.",
            facts=[ExtractedFact(s="venue", p="status", o="booked monday")],
            removed_keys=[],
            derived=[ExtractedLink(child_key="venue|status", parent_key="launch|deadline")],
            procedures=[],
            cited_keys=[],
        ), usage

    return llm


def test_explain_and_rederive_routes_with_fake_llm_and_llm_error_is_502():
    t = "/api/ci_arbiter"
    calls: list = []
    try:
        with TestClient(app) as client:
            app.dependency_overrides[get_llm] = lambda: fake_llm(calls)
            assert client.post(f"{t}/seed").status_code == 200
            body = {"source": "scheduler", "target": "main"}
            assert client.post(f"{t}/merge/resolve", json={**body, "choices": {}}).status_code == 200
            assert client.post(f"{t}/commits", json=MONDAY).status_code == 200

            # No conflicts (scheduler already merged): no LLM call.
            assert client.post(f"{t}/merge/explain", json=body).json() == []
            assert calls == []

            ex = client.post(f"{t}/merge/explain", json={"source": "planner", "target": "main"})
            assert ex.status_code == 200
            assert ex.json() == [{"key": "launch|deadline", "text": "Planner and Scheduler disagree."}]
            assert (
                client.post(f"{t}/merge/explain", json={"source": "ghost", "target": "main"}).status_code
                == 400
            )

            plan = client.post(f"{t}/merge/preview", json={"source": "planner", "target": "main"}).json()
            choice = {plan["conflicts"][0]["key"]: plan["conflicts"][0]["theirs"]["id"]}
            applied = client.post(
                f"{t}/merge/resolve", json={"source": "planner", "target": "main", "choices": choice}
            ).json()
            ids = [f["id"] for f in applied["invalidated"]]
            assert len(ids) == 3

            calls.clear()
            r = client.post(f"{t}/arbiter/rederive", json={"target": "main", "fact_ids": ids})
            assert r.status_code == 200
            out = r.json()
            assert out["owners"] == ["scheduler"] and out["tokens"] == 8 and out["skipped"] == []
            assert calls == [Extraction]
            main = {f["key"]: f["o"] for f in client.get(f"{t}/branches/main/checkout").json()}
            assert main["venue|status"] == "booked monday"
            bad = client.post(f"{t}/arbiter/rederive", json={"target": "ghost", "fact_ids": ids})
            assert bad.status_code == 400

            async def failing(prompt, schema, *, system, tenant):
                raise LLMError("all LLM providers failed: boom")

            app.dependency_overrides[get_llm] = lambda: failing
            down = client.post(f"{t}/arbiter/rederive", json={"target": "main", "fact_ids": ids})
            assert down.status_code == 502 and down.json() == {"detail": "all LLM providers failed: boom"}
    finally:
        app.dependency_overrides.pop(get_llm, None)
        FalkorDB.from_url(get_settings().falkordb_url).select_graph("team_ci_arbiter").delete()


def test_agent_message_commits_one_turn_on_the_agents_branch_and_llm_error_is_502():
    t = "/api/ci_chat"
    calls: list = []
    try:
        with TestClient(app) as client:
            app.dependency_overrides[get_llm] = lambda: fake_llm(calls)
            assert client.post(f"{t}/seed").status_code == 200
            before = len(client.get(f"{t}/branches/scheduler/log").json())

            r = client.post(
                f"{t}/agents/scheduler/messages", json={"text": "book the venue", "session_id": "s1"}
            )
            assert r.status_code == 200
            events = parse_sse(r.text)
            token, commit = events["token"], events["commit"]
            assert token["agent_id"] == "scheduler" and commit["branch"] == "scheduler"
            assert token["text"] == "Re-planned." and commit["usage"]["prompt_tokens"] == 5
            assert calls == [Extraction]

            log = client.get(f"{t}/branches/scheduler/log").json()
            assert len(log) == before + 1 and log[0]["id"] == commit["commit_id"]
            facts = {f["key"]: f["o"] for f in client.get(f"{t}/branches/scheduler/checkout").json()}
            assert facts["venue|status"] == "booked monday"

            assert client.post(f"{t}/agents/ghost/messages", json={"text": "hi"}).status_code == 404
            assert client.post(f"{t}/agents/planner/messages", json={"text": ""}).status_code == 422

            async def failing(prompt, schema, *, system, tenant):
                raise LLMError("all LLM providers failed: boom")

            app.dependency_overrides[get_llm] = lambda: failing
            down = client.post(f"{t}/agents/planner/messages", json={"text": "move launch to monday"})
            # LLM errors are emitted as SSE error events (200 status, streaming already started).
            assert down.status_code == 200
            assert parse_sse(down.text)["error"]["message"] == "all LLM providers failed: boom"
            # A failed turn writes nothing.
            assert client.get(f"{t}/branches/planner/log").json()[0]["kind"] == "seed"
    finally:
        app.dependency_overrides.pop(get_llm, None)
        FalkorDB.from_url(get_settings().falkordb_url).select_graph("team_ci_chat").delete()


def test_agent_message_keeps_the_room_alive():
    """A visitor who only chats (no page reload) must not have their room swept as idle."""
    graph = FalkorDB.from_url(get_settings().falkordb_url).select_graph("team_ci_chat_touch")
    stamp = "MATCH (r:Room) RETURN r.last_seen"
    calls: list = []
    try:
        with TestClient(app) as client:
            app.dependency_overrides[get_llm] = lambda: fake_llm(calls)
            assert client.post("/api/ci_chat_touch/seed").status_code == 200
            graph.query("MATCH (r:Room) SET r.last_seen = 0")  # pretend the room went quiet long ago
            r = client.post("/api/ci_chat_touch/agents/planner/messages", json={"text": "hello"})
            assert r.status_code == 200
            assert graph.ro_query(stamp).result_set[0][0] > 0
    finally:
        app.dependency_overrides.pop(get_llm, None)
        graph.delete()
