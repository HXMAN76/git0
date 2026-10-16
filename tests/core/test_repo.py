import asyncio

import pytest

from git0.core.models import CommitRequest, Derivation, Episode, NewFact, NewProcedure
from git0.core.queries import Q
from git0.core.repo import new_id


def fact(s, p, o, fid=None):
    return NewFact(id=fid or new_id(), s=s, p=p, o=o)


async def test_init_is_idempotent(repo):
    head = await repo.head("main")
    await repo.init()
    assert await repo.head("main") == head


async def test_commit_then_checkout(repo):
    await repo.commit(
        CommitRequest(
            branch="main", agent_id="planner", msg="plan", facts=[fact("launch", "deadline", "fri")]
        )
    )
    facts = await repo.checkout("main")
    assert [(f.key, f.o) for f in facts] == [("launch|deadline", "fri")]


async def test_empty_commit_is_not_reported_as_cas_failure(repo):
    commit, retries = await repo.commit(CommitRequest(branch="main", agent_id="a", msg="noop"))
    assert retries == 0 and await repo.head("main") == commit.id


async def test_stale_cas_writes_nothing(repo):
    old = await repo.head("main")
    await repo.commit(CommitRequest(branch="main", agent_id="a", msg="x"))
    late = await repo.try_commit(
        CommitRequest(branch="main", agent_id="b", msg="late", facts=[fact("a", "owner", "b")]), old
    )
    assert late is None
    assert await repo.checkout("main") == []


async def test_removal_hides_fact(repo):
    f = fact("launch", "deadline", "fri")
    await repo.commit(CommitRequest(branch="main", agent_id="a", msg="add", facts=[f]))
    await repo.commit(
        CommitRequest(
            branch="main", agent_id="a", msg="drop", removed=[f.id], facts=[fact("launch", "deadline", "mon")]
        )
    )
    assert [f.o for f in await repo.checkout("main")] == ["mon"]


async def test_branches_are_isolated_and_merge_base(repo):
    await repo.commit(
        CommitRequest(branch="main", agent_id="a", msg="base", facts=[fact("launch", "deadline", "fri")])
    )
    base = await repo.head("main")
    await repo.create_branch("scheduler")
    await repo.commit(
        CommitRequest(
            branch="scheduler", agent_id="scheduler", msg="venue", facts=[fact("venue", "status", "booked")]
        )
    )
    await repo.commit(
        CommitRequest(branch="main", agent_id="planner", msg="owner", facts=[fact("launch", "owner", "asha")])
    )
    assert {f.key for f in await repo.checkout("main")} == {"launch|deadline", "launch|owner"}
    assert {f.key for f in await repo.checkout("scheduler")} == {"launch|deadline", "venue|status"}
    assert await repo.merge_base("main", "scheduler") == base


async def test_checkout_matches_traversal_version(repo):
    for i in range(5):
        await repo.commit(
            CommitRequest(branch="main", agent_id="a", msg=str(i), facts=[fact(f"t{i}", "status", "open")])
        )
    fast = {f.id for f in await repo.checkout("main")}
    walk = {
        row[0] for row in (await repo.graph.ro_query(Q["checkout_traversal"], {"branch": "main"})).result_set
    }
    assert fast == walk and len(fast) == 5


async def test_dependents_why_and_lookup(repo):
    launch, venue = fact("launch", "deadline", "fri"), fact("venue", "status", "booked")
    ep = Episode(id=new_id(), text="Book the venue for Friday", session_id="s1")
    await repo.commit(
        CommitRequest(
            branch="main",
            agent_id="scheduler",
            msg="book",
            facts=[launch, venue],
            episodes=[ep],
            derived=[Derivation(child=venue.id, parent=launch.id)],
        )
    )
    assert [d["id"] for d in await repo.dependents(launch.id)] == [venue.id]
    why = await repo.why(venue.id)
    assert why[0]["agent_id"] == "scheduler" and why[0]["episode_text"] == ep.text
    assert await repo.lookup("main", "caterer|contact") == []


@pytest.mark.parametrize("writers", [20])
async def test_concurrent_writers_lose_nothing(repo, writers):
    """M6: N agents commit to the same branch at once; every commit lands exactly once."""
    reqs = [
        CommitRequest(
            branch="main", agent_id=f"agent{i}", msg=f"w{i}", facts=[fact(f"task{i}", "status", "done")]
        )
        for i in range(writers)
    ]
    results = await asyncio.gather(*(repo.commit(r, retries=writers) for r in reqs))
    log = await repo.log("main", limit=writers + 5)
    assert len(log) == writers + 1  # + root
    assert len({c.seq for c in log}) == writers + 1  # linear history, no forks
    assert len(await repo.checkout("main")) == writers
    assert sum(r for _, r in results) >= 0


