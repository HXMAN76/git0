"""Agent step against a real graph with a fake LLM: commit, persistence, branch isolation, not-in-memory."""

import pytest

from git0.agents.base import step
from git0.agents.extract import ExtractedFact, ExtractedLink, Extraction
from git0.agents.specs import AGENTS, ARBITER, NOTES, PLANNER, SCHEDULER
from git0.core.models import CommitRequest, NewFact
from git0.core.repo import new_id
from git0.llm.client import LLMError, Usage

USAGE = Usage(model="fake", prompt_tokens=11, completion_tokens=7, provider="fake")


class FakeLLM:
    """Records every prompt/system and returns the queued Extraction."""

    def __init__(self, *extractions: Extraction):
        self.queue, self.prompts, self.systems = list(extractions), [], []

    async def __call__(self, prompt, schema, *, system, tenant):
        assert schema is Extraction
        self.prompts.append(prompt)
        self.systems.append(system)
        return self.queue.pop(0), USAGE


def ext(facts=(), cited=(), derived=(), reply="done") -> Extraction:
    return Extraction(
        reply=reply,
        facts=[ExtractedFact(s=s, p=p, o=o) for s, p, o in facts],
        removed_keys=[],
        derived=[ExtractedLink(child_key=c, parent_key=p) for c, p in derived],
        procedures=[],
        cited_keys=list(cited),
    )


async def add_main_fact(repo, s, p, o):
    await repo.commit(
        CommitRequest(branch="main", agent_id="seed", msg="seed", facts=[NewFact(id=new_id(), s=s, p=p, o=o)])
    )


async def test_specs_are_consistent():
    assert set(AGENTS) == {"planner", "scheduler", "notes", "arbiter"}
    assert [(a.id, a.branch) for a in (PLANNER, SCHEDULER, NOTES, ARBITER)] == [
        ("planner", "planner"),
        ("scheduler", "scheduler"),
        ("notes", "notes"),
        ("arbiter", "main"),
    ]
    assert all(AGENTS[k].id == k for k in AGENTS)
    assert "derived" in SCHEDULER.prompt and "ALWAYS" in SCHEDULER.prompt
    for a in AGENTS.values():
        assert "cited_keys" in a.prompt


async def test_step_commits_episode_under_session_and_facts_are_visible(repo):
    await repo.create_branch("planner")
    llm = FakeLLM(ext(facts=[("Launch", "deadline", "June 1")], cited=["launch|deadline"], reply="Set."))

    reply = await step(PLANNER, repo, "launch is June 1", "sess-1", tenant="t", llm=llm)

    assert reply.agent_id == "planner" and reply.branch == "planner"
    assert reply.text == "Set." and reply.missing_keys == []
    assert reply.usage == USAGE
    assert llm.systems == [PLANNER.prompt]
    assert reply.commit_id == await repo.head("planner")
    (head, *_) = await repo.log("planner")
    assert head.agent_id == "planner" and head.kind == "commit"
    assert head.msg == "planner: launch is June 1"

    facts = {f.key: f for f in await repo.checkout("planner")}
    assert facts["launch|deadline"].o == "June 1"
    assert reply.cited_fact_ids == [facts["launch|deadline"].id]

    res = await repo.graph.ro_query(
        "MATCH (:Session {id: 'sess-1'})-[:HAS_TURN]->(e:Episode)<-[:FROM_EPISODE]-(c:Commit {id: $c}) "
        "RETURN e.text",
        {"c": reply.commit_id},
    )
    assert res.result_set == [["launch is June 1"]]


async def test_commit_msg_truncates_user_msg_to_60_chars(repo):
    await repo.create_branch("notes")
    msg = "x" * 100
    await step(NOTES, repo, msg, "s", tenant="t", llm=FakeLLM(ext()))
    assert (await repo.log("notes"))[0].msg == f"notes: {'x' * 60}"


async def test_second_turn_prompt_contains_first_turn_fact(repo):
    await repo.create_branch("planner")
    llm = FakeLLM(ext(facts=[("launch", "deadline", "June 1")]), ext())
    await step(PLANNER, repo, "launch is June 1", "s", tenant="t", llm=llm)
    await step(PLANNER, repo, "what is the date?", "s", tenant="t", llm=llm)
    assert "launch|deadline = June 1" not in llm.prompts[0]
    assert "launch|deadline = June 1" in llm.prompts[1]


