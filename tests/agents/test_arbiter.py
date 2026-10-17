"""Arbiter: explain (one LLM call, keys must match); rederive (one step per owner, invalidated facts only)."""

import pytest

from git0.agents.arbiter import ConflictExplanation, Explanations, explain, rederive
from git0.agents.extract import ExtractedFact, ExtractedLink, Extraction
from git0.core.merge import apply_merge, plan_merge
from git0.core.models import CommitRequest, Conflict, Fact, MergeResult, MergeStrategy, NewFact
from git0.core.repo import MemoryRepo
from git0.llm.client import LLMError, Usage
from git0.seed import LAUNCH_DEADLINE, seed

USAGE = Usage(model="fake", prompt_tokens=11, completion_tokens=7, provider="fake")


def fact(id_, s, p, o, agent="planner") -> Fact:
    return Fact(id=id_, s=s, p=p, o=o, key=f"{s}|{p}", agent_id=agent)


def conflict(s="launch", p="deadline") -> Conflict:
    return Conflict(
        key=f"{s}|{p}",
        base=fact("b", s, p, "friday"),
        ours=fact("o", s, p, "friday", "scheduler"),
        theirs=fact("t", s, p, "monday"),
        strategy=MergeStrategy.NEEDS_REVIEW,
        reason="dependency",
        dependents_ours=[fact("d1", "venue", "status", "booked friday", "scheduler")],
        precedent="last time: theirs (2x)",
    )


def plan(*conflicts: Conflict) -> MergeResult:
    return MergeResult(
        source="planner", target="main", base_commit="c0", target_head="c1", source_head="c2",
        conflicts=list(conflicts),
    )  # fmt: skip


class FakeLLM:
    def __init__(self, *outputs):
        self.queue, self.prompts, self.schemas = list(outputs), [], []

    async def __call__(self, prompt, schema, *, system, tenant):
        self.prompts.append(prompt)
        self.schemas.append(schema)
        return self.queue.pop(0), USAGE


async def test_explain_without_conflicts_makes_no_llm_call():
    llm = FakeLLM()
    assert await explain(plan(), tenant="t", llm=llm) == []
    assert llm.prompts == []


async def test_explain_maps_texts_to_keys_in_one_call_and_drops_extra_keys():
    llm = FakeLLM(
        Explanations(
            items=[
                ConflictExplanation(key="extra|owner", text="ignored"),
                ConflictExplanation(key="launch|deadline", text="Planner says Monday."),
                ConflictExplanation(key="launch|budget", text="Budget differs."),
            ]
        )
    )
    out = await explain(plan(conflict(), conflict("launch", "budget")), tenant="t", llm=llm)
    assert out == [
        ConflictExplanation(key="launch|deadline", text="Planner says Monday."),
        ConflictExplanation(key="launch|budget", text="Budget differs."),
    ]
    assert len(llm.prompts) == 1 and llm.schemas == [Explanations]
    p = llm.prompts[0]
    assert "launch|deadline" in p and "monday" in p and "friday" in p
    assert "venue|status=booked friday" in p and "last time: theirs (2x)" in p


async def test_explain_raises_when_a_conflict_key_is_missing():
    llm = FakeLLM(Explanations(items=[ConflictExplanation(key="other|key", text="x")]))
    with pytest.raises(LLMError, match="launch\\|deadline"):
        await explain(plan(conflict()), tenant="t", llm=llm)


class ReplanLLM:
    """Returns the queued Extraction for each step call and records prompts."""

    def __init__(self, *extractions: Extraction):
        self.queue, self.prompts = list(extractions), []

    async def __call__(self, prompt, schema, *, system, tenant):
        assert schema is Extraction
        self.prompts.append(prompt)
        return self.queue.pop(0), USAGE


