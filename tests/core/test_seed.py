from git0.seed import seed


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
