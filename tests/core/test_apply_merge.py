import pytest

from git0.core.merge import DELETE, apply_merge, plan_merge
from git0.core.models import Derivation
from git0.core.repo import CommitConflictError
from tests.core.test_merge_commit import commit, fact

KEY = "launch|deadline"


async def precedents(repo):
    rows = (
        await repo.graph.ro_query("MATCH (p:Precedent) RETURN p.key_pattern, p.choice, p.count")
    ).result_set
    return [tuple(r) for r in rows]


async def judge_story(repo):
    """main: deadline=fri. planner: mon. scheduler: moves it to tue and books a venue derived from that.

    scheduler merges into main first (auto), so planner vs main is a real conflict whose ours side has a
    dependent (the venue booking).
    """
    await commit(repo, "main", "base", facts=[fact("launch", "deadline", "fri")])
    await repo.create_branch("planner")
    await repo.create_branch("scheduler")
    mon = fact("launch", "deadline", "mon")
    await commit(repo, "planner", "planner picks mon", facts=[mon])
    tue, venue = fact("launch", "deadline", "tue"), fact("venue", "status", "booked_tue")
    await commit(repo, "scheduler", "pick tue", facts=[tue])
    await commit(
        repo, "scheduler", "book", facts=[venue], derived=[Derivation(child=venue.id, parent=tue.id)]
    )
    auto = await plan_merge(repo, "scheduler", "main")
    assert auto.conflicts == []
    await apply_merge(repo, auto, {})
    return mon, tue, venue


async def test_judge_story_choose_planner_cascades_and_learns(repo):
    mon, tue, venue = await judge_story(repo)
    plan = await plan_merge(repo, "planner", "main")
    assert [c.key for c in plan.conflicts] == [KEY]
    assert [f.id for f in plan.conflicts[0].dependents_ours] == [venue.id]

    done = await apply_merge(repo, plan, {KEY: mon.id})

    facts = {f.key: f.o for f in await repo.checkout("main")}
    assert facts == {KEY: "mon"}
    assert set(done.removed) == {tue.id, venue.id}
    assert [f.id for f in done.invalidated] == [venue.id]
    assert done.merge_commit == await repo.head("main")
    assert await precedents(repo) == [("deadline", "source", 1)]

    # a similar conflict later shows the learned precedent
    await repo.create_branch("late", from_branch="main")
    await commit(repo, "late", "x", facts=[fact("launch", "deadline", "wed")])
    await commit(repo, "main", "y", facts=[fact("launch", "deadline", "thu")])
    c = (await plan_merge(repo, "late", "main")).conflicts[0]
    assert (c.precedent_choice, c.precedent_count) == ("source", 1)


async def test_choose_ours_keeps_dependents_and_removes_source_fact(repo):
    mon, tue, venue = await judge_story(repo)
    plan = await plan_merge(repo, "planner", "main")
    done = await apply_merge(repo, plan, {KEY: tue.id})
    assert {f.key: f.o for f in await repo.checkout("main")} == {KEY: "tue", "venue|status": "booked_tue"}
    assert done.removed == [mon.id] and done.invalidated == []
    assert await precedents(repo) == [("deadline", "target", 1)]


async def test_delete_removes_both_sides_and_dependents(repo):
    mon, tue, venue = await judge_story(repo)
    plan = await plan_merge(repo, "planner", "main")
    done = await apply_merge(repo, plan, {KEY: DELETE})
    assert await repo.checkout("main") == []
    assert set(done.removed) == {mon.id, tue.id, venue.id}
    assert await precedents(repo) == [("deadline", "delete", 1)]


async def test_missing_or_invalid_choice_raises_and_commits_nothing(repo):
    mon, _, _ = await judge_story(repo)
    plan = await plan_merge(repo, "planner", "main")
    head = await repo.head("main")
    with pytest.raises(ValueError, match="no choice"):
        await apply_merge(repo, plan, {})
    with pytest.raises(ValueError, match="not one of"):
        await apply_merge(repo, plan, {KEY: "bogus"})
    with pytest.raises(ValueError, match="no conflict"):
        await apply_merge(repo, plan, {KEY: mon.id, "x|owner": mon.id})
    assert await repo.head("main") == head


async def test_stale_plan_raises(repo):
    mon, _, _ = await judge_story(repo)
    plan = await plan_merge(repo, "planner", "main")
    await commit(repo, "main", "moved on", facts=[fact("other", "owner", "z")])
    with pytest.raises(CommitConflictError, match="re-plan"):
        await apply_merge(repo, plan, {KEY: mon.id})


async def test_winner_survives_when_it_is_also_a_loser_dependent(repo):
    """Winner of conflict B is derived from the loser of conflict A: the winner must not be removed."""
    await commit(repo, "main", "base", facts=[fact("a", "deadline", "1"), fact("b", "owner", "1")])
    await repo.create_branch("feat")
    a_ours, a_theirs = fact("a", "deadline", "2"), fact("a", "deadline", "3")
    await commit(repo, "main", "a-ours", facts=[a_ours])
    await commit(repo, "feat", "a-theirs", facts=[a_theirs])
    b_ours, b_theirs = fact("b", "owner", "2"), fact("b", "owner", "3")
    await commit(
        repo, "main", "b-ours", facts=[b_ours], derived=[Derivation(child=b_ours.id, parent=a_ours.id)]
    )
    await commit(repo, "feat", "b-theirs", facts=[b_theirs])
    plan = await plan_merge(repo, "feat", "main")
    assert len(plan.conflicts) == 2
    done = await apply_merge(repo, plan, {"a|deadline": a_theirs.id, "b|owner": b_ours.id})
    assert {f.key: f.id for f in await repo.checkout("main")} == {
        "a|deadline": a_theirs.id,
        "b|owner": b_ours.id,
    }
    assert b_ours.id not in done.removed and done.invalidated == []