def replan() -> Extraction:
    return Extraction(
        reply="Re-planned for Monday.",
        facts=[
            ExtractedFact(s="venue", p="status", o="booked monday"),
            ExtractedFact(s="invites", p="status", o="sent for monday"),
            ExtractedFact(s="catering", p="deadline", o="friday"),
        ],
        removed_keys=[],
        derived=[
            ExtractedLink(child_key=k, parent_key="launch|deadline")
            for k in ("venue|status", "invites|status", "catering|deadline")
        ],
        procedures=[],
        cited_keys=["launch|deadline"],
    )


async def dependency_conflict_story(repo: MemoryRepo):
    """Scheduler's 3 tasks derive from the Friday deadline; planner moves it to Monday; human picks Monday."""
    await seed(repo)
    first = await plan_merge(repo, "scheduler", "main")
    assert first.conflicts == []
    await apply_merge(repo, first, {}, "human", "take scheduler")
    await repo.commit(
        CommitRequest(
            branch="planner", agent_id="planner", msg="move launch to monday",
            facts=[NewFact(id="planner-launch-deadline", s="launch", p="deadline", o="monday")],
        )
    )  # fmt: skip
    second = await plan_merge(repo, "planner", "main")
    (c,) = second.conflicts
    return await apply_merge(repo, second, {c.key: c.theirs.id}, "human", "monday wins")


async def test_rederive_runs_one_step_per_owner_for_invalidated_facts_only(repo):
    applied = await dependency_conflict_story(repo)
    assert len(applied.invalidated) == 3 and {f.agent_id for f in applied.invalidated} == {"scheduler"}
    before = {f.key for f in await repo.checkout("main")}
    assert "venue|status" not in before

    llm = ReplanLLM(replan())
    res = await rederive(repo, applied.invalidated, target="main", tenant="t", session_id="s1", llm=llm)

    assert res.owners == ["scheduler"] and res.skipped == []
    assert len(llm.prompts) == 1 and len(res.replies) == 1  # one call for the one owner, not per fact
    assert res.tokens == 18
    for f in applied.invalidated:
        assert f"{f.s}|{f.p} = {f.o}" in llm.prompts[0]
    assert "launch|deadline = monday" in llm.prompts[0]  # the current fact it re-plans against
    assert res.replies[0].branch == "main" and res.replies[0].commit_id == await repo.head("main")
    after = {f.key: f.o for f in await repo.checkout("main")}
    assert after["venue|status"] == "booked monday" and after["invites|status"] == "sent for monday"
    # Re-derived tasks are linked to the new deadline fact.
    new_deadline = next(f for f in await repo.checkout("main") if f.key == "launch|deadline")
    assert {d.key for d in await repo.dependents_visible(new_deadline.id, await repo.head("main"))} == {
        "venue|status", "invites|status", "catering|deadline",
    }  # fmt: skip
    assert LAUNCH_DEADLINE not in {f.id for f in await repo.checkout("main")}


async def test_rederive_maps_handoff_successor_and_skips_unknown_owners(repo):
    await repo.create_branch("scratch")
    facts = [fact("a", "venue", "status", "x", "scheduler-2"), fact("b", "qa", "owner", "y", "human")]
    llm = ReplanLLM(replan())
    res = await rederive(repo, facts, target="scratch", tenant="t", session_id="s", llm=llm)
    assert res.owners == ["scheduler-2"] and res.skipped == ["human"]
    assert res.replies[0].agent_id == "scheduler" and len(llm.prompts) == 1


async def test_rederive_with_nothing_invalidated_makes_no_call(repo):
    llm = ReplanLLM()
    res = await rederive(repo, [], target="main", tenant="t", session_id="s", llm=llm)
    assert res.replies == [] and res.tokens == 0 and res.owners == [] and llm.prompts == []


async def test_facts_by_ids_returns_removed_facts_too(repo):
    applied = await dependency_conflict_story(repo)
    ids = [f.id for f in applied.invalidated]
    got = await repo.facts_by_ids(ids)
    assert {f.id for f in got} == set(ids)
    assert await repo.facts_by_ids([]) == []
