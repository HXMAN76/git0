from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.api.app import app
from git0.config import get_settings

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
