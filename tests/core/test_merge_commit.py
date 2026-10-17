from git0.core.models import CommitRequest, NewFact
from git0.core.repo import new_id


def fact(s, p, o, fid=None):
    return NewFact(id=fid or new_id(), s=s, p=p, o=o)


async def commit(repo, branch, msg, **kw):
    c, _ = await repo.commit(CommitRequest(branch=branch, agent_id="a", msg=msg, **kw))
    return c


async def merge(repo, target="main", source="feat", removed=(), resolutions=(), expected=None):
    return await repo.try_merge_commit(
        target,
        expected or await repo.head(target),
        await repo.head(source),
        list(removed),
        list(resolutions),
        "merge",
        "merger",
    )


async def test_init_seeds_nine_rules_idempotently(repo):
    await repo.init()
    rules = await repo.rules()
    assert len(rules) == 9
    assert rules["deadline"] == "needs-review" and rules["status"] == "latest-wins"


async def test_merge_makes_source_only_facts_visible(repo):
    await commit(repo, "main", "base", facts=[fact("a", "owner", "x")])
    await repo.create_branch("feat")
    await commit(repo, "feat", "src", facts=[fact("b", "owner", "y")])
    await commit(repo, "main", "tgt", facts=[fact("c", "owner", "z")])
    assert await merge(repo)
    assert sorted(f.key for f in await repo.checkout("main")) == ["a|owner", "b|owner", "c|owner"]


async def test_fact_removed_on_source_is_hidden_after_merge(repo):
    f = fact("a", "owner", "x")
    await commit(repo, "main", "base", facts=[f])
    await repo.create_branch("feat")
    await commit(repo, "feat", "drop", removed=[f.id])
    await commit(repo, "main", "tgt", facts=[fact("c", "owner", "z")])
    await merge(repo)
    assert [f.key for f in await repo.checkout("main")] == ["c|owner"]


async def test_removed_hides_chosen_fact(repo):
    await commit(repo, "main", "base")
    await repo.create_branch("feat")
    ours = fact("a", "deadline", "fri")
    await commit(repo, "main", "ours", facts=[ours])
    await commit(repo, "feat", "theirs", facts=[fact("a", "deadline", "mon")])
    assert await merge(repo, removed=[ours.id])
    facts = await repo.checkout("main")
    assert [f.o for f in facts if f.key == "a|deadline"] == ["mon"]


async def test_seq_is_max_plus_one_with_both_parents(repo):
    await commit(repo, "main", "base")
    await repo.create_branch("feat")
    await commit(repo, "feat", "s1")
    await commit(repo, "feat", "s2")
    await commit(repo, "main", "t1")
    ht, hs = await repo.head("main"), await repo.head("feat")
    m = await merge(repo)
    assert m.seq == 4  # base=1, feat=3, main=2 -> max(2,3)+1
    res = await repo.graph.ro_query("MATCH (:Commit {id: $m})-[:PARENT]->(p:Commit) RETURN p.id", {"m": m.id})
    assert {r[0] for r in res.result_set} == {ht, hs}
    assert await repo.head("main") == m.id
    log = await repo.log("main")
    assert log[0].kind == "merge"


async def test_log_lists_parents_so_the_ui_can_draw_merges(repo):
    await commit(repo, "main", "base")
    await repo.create_branch("feat")
    await commit(repo, "feat", "src")
    await commit(repo, "main", "tgt")
    ht, hs = await repo.head("main"), await repo.head("feat")
    m = await merge(repo)
    by_id = {c.id: c for c in await repo.log("main")}
    assert sorted(by_id[m.id].parents) == sorted([ht, hs])
    assert len(by_id[ht].parents) == 1  # a plain commit has one parent
    assert any(c.parents == [] for c in by_id.values())  # the root from init has none


async def test_stale_expected_target_returns_none_and_writes_nothing(repo):
    await commit(repo, "main", "base")
    await repo.create_branch("feat")
    await commit(repo, "feat", "src", facts=[fact("b", "owner", "y")])
    stale = await repo.head("main")
    await commit(repo, "main", "tgt")
    head = await repo.head("main")
    assert (
        await merge(
            repo,
            expected=stale,
            removed=["nope"],
            resolutions=[
                {
                    "key": "k",
                    "p": "owner",
                    "side": "ours",
                    "base_id": None,
                    "ours_id": None,
                    "theirs_id": None,
                }
            ],
        )
        is None
    )
    assert await repo.head("main") == head
    assert await repo.checkout("main") == []
    res = await repo.graph.ro_query("MATCH (c:Conflict) RETURN count(c)")
    assert res.result_set[0][0] == 0


async def test_resolutions_create_conflict_and_precedent_count(repo):
    base = fact("a", "deadline", "wed")
    await commit(repo, "main", "base", facts=[base])
    await repo.create_branch("feat")
    ours, theirs = fact("a", "deadline", "fri"), fact("a", "deadline", "mon")
    await commit(repo, "main", "ours", facts=[ours])
    await commit(repo, "feat", "theirs", facts=[theirs])
    res = {
        "key": "a|deadline",
        "p": "deadline",
        "side": "theirs",
        "base_id": base.id,
        "ours_id": ours.id,
        "theirs_id": theirs.id,
    }
    assert await merge(repo, removed=[ours.id], resolutions=[res])
    rows = (
        await repo.graph.ro_query(
            "MATCH (cf:Conflict {key: 'a|deadline'})-[:RESOLVED_BY]->(pr:Precedent) "
            "MATCH (cf)-[:SIDE_A]->(a), (cf)-[:SIDE_B]->(b), (cf)-[:BASE]->(bs) "
            "RETURN a.id, b.id, bs.id, pr.count, cf.status"
        )
    ).result_set
    assert rows == [[ours.id, theirs.id, base.id, 1, "resolved"]]

    # same predicate + same choice on a second conflict (one-sided: no base, no ours) bumps the count
    await repo.create_branch("feat2")
    await commit(repo, "feat2", "t2", facts=[fact("z", "deadline", "tue")])
    res2 = {
        "key": "z|deadline",
        "p": "deadline",
        "side": "theirs",
        "base_id": None,
        "ours_id": None,
        "theirs_id": None,
    }
    assert await merge(repo, source="feat2", resolutions=[res2])
    count = (await repo.graph.ro_query("MATCH (pr:Precedent) RETURN pr.count")).result_set
    assert count == [[2]]


async def test_checkout_at_returns_base_view(repo):
    await commit(repo, "main", "base", facts=[fact("a", "owner", "x")])
    base = await repo.head("main")
    await commit(repo, "main", "later", facts=[fact("b", "owner", "y")])
    assert [f.key for f in await repo.checkout_at(base)] == ["a|owner"]
