import time
import uuid

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


def test_seed_touches_last_seen():
    graph = FalkorDB.from_url(get_settings().falkordb_url).select_graph("team_ci_touch")
    query = "MATCH (r:Room) RETURN r.last_seen"
    try:
        with TestClient(app) as client:
            client.post("/api/ci_touch/seed")
            first = graph.ro_query(query).result_set[0][0]
            time.sleep(0.01)
            client.post("/api/ci_touch/seed")  # a repeat page load
            second = graph.ro_query(query).result_set[0][0]
    finally:
        graph.delete()

    assert abs(first - time.time() * 1000) < 60_000  # FalkorDB clock vs ours: same host, so close
    assert second > first


def test_seeding_a_new_room_at_the_cap_evicts_the_least_recently_seen(monkeypatch):
    settings = get_settings()
    prefix = f"capt_{uuid.uuid4().hex[:8]}_"  # own prefix: the cap sweep must not see real team_* rooms
    monkeypatch.setattr(settings, "tenant_graph_prefix", prefix)
    monkeypatch.setattr(settings, "max_rooms", 2)
    db = FalkorDB.from_url(settings.falkordb_url)
    try:
        with TestClient(app) as client:
            for room in ["a", "b", "a", "c"]:  # "a" seen again after "b", so "b" is the oldest
                assert client.post(f"/api/{room}/seed").status_code == 200
                time.sleep(0.01)
        rooms = {g.removeprefix(prefix) for g in db.list_graphs() if g.startswith(prefix)}
    finally:
        for g in db.list_graphs():
            if g.startswith(prefix):
                db.select_graph(g).delete()

    assert rooms == {"a", "c"}
