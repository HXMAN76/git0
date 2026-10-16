from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.api.app import app
from git0.config import get_settings

GRAPH = "team_ci_scorecard"


def test_scorecard_endpoint_counts_tenants():
    try:
        with TestClient(app) as client:
            client.post("/api/ci_scorecard/init")
            card = client.get("/api/ci_scorecard/scorecard").json()
    finally:
        FalkorDB.from_url(get_settings().falkordb_url).select_graph(GRAPH).delete()

    assert card["commits"] == 0 and card["facts_on_main"] == 0
    assert card["tenants"] >= 1  # at least this test's own graph
    assert card["query_ms"] > 0
