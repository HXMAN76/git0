from collections import Counter

from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.api.app import app
from git0.config import get_settings

T = "/api/ci_graph"
MONDAY = {
    "branch": "planner",
    "agent_id": "planner",
    "msg": "move launch to monday",
    "facts": [{"id": "planner-launch-deadline", "s": "launch", "p": "deadline", "o": "monday"}],
}


def _labels(view: dict) -> Counter:
    return Counter(n["label"] for n in view["nodes"])


def _types(view: dict) -> Counter:
    return Counter(link["type"] for link in view["links"])


def test_graph_view_shows_visible_memory_only():
    try:
        with TestClient(app) as client:
            assert client.post(f"{T}/seed").status_code == 200
            assert client.post(f"{T}/commits", json=MONDAY).status_code == 200

            # main: 37 facts from one kickoff commit by the planner, with its episode.
            main = client.get(f"{T}/graph").json()
            assert _labels(main) == {"Fact": 37, "Commit": 1, "Agent": 1, "Episode": 1}
            assert _types(main) == {"ADDED_IN": 37, "AUTHORED": 1, "FROM_EPISODE": 1}
            assert main["truncated"] is False

            # scheduler: +3 facts in a second commit, each DERIVED_FROM the launch deadline.
            sched = client.get(f"{T}/graph", params={"branch": "scheduler"}).json()
            assert _labels(sched) == {"Fact": 40, "Commit": 2, "Agent": 2, "Episode": 2}
            assert _types(sched) == {"ADDED_IN": 40, "AUTHORED": 2, "FROM_EPISODE": 2, "DERIVED_FROM": 3}
            assert {link["target"] for link in sched["links"] if link["type"] == "DERIVED_FROM"} == {
                "seed-launch-deadline"
            }

            # planner replaced the deadline: the old value is hidden there, still visible on main.
            planner = client.get(f"{T}/graph", params={"branch": "planner"}).json()
            planner_ids = {n["id"] for n in planner["nodes"]}
            assert "planner-launch-deadline" in planner_ids
            assert "seed-launch-deadline" not in planner_ids
            assert "seed-launch-deadline" in {n["id"] for n in main["nodes"]}
            assert len([n for n in planner["nodes"] if n["label"] == "Fact"]) == 37

            # Every link points at a node in the view (no dangling DERIVED_FROM past the cap).
            for view in (main, sched, planner):
                ids = {n["id"] for n in view["nodes"]}
                assert all(link["source"] in ids and link["target"] in ids for link in view["links"])

            capped = client.get(f"{T}/graph", params={"branch": "scheduler", "limit": 5}).json()
            assert _labels(capped)["Fact"] == 5 and capped["truncated"] is True

            no_eps = client.get(f"{T}/graph", params={"episodes": "false"}).json()
            assert "Episode" not in _labels(no_eps) and "FROM_EPISODE" not in _types(no_eps)

            assert client.get(f"{T}/graph", params={"branch": "nope"}).status_code == 404
            assert client.get(f"{T}/graph", params={"limit": 0}).status_code == 422
            assert client.get("/api/ci_graph_missing/graph").status_code == 404
    finally:
        FalkorDB.from_url(get_settings().falkordb_url).select_graph("team_ci_graph").delete()
