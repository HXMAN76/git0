import asyncio

import pytest

from git0.core.merge import plan_merge
from git0.core.models import Derivation, MergeStrategy
from git0.core.repo import new_id
from tests.core.test_merge_commit import commit, fact

KEY = "launch|deadline"


async def tick():
    # created_at is in ms; separate commits so latest-wins order is deterministic.
    await asyncio.sleep(0.01)


async def setup(repo, base_o="fri", p="deadline"):
    """base on main, then branch `feat`. Returns the base fact."""
    base = fact("launch", p, base_o)
    await commit(repo, "main", "base", facts=[base])
    await repo.create_branch("feat")
    return base


async def plan(repo):
    return await plan_merge(repo, source="feat", target="main")


async def test_unchanged_key_counted(repo):
    await setup(repo)
    r = await plan(repo)
    assert (r.unchanged, r.auto_merged, r.conflicts, r.removals) == (1, [], [], [])
    assert r.target_head == await repo.head("main")
    assert r.source_head == await repo.head("feat")
    assert r.base_commit == r.target_head


async def test_source_only_change_is_auto(repo):
    await setup(repo)
    new = fact("launch", "deadline", "mon")
    await commit(repo, "feat", "src", facts=[new])
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [new.id]
    assert r.removals == [] and r.conflicts == [] and r.unchanged == 0


async def test_target_only_change_is_auto(repo):
    await setup(repo)
    new = fact("launch", "deadline", "mon")
    await commit(repo, "main", "tgt", facts=[new])
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [new.id]
    assert r.removals == [] and r.conflicts == []


async def test_same_change_both_sides_dedupes_source_fact(repo):
    await setup(repo)
    ours, theirs = fact("launch", "deadline", "mon"), fact("launch", "deadline", "mon")
    await commit(repo, "main", "tgt", facts=[ours])
    await commit(repo, "feat", "src", facts=[theirs])
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [ours.id]
    assert r.removals == [theirs.id] and r.conflicts == []


async def test_both_deleted_is_auto_without_removals(repo):
    base = await setup(repo)
    await commit(repo, "main", "tgt", removed=[base.id])
    await commit(repo, "feat", "src", removed=[base.id])
    r = await plan(repo)
    assert (r.auto_merged, r.removals, r.conflicts) == ([], [], [])


async def test_latest_wins_removes_loser_and_its_dependents(repo):
    await setup(repo, "active", p="status")
    mine = fact("launch", "status", "paused")
    await commit(repo, "main", "tgt", facts=[mine])
    await tick()
    theirs = fact("launch", "status", "shipped")
    await commit(repo, "feat", "src", facts=[theirs])
    # a fact derived from the target-side loser, visible on target
    dep = fact("launch", "owner", "dana")
    await commit(repo, "main", "dep", facts=[dep], derived=[Derivation(child=dep.id, parent=mine.id)])
    r = await plan(repo)
    assert r.conflicts == []
    assert [f.id for f in r.auto_merged] == [theirs.id]  # source is newer
    assert sorted(r.removals) == sorted([mine.id, dep.id])


async def test_latest_wins_tie_goes_to_source(repo):
    await setup(repo, "active", p="status")
    mine, theirs = fact("launch", "status", "paused"), fact("launch", "status", "shipped")
    await commit(repo, "main", "tgt", facts=[mine])
    await commit(repo, "feat", "src", facts=[theirs])
    await repo.graph.query(
        "MATCH (f:Fact) WHERE f.id IN $ids SET f.created_at = 5", {"ids": [mine.id, theirs.id]}
    )
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [theirs.id] and r.removals == [mine.id]


async def test_latest_wins_deleted_side_loses(repo):
    base = await setup(repo, "active", p="status")
    mine = fact("launch", "status", "paused")
    await commit(repo, "main", "tgt", facts=[mine])
    await commit(repo, "feat", "src", removed=[base.id])
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [mine.id]
    assert r.removals == [] and r.conflicts == []


