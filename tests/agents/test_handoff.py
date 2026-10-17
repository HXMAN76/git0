"""Handoff on a real graph: successor naming, inherited facts, the handoff commit and the scorecard."""

import pytest

from git0.agents.handoff import handoff
from git0.core.models import CommitRequest, NewFact
from git0.core.repo import new_id


async def add_planner_fact(repo, s, p, o):
    await repo.commit(
        CommitRequest(
            branch="planner",
            agent_id="planner",
            msg=f"planner: {s} {p}",
            facts=[NewFact(id=new_id(), s=s, p=p, o=o)],
        )
    )


async def test_handoff_inherits_facts_and_commits_as_successor(repo):
    await repo.create_branch("planner")
    await add_planner_fact(repo, "launch", "deadline", "friday")
    await add_planner_fact(repo, "launch", "owner", "asha")

    res = await handoff(repo, "planner", session_id="sess-h")

    assert res.successor == "planner-2" and res.branch == "planner"
    assert [f.key for f in res.inherited] == ["launch|deadline", "launch|owner"]
    assert res.commits == 2  # the two planner commits; the root init is not counted
    assert res.summary == (
        "planner-2 took over planner from planner: inherited 2 facts from 2 commits.\n"
        "launch|deadline = friday\n"
        "launch|owner = asha"
    )

    (head, *_) = await repo.log("planner")
    assert head.id == res.commit_id
    assert head.kind == "handoff" and head.agent_id == "planner-2"
    assert head.msg == "handoff: planner -> planner-2"

    episode = await repo.graph.ro_query(
        "MATCH (:Commit {id: $c})-[:FROM_EPISODE]->(e:Episode) RETURN e.text, e.session_id",
        {"c": res.commit_id},
    )
    assert episode.result_set == [[res.summary, "sess-h"]]

    assert (await repo.scorecard()).handoffs == 1


async def test_second_handoff_increments_suffix(repo):
    await repo.create_branch("planner")
    await add_planner_fact(repo, "launch", "deadline", "friday")

    first = await handoff(repo, "planner", session_id="s")
    second = await handoff(repo, "planner", session_id="s")

    assert first.successor == "planner-2"
    assert second.successor == "planner-3"
    assert second.commits == 2  # one planner commit + the first handoff commit
    assert (await repo.scorecard()).handoffs == 2


async def test_summary_lists_at_most_ten_facts_sorted_by_key(repo):
    await repo.create_branch("planner")
    await repo.commit(
        CommitRequest(
            branch="planner",
            agent_id="planner",
            msg="many facts",
            facts=[NewFact(id=f"f{i:02d}", s=f"e{i:02d}", p="owner", o="x") for i in range(12, 0, -1)],
        )
    )

    res = await handoff(repo, "planner", session_id="s")

    lines = res.summary.splitlines()
    assert len(res.inherited) == 12
    assert lines[1:] == [f"e{i:02d}|owner = x" for i in range(1, 11)]


async def test_unknown_agent_is_key_error(repo):
    with pytest.raises(KeyError):
        await handoff(repo, "ghost", session_id="s")


async def test_missing_branch_is_key_error(repo):
    # The planner branch was never created: there is nothing to inherit.
    with pytest.raises(KeyError):
        await handoff(repo, "planner", session_id="s")