async def test_sessions_group_episodes_across_commits(repo):
    """Persistent conversation history: one Session, many turns, each linked to the commit it produced."""
    for i, text in enumerate(["launch is Friday", "book the venue"]):
        await repo.commit(
            CommitRequest(
                branch="main",
                agent_id="planner",
                msg=f"turn {i}",
                episodes=[Episode(id=new_id(), text=text, session_id="s1")],
            )
        )
    res = await repo.graph.ro_query(
        "MATCH (s:Session {id: 's1'})-[:HAS_TURN]->(e:Episode)<-[:FROM_EPISODE]-(c:Commit) "
        "RETURN count(DISTINCT s), count(e), count(DISTINCT c)"
    )
    assert res.result_set == [[1, 2, 2]]


async def test_procedures_are_versioned_like_facts(repo):
    proc = NewProcedure(id=new_id(), trigger="launch date moves", steps='["notify qa", "add 24h freeze"]')
    await repo.create_branch("planner")
    await repo.commit(CommitRequest(branch="planner", agent_id="planner", msg="learned", procedures=[proc]))
    assert await repo.procedures("main") == []
    [got] = await repo.procedures("planner")
    assert got.trigger == "launch date moves" and got.agent_id == "planner"
    await repo.commit(
        CommitRequest(branch="planner", agent_id="planner", msg="drop", removed_procedures=[proc.id])
    )
    assert await repo.procedures("planner") == []


async def test_one_visible_value_per_key(repo):
    """Invariant: a branch view holds at most one fact per (subject, predicate) key.
    commit_cas retires the visible fact with the same key automatically."""
    await repo.commit(
        CommitRequest(branch="main", agent_id="a", msg="fri", facts=[fact("launch", "deadline", "fri")])
    )
    await repo.commit(
        CommitRequest(branch="main", agent_id="a", msg="mon", facts=[fact("launch", "deadline", "mon")])
    )
    assert [f.o for f in await repo.checkout("main")] == ["mon"]


async def test_ensure_schema_is_idempotent(repo):
    """Regression: list_indices groups properties per label, so Fact(id, key) must not be re-created."""
    from git0.core.db import ensure_schema

    await ensure_schema(repo.graph)
    await ensure_schema(repo.graph)


async def test_explicit_removal_plus_same_key_add_makes_one_removed_edge(repo):
    """The explicit `removed` entry and the automatic same-key removal must MERGE into one edge."""
    old = fact("launch", "deadline", "fri")
    await repo.commit(CommitRequest(branch="main", agent_id="a", msg="fri", facts=[old]))
    await repo.commit(
        CommitRequest(
            branch="main",
            agent_id="a",
            msg="mon",
            removed=[old.id],
            facts=[fact("launch", "deadline", "mon")],
        )
    )
    res = await repo.graph.ro_query(
        "MATCH (:Fact {id: $id})-[r:REMOVED_IN]->(:Commit) RETURN count(r)", {"id": old.id}
    )
    assert res.result_set[0][0] == 1
    assert [f.o for f in await repo.checkout("main")] == ["mon"]


def test_duplicate_key_in_one_commit_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        CommitRequest(
            branch="main",
            agent_id="a",
            msg="dup",
            facts=[fact("launch", "deadline", "fri"), fact("launch", "deadline", "mon")],
        )


async def test_log_reports_commit_kind(repo):
    await repo.commit(CommitRequest(branch="main", agent_id="a", msg="x", facts=[fact("a", "owner", "b")]))
    assert (await repo.log("main"))[0].kind == "commit"


async def test_same_key_on_branch_does_not_hide_main_value(repo):
    await repo.commit(
        CommitRequest(branch="main", agent_id="a", msg="fri", facts=[fact("launch", "deadline", "fri")])
    )
    await repo.create_branch("b")
    await repo.commit(
        CommitRequest(branch="b", agent_id="a", msg="mon", facts=[fact("launch", "deadline", "mon")])
    )
    assert [f.o for f in await repo.checkout("main")] == ["fri"]
    assert [f.o for f in await repo.checkout("b")] == ["mon"]
