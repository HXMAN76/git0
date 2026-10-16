import pytest

from git0.core.models import Derivation
from git0.core.revert import revert
from tests.core.test_merge_commit import commit, fact

KEY = "launch|deadline"


async def story(repo):
    """main: fri, then mon (replaces fri), then a venue derived from mon, plus an unrelated fact."""
    await commit(
        repo, "main", "base", facts=[fact("launch", "deadline", "fri"), fact("team", "owner", "ann")]
    )
    mon = fact("launch", "deadline", "mon")
    set_mon = await commit(repo, "main", "move to mon", facts=[mon])
    venue = fact("venue", "status", "booked_mon")
    await commit(repo, "main", "book", facts=[venue], derived=[Derivation(child=venue.id, parent=mon.id)])
    return set_mon, mon, venue


async def test_revert_restores_old_value_and_cascades(repo):
    set_mon, mon, venue = await story(repo)

    res = await revert(repo, "main", set_mon.id)

    assert res.reverted == [mon.id]
    assert res.cascaded == [venue.id]
    assert len(res.restored) == 1
    assert res.unchanged == 1  # team|owner
    assert res.revert_commit == await repo.head("main")
    facts = {f.key: f for f in await repo.checkout("main")}
    assert {k: f.o for k, f in facts.items()} == {KEY: "fri", "team|owner": "ann"}
    assert facts[KEY].id == res.restored[0]  # a fresh copy, not the original fri

    [top] = await repo.log("main", limit=1)
    assert top.kind == "revert" and top.msg == f"revert {set_mon.id}"


async def test_revert_commit_not_on_branch_raises(repo):
    await commit(repo, "main", "base", facts=[fact("a", "owner", "x")])
    await repo.create_branch("feat")
    other = await commit(repo, "feat", "only on feat", facts=[fact("b", "owner", "y")])
    with pytest.raises(ValueError, match="not in the history"):
        await revert(repo, "main", other.id)
    with pytest.raises(ValueError, match="not in the history"):
        await revert(repo, "main", "nosuchcommit")


async def test_revert_twice_has_nothing_to_revert(repo):
    set_mon, _, _ = await story(repo)
    await revert(repo, "main", set_mon.id)
    with pytest.raises(ValueError, match="nothing to revert"):
        await revert(repo, "main", set_mon.id)


async def test_revert_empty_commit_raises(repo):
    await commit(repo, "main", "base", facts=[fact("a", "owner", "x")])
    empty = await commit(repo, "main", "nothing")
    with pytest.raises(ValueError, match="nothing to revert"):
        await revert(repo, "main", empty.id)


async def test_revert_keeps_old_value_when_key_is_held_by_a_later_fact(repo):
    # fri -> mon (commit A) -> tue (commit B): A's mon is already gone and tue holds the key, so reverting A
    # must not bring fri back.
    await commit(repo, "main", "base", facts=[fact("launch", "deadline", "fri")])
    set_mon = await commit(repo, "main", "mon", facts=[fact("launch", "deadline", "mon")])
    tue = fact("launch", "deadline", "tue")
    await commit(repo, "main", "tue", facts=[tue])
    with pytest.raises(ValueError, match="nothing to revert"):
        await revert(repo, "main", set_mon.id)
    assert [f.id for f in await repo.checkout("main")] == [tue.id]


async def test_revert_root_commit_removes_its_facts(repo):
    root = (await repo.log("main", limit=1))[0]
    c = await commit(repo, "main", "add", facts=[fact("a", "owner", "x")])
    res = await revert(repo, "main", c.id)
    assert len(res.reverted) == 1 and res.restored == [] and res.unchanged == 0
    assert await repo.checkout("main") == []
    assert root.id  # root exists; reverting it has nothing to undo
    with pytest.raises(ValueError, match="nothing to revert"):
        await revert(repo, "main", root.id)


async def test_revert_recomputes_when_head_moves(repo):
    set_mon, mon, venue = await story(repo)
    real, moved = repo.try_commit, []

    async def racing(req, expected):
        if not moved:  # someone commits between our read and our CAS
            moved.append(True)  # before committing: repo.commit routes through this patched try_commit too
            await commit(repo, "main", "race", facts=[fact("x", "owner", "y")])
        return await real(req, expected)

    repo.try_commit = racing
    res = await revert(repo, "main", set_mon.id)
    assert moved and res.unchanged == 2  # team|owner and the racing fact, seen on the second attempt
    assert {f.key for f in await repo.checkout("main")} == {KEY, "team|owner", "x|owner"}
