"""The hero case: a one-sided change that leaves a fact derived from the OLD value stale."""

from git0.core.merge import apply_merge, plan_merge
from git0.core.models import Derivation
from tests.core.test_apply_merge import precedents
from tests.core.test_merge_commit import commit, fact

KEY = "launch|deadline"


async def story(repo, p="deadline", base_o="fri", new_o="mon", derive_first=False):
    """main: launch|<p>=base_o. scheduler books a venue derived from it; planner moves the value.

    The scheduler merges into main first (it never touched the value, so no conflict). Then planner vs main is
    value-wise a clean one-sided change, but main now holds a dependent of the value planner replaced.
    """
    base = fact("launch", p, base_o)
    venue = fact("venue", "owner" if p == "status" else "status", "booked")
    await commit(repo, "main", "base", facts=[base])
    if derive_first:  # the dependent already exists at the merge base
        await commit(
            repo, "main", "venue", facts=[venue], derived=[Derivation(child=venue.id, parent=base.id)]
        )
    await repo.create_branch("planner")
    await repo.create_branch("scheduler")
    if not derive_first:
        await commit(
            repo, "scheduler", "book", facts=[venue], derived=[Derivation(child=venue.id, parent=base.id)]
        )
        auto = await plan_merge(repo, "scheduler", "main")
        assert auto.conflicts == []
        await apply_merge(repo, auto, {})
    moved = fact("launch", p, new_o)
    await commit(repo, "planner", "move", facts=[moved])
    return base, moved, venue


async def test_stale_dependent_makes_a_dependency_conflict(repo):
    base, mon, venue = await story(repo)
    plan = await plan_merge(repo, "planner", "main")
    assert len(plan.conflicts) == 1
    c = plan.conflicts[0]
    assert c.reason == "dependency" and c.key == KEY
    assert (c.base.id, c.ours.id, c.ours.o, c.theirs.id, c.theirs.o) == (
        base.id,
        base.id,
        "fri",
        mon.id,
        "mon",
    )
    assert [f.id for f in c.dependents_ours] == [venue.id] and c.dependents_theirs == []
    assert KEY not in {f.key for f in plan.auto_merged}  # the conflicted key is not silently merged


async def test_choose_theirs_hides_stale_dependent_and_learns(repo):
    base, mon, venue = await story(repo)
    plan = await plan_merge(repo, "planner", "main")
    done = await apply_merge(repo, plan, {KEY: mon.id})

    assert {f.key: f.o for f in await repo.checkout("main")} == {KEY: "mon"}
    assert [f.id for f in done.invalidated] == [venue.id] and venue.id in done.removed
    assert done.restored == []
    assert await precedents(repo) == [("deadline", "source", 1)]

    rows = (
        await repo.graph.ro_query(
            "MATCH (c:Conflict)-[:RESOLVED_IN]->(m:Commit {id: $m}) "
            "OPTIONAL MATCH (c)-[:SIDE_A]->(a) OPTIONAL MATCH (c)-[:SIDE_B]->(b) "
            "OPTIONAL MATCH (c)-[:BASE]->(x) "
            "RETURN c.side, m.kind, a.id, b.id, x.id",
            {"m": done.merge_commit},
        )
    ).result_set
    assert rows == [["source", "merge", base.id, mon.id, base.id]]


async def test_choose_ours_restores_base_value_as_a_copy(repo):
    base, mon, venue = await story(repo)
    plan = await plan_merge(repo, "planner", "main")
    done = await apply_merge(repo, plan, {KEY: base.id})

    visible = {f.key: f for f in await repo.checkout("main")}
    assert set(visible) == {KEY, "venue|status"} and visible[KEY].o == "fri"
    assert done.restored == [visible[KEY].id] and visible[KEY].id != base.id
    assert mon.id in done.removed and done.invalidated == []
    assert await precedents(repo) == [("deadline", "target", 1)]


async def test_choose_ours_when_source_holds_the_base_value(repo):
    """Mirror image: planner (target) changed the value, main (source) holds the stale dependent."""
    base, mon, venue = await story(repo)
    plan = await plan_merge(repo, "main", "planner")
    c = plan.conflicts[0]
    assert c.reason == "dependency"
    assert (c.ours.o, c.theirs.o) == ("mon", "fri")
    assert [f.id for f in c.dependents_theirs] == [venue.id] and c.dependents_ours == []
    done = await apply_merge(repo, plan, {KEY: base.id})  # keep the base-valued source side
    assert done.restored and {f.key: f.o for f in await repo.checkout("planner")}[KEY] == "fri"


async def test_latest_wins_predicate_removes_stale_dependent_without_asking(repo):
    base, moved, venue = await story(repo, p="status", base_o="active", new_o="paused")
    plan = await plan_merge(repo, "planner", "main")
    assert plan.conflicts == []
    assert venue.id in plan.removals
    assert [f.id for f in plan.auto_merged] == [moved.id]
    assert [f.id for f in plan.invalidated_auto] == [venue.id]
    done = await apply_merge(repo, plan, {})
    assert {f.key: f.o for f in await repo.checkout("main")} == {"launch|status": "paused"}
    # the Arbiter re-derives only invalidated facts, so the silent cascade must be reported
    assert [f.id for f in done.invalidated] == [venue.id] and venue.id in done.removed


async def test_dependent_present_at_merge_base_is_not_a_dependency_conflict(repo):
    await story(repo, derive_first=True)
    plan = await plan_merge(repo, "planner", "main")
    assert plan.conflicts == []
    assert [f.o for f in plan.auto_merged] == ["mon"]