async def test_missing_branch_is_created_from_main(repo):
    await add_main_fact(repo, "team", "owner", "ana")
    llm = FakeLLM(ext())
    reply = await step(SCHEDULER, repo, "hi", "s", tenant="t", llm=llm)
    assert "team|owner = ana" in llm.prompts[0]
    assert reply.commit_id == await repo.head("scheduler")


async def test_branch_isolation_main_fact_added_after_branching_is_invisible(repo):
    await repo.create_branch("planner")
    await add_main_fact(repo, "zebra", "budget", "9000")
    llm = FakeLLM(ext())
    await step(PLANNER, repo, "status?", "s", tenant="t", llm=llm)
    assert "zebra" not in llm.prompts[0]


async def test_branch_override_runs_arbiter_on_main(repo):
    await repo.create_branch("scratch")
    await add_main_fact(repo, "zebra", "budget", "9000")
    llm = FakeLLM(ext(facts=[("zebra", "status", "checked")]))
    reply = await step(ARBITER, repo, "explain", "s", tenant="t", llm=llm)
    assert reply.branch == "main" and "zebra|budget = 9000" in llm.prompts[0]

    other = FakeLLM(ext())
    reply = await step(ARBITER, repo, "explain", "s", tenant="t", llm=other, branch="scratch")
    assert reply.branch == "scratch"
    assert reply.commit_id == await repo.head("scratch")
    assert "zebra" not in other.prompts[0]  # scratch branched before main got either fact


async def test_missing_cited_key_appends_exact_not_in_memory_text(repo):
    await repo.create_branch("planner")
    llm = FakeLLM(
        ext(
            facts=[("launch", "deadline", "June 1")],
            cited=["Ghost|owner", "launch|deadline", "Other Thing|deadline"],
            reply="Answer.",
        )
    )
    reply = await step(PLANNER, repo, "q", "s", tenant="t", llm=llm)
    assert reply.missing_keys == ["ghost|owner", "other_thing|deadline"]
    assert reply.text == (
        "Answer.\n\nNot in team memory (no path from planner HEAD): ghost|owner, other_thing|deadline"
    )
    assert len(reply.cited_fact_ids) == 1


async def test_cited_fact_ids_follow_cited_key_order_and_skip_unknown(repo):
    await add_main_fact(repo, "a", "owner", "1")
    await add_main_fact(repo, "b", "owner", "2")
    await repo.create_branch("notes")
    facts = {f.key: f.id for f in await repo.checkout("notes")}
    llm = FakeLLM(ext(cited=["b|owner", "zzz|owner", "a|owner"]))
    reply = await step(NOTES, repo, "q", "s", tenant="t", llm=llm)
    assert reply.cited_fact_ids == [facts["b|owner"], facts["a|owner"]]


async def test_derived_links_are_committed(repo):
    await repo.create_branch("scheduler")
    llm = FakeLLM(
        ext(
            facts=[("launch", "deadline", "June 1"), ("task_ship", "deadline", "May 25")],
            derived=[("task_ship|deadline", "launch|deadline")],
        )
    )
    await step(SCHEDULER, repo, "plan", "s", tenant="t", llm=llm)
    facts = {f.key: f for f in await repo.checkout("scheduler")}
    deps = await repo.dependents(facts["launch|deadline"].id)
    assert [d["id"] for d in deps] == [facts["task_ship|deadline"].id]


async def test_llm_error_propagates_and_nothing_is_committed(repo):
    await repo.create_branch("planner")
    before = await repo.head("planner")

    async def boom(prompt, schema, *, system, tenant):
        raise LLMError("all LLM providers failed")

    with pytest.raises(LLMError):
        await step(PLANNER, repo, "hi", "s", tenant="t", llm=boom)
    assert await repo.head("planner") == before
    res = await repo.graph.ro_query("MATCH (e:Episode) RETURN count(e)")
    assert res.result_set == [[0]]
