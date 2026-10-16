import asyncio

from git0.core.models import CommitRequest, NewFact
from git0.seed import seed, seed_main


async def test_seed_twice_is_idempotent(repo):
    first = await seed(repo)
    main_log = await repo.log("main")
    second = await seed(repo)

    assert first["created"] is True
    assert second["created"] is False
    assert {k: v for k, v in first.items() if k != "created"} == {
        k: v for k, v in second.items() if k != "created"
    }
    assert first["facts_on_main"] == 37
    assert first["facts_on_scheduler"] == 40
    # the second call must not write: no new commits on any branch
    assert await repo.log("main") == main_log


async def test_scheduler_dependents_of_launch_deadline(repo):
    await seed(repo)
    head = await repo.head("scheduler")
    deps = await repo.dependents_visible("seed-launch-deadline", head)
    assert sorted(f.id for f in deps) == [
        "seed-catering-deadline",
        "seed-invites-status",
        "seed-venue-status",
    ]


async def test_seed_completes_room_when_branches_precreated(repo):
    # main already holds the launch facts; planner and scheduler exist but carry no seed facts
    await seed_main(repo)
    await repo.create_branch("planner", from_branch="main")
    await repo.create_branch("scheduler", from_branch="main")

    summary = await seed(repo)

    assert summary["created"] is True
    assert summary["facts_on_main"] == 37
    assert summary["facts_on_scheduler"] == 40


async def test_seed_after_main_only_does_not_duplicate_main(repo):
    await seed_main(repo)

    summary = await seed(repo)

    assert summary["created"] is True
    assert summary["facts_on_main"] == 37
    assert summary["facts_on_scheduler"] == 40
    # init root + the one seed commit: the retry must not re-commit main
    assert len(await repo.log("main")) == 2
    assert len({f.id for f in await repo.checkout("main")}) == 37


async def test_concurrent_seeds_end_with_full_room(repo):
    results = await asyncio.gather(seed(repo), seed(repo), return_exceptions=True)

    # a losing racer may raise ValueError (branch created first by the other call); the room must be whole
    errors = [r for r in results if isinstance(r, BaseException)]
    assert len(errors) <= 1 and all(isinstance(e, ValueError) for e in errors)
    assert len(await repo.checkout("main")) == 37
    assert len(await repo.checkout("scheduler")) == 40
    deps = await repo.dependents_visible("seed-launch-deadline", await repo.head("scheduler"))
    assert len(deps) == 3


async def _count_nodes(repo, fact_id):
    res = await repo.graph.ro_query("MATCH (f:Fact {id: $id}) RETURN count(f)", {"id": fact_id})
    return res.result_set[0][0]


async def test_reseed_after_demo_changed_seed_values_does_not_rerun(repo):
    """The demo moves the deadline and edits venue status, so those seed facts are no longer visible.
    Re-seeding must judge 'already done' by history, not visibility (it used to re-create main)."""
    await seed(repo)
    for branch, agent, fact_id, s, p, o in [
        ("main", "planner", "monday-deadline", "launch", "deadline", "monday"),
        ("scheduler", "scheduler", "venue-moved", "venue", "status", "booked monday"),
    ]:
        await repo.commit(
            CommitRequest(
                branch=branch, agent_id=agent, msg="demo edit", facts=[NewFact(id=fact_id, s=s, p=p, o=o)]
            )
        )
    main_log, sched_log = await repo.log("main"), await repo.log("scheduler")

    again = await seed(repo)

    assert again["created"] is False
    assert {f.key: f.o for f in await repo.checkout("main")}["launch|deadline"] == "monday"
    assert await _count_nodes(repo, "seed-launch-deadline") == 1
    assert await _count_nodes(repo, "seed-venue-status") == 1
    assert await repo.log("main") == main_log and await repo.log("scheduler") == sched_log