async def test_needs_review_conflict_carries_values_and_dependents(repo):
    base = await setup(repo)
    ours, theirs = fact("launch", "deadline", "mon"), fact("launch", "deadline", "tue")
    await commit(repo, "main", "tgt", facts=[ours])
    await commit(repo, "feat", "src", facts=[theirs])
    d_o, d_t = fact("plan_o", "owner", "o"), fact("plan_t", "owner", "t")
    await commit(repo, "main", "do", facts=[d_o], derived=[Derivation(child=d_o.id, parent=ours.id)])
    await commit(repo, "feat", "dt", facts=[d_t], derived=[Derivation(child=d_t.id, parent=theirs.id)])
    r = await plan(repo)
    assert r.removals == [] and len(r.conflicts) == 1
    # the dependents are one-sided new keys, so they merge automatically; the conflict key does not
    assert sorted(f.id for f in r.auto_merged) == sorted([d_o.id, d_t.id])
    c = r.conflicts[0]
    assert (c.key, c.strategy) == (KEY, MergeStrategy.NEEDS_REVIEW)
    assert (c.base.o, c.ours.o, c.theirs.o) == ("fri", "mon", "tue")
    assert c.base.id == base.id
    assert [f.id for f in c.dependents_ours] == [d_o.id]
    assert [f.id for f in c.dependents_theirs] == [d_t.id]
    assert (c.precedent, c.precedent_choice, c.precedent_count) == (None, None, 0)


@pytest.mark.parametrize("deleted_side", ["main", "feat"])
async def test_delete_vs_change_is_conflict_with_one_side_none(repo, deleted_side):
    base = await setup(repo)
    changed_side = "feat" if deleted_side == "main" else "main"
    await commit(repo, deleted_side, "del", removed=[base.id])
    await commit(repo, changed_side, "chg", facts=[fact("launch", "deadline", "mon")])
    r = await plan(repo)
    assert len(r.conflicts) == 1
    c = r.conflicts[0]
    gone, kept = (c.ours, c.theirs) if deleted_side == "main" else (c.theirs, c.ours)
    assert gone is None and kept.o == "mon" and c.base.o == "fri"


async def test_precedent_fields_filled(repo):
    await setup(repo)
    await commit(repo, "main", "tgt", facts=[fact("launch", "deadline", "mon")])
    await commit(repo, "feat", "src", facts=[fact("launch", "deadline", "tue")])
    # two earlier human resolutions for `deadline` chose the source side
    for _ in range(2):
        await repo.graph.query(
            "MERGE (pr:Precedent {key_pattern: 'deadline', choice: 'theirs'}) "
            "ON CREATE SET pr.count = 1 ON MATCH SET pr.count = pr.count + 1"
        )
    c = (await plan(repo)).conflicts[0]
    assert (c.precedent_choice, c.precedent_count) == ("theirs", 2)
    assert c.precedent == "theirs chosen 2x"


async def test_new_key_on_both_sides_with_different_values_conflicts(repo):
    await setup(repo)
    await commit(repo, "main", "tgt", facts=[fact("x", "owner", "a")])
    await commit(repo, "feat", "src", facts=[fact("x", "owner", "b")])
    r = await plan(repo)
    c = r.conflicts[0]
    assert c.key == "x|owner" and c.base is None and (c.ours.o, c.theirs.o) == ("a", "b")
    assert r.unchanged == 1  # launch|deadline


async def test_recommitted_equal_value_on_stale_side_is_removed(repo):
    # target re-commits the same value (new node); source changes it. The merge would otherwise
    # keep the re-committed node next to the source's new value (two values for one key).
    await setup(repo)
    stale = fact("launch", "deadline", "fri")
    await commit(repo, "main", "recommit", facts=[stale])
    new = fact("launch", "deadline", "mon")
    await commit(repo, "feat", "src", facts=[new])
    r = await plan(repo)
    assert [f.id for f in r.auto_merged] == [new.id]
    assert r.removals == [stale.id]


async def test_view_with_two_facts_for_one_key_raises(repo):
    await setup(repo)
    # forge a violation of invariant 7 on main: a second visible node for the same key
    await repo.graph.query(
        "MATCH (c:Commit {id: $h}) CREATE (:Fact {id: $i, s: 'launch', p: 'deadline', o: 'zzz', "
        "key: 'launch|deadline', created_at: 1})-[:ADDED_IN]->(c)",
        {"h": await repo.head("main"), "i": new_id()},
    )
    with pytest.raises(ValueError, match="launch\\|deadline"):
        await plan(repo)
