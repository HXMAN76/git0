from git0.core.models import Episode, NewProcedure
from tests.core.test_merge_commit import commit, fact, merge

ZEROS = dict.fromkeys(
    [
        "episodes",
        "sessions",
        "facts_on_main",
        "procedures_on_main",
        "commits",
        "merges",
        "reverts",
        "handoffs",
        "conflicts_resolved",
        "precedents_reused",
        "agents",
        "tenants",
    ],
    0,
)


async def test_empty_repo_is_all_zeros(repo):
    card = await repo.scorecard()
    assert card.model_dump(exclude={"query_ms"}) == ZEROS  # root commit is not counted
    assert card.query_ms > 0


async def test_counts_after_commits_merge_episode_and_conflict(repo):
    old = fact("launch", "deadline", "fri")
    await commit(
        repo,
        "main",
        "base",
        facts=[old, fact("team", "owner", "ann")],
        episodes=[Episode(id="e1", text="hi", session_id="s1")],
    )
    await commit(
        repo,
        "main",
        "proc",
        procedures=[NewProcedure(id="p1", trigger="date moves", steps="[]")],
    )
    await repo.create_branch("feat")
    await commit(repo, "main", "ours", facts=[fact("launch", "deadline", "mon")])
    await commit(repo, "feat", "theirs", facts=[fact("launch", "deadline", "tue")])
    resolution = {"key": "launch|deadline", "p": "deadline", "side": "theirs", "base_id": old.id}
    ours = [f.id for f in await repo.checkout("main") if f.key == "launch|deadline"][0]
    theirs = [f.id for f in await repo.checkout("feat") if f.key == "launch|deadline"][0]
    resolution |= {"ours_id": ours, "theirs_id": theirs}
    assert await merge(repo, removed=[ours], resolutions=[resolution])

    # A second branch resolved the same way reuses the precedent once.
    await repo.create_branch("feat2")
    await commit(repo, "feat2", "theirs2", facts=[fact("launch", "deadline", "wed")])
    await commit(repo, "main", "ours2", facts=[fact("launch", "deadline", "thu")])
    ours2 = [f.id for f in await repo.checkout("main") if f.key == "launch|deadline"][0]
    theirs2 = [f.id for f in await repo.checkout("feat2") if f.key == "launch|deadline"][0]
    res2 = {
        "key": "launch|deadline",
        "p": "deadline",
        "side": "theirs",
        "ours_id": ours2,
        "theirs_id": theirs2,
    }
    assert await merge(repo, source="feat2", removed=[ours2], resolutions=[res2])

    card = await repo.scorecard()
    assert card.episodes == 1 and card.sessions == 1
    assert card.facts_on_main == 2  # team|owner + the winning deadline
    assert card.procedures_on_main == 1
    assert card.commits == 8  # base, proc, ours, theirs, merge, theirs2, ours2, merge
    assert card.merges == 2 and card.reverts == 0 and card.handoffs == 0
    assert card.conflicts_resolved == 2
    assert card.precedents_reused == 1  # (deadline, theirs) chosen twice
    assert card.agents == 2  # "a" and "merger"
