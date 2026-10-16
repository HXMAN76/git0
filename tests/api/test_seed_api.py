from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.api.app import app
from git0.config import get_settings

GRAPH = "team_ci_seed"


def test_seed_endpoint_creates_room_once():
    try:
        with TestClient(app) as client:
            first = client.post("/api/ci_seed/seed").json()
            second = client.post("/api/ci_seed/seed").json()
            scheduler = client.get("/api/ci_seed/branches/scheduler/checkout").json()
    finally:
        FalkorDB.from_url(get_settings().falkordb_url).select_graph(GRAPH).delete()

    assert first["created"] is True
    assert second["created"] is False
    assert first["facts_on_main"] == 37 and second["facts_on_main"] == 37
    assert first["facts_on_scheduler"] == 40 and second["facts_on_scheduler"] == 40
    assert len(scheduler) == 40
