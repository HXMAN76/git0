from falkordb import FalkorDB
from fastapi.testclient import TestClient

from git0.api.app import app
from git0.config import get_settings

MONDAY = {
    "branch": "planner",
    "agent_id": "planner",
    "msg": "move launch to monday",
    "facts": [{"id": "planner-launch-deadline", "s": "launch", "p": "deadline", "o": "monday"}],
}


def _drop(graph: str) -> None:
    FalkorDB.from_url(get_settings().falkordb_url).select_graph(graph).delete()


def test_merge_preview_resolve_revert_and_procedures():
    t = "/api/ci_merge"
    try:
        with TestClient(app) as client:
            assert client.post(f"{t}/seed").status_code == 200

            # Scheduler -> main: its 3 tasks derive from the base deadline, which main never changed.
            plan = client.post(f"{t}/merge/preview", json={"source": "scheduler", "target": "main"}).json()
            assert plan["conflicts"] == []
            done = client.post(
                f"{t}/merge/resolve", json={"source": "scheduler", "target": "main", "choices": {}}
            )
            assert done.status_code == 200 and done.json()["invalidated"] == []

            # Planner moves the deadline to Monday: the 3 scheduler tasks now sit on a stale value.
            assert client.post(f"{t}/commits", json=MONDAY).status_code == 200
            plan = client.post(f"{t}/merge/preview", json={"source": "planner", "target": "main"}).json()
            assert len(plan["conflicts"]) == 1
            conflict = plan["conflicts"][0]
            assert conflict["reason"] == "dependency"
            assert len(conflict["dependents_ours"]) == 3

            # A choice that is not one of the conflict's fact ids is a client error.
            bad = client.post(
                f"{t}/merge/resolve",
                json={"source": "planner", "target": "main", "choices": {conflict["key"]: "nope"}},
            )
            assert bad.status_code == 400
            missing = client.post(
                f"{t}/merge/resolve", json={"source": "planner", "target": "main", "choices": {}}
            )
            assert missing.status_code == 400

            applied = client.post(
                f"{t}/merge/resolve",
                json={
                    "source": "planner",
                    "target": "main",
                    "choices": {conflict["key"]: conflict["theirs"]["id"]},
                },
            ).json()
            assert len(applied["invalidated"]) == 3
            assert client.get(f"{t}/scorecard").json()["conflicts_resolved"] == 1

            # Revert the planner's Monday commit on the planner branch.
            log = client.get(f"{t}/branches/planner/log").json()
            monday = next(c for c in log if c["msg"] == "move launch to monday")
            reverted = client.post(f"{t}/revert", json={"branch": "planner", "commit_id": monday["id"]})
            assert reverted.status_code == 200 and reverted.json()["reverted"] == ["planner-launch-deadline"]
            nothing = client.post(f"{t}/revert", json={"branch": "planner", "commit_id": "no-such-commit"})
            assert nothing.status_code == 400

            procs = client.get(f"{t}/branches/main/procedures")
            assert procs.status_code == 200 and isinstance(procs.json(), list)
    finally:
        _drop("team_ci_merge")


def test_merge_preview_unknown_branch_is_400():
    try:
        with TestClient(app) as client:
            client.post("/api/ci_merge_bad/init")
            r = client.post("/api/ci_merge_bad/merge/preview", json={"source": "ghost", "target": "main"})
    finally:
        _drop("team_ci_merge_bad")
    assert r.status_code == 400


def test_uninitialised_tenant_is_404_not_500():
    with TestClient(app) as client:
        r = client.get("/api/ci_never_made/scorecard")
    assert r.status_code == 404
    assert "tenant not initialised" in r.json()["detail"]
