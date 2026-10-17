"""Extraction schema and commit mapping: pure tests, plus one real-graph commit round trip."""

import json

from git0.agents.extract import (
    ExtractedFact,
    ExtractedLink,
    ExtractedProcedure,
    Extraction,
    build_prompt,
    normalise_entity,
    to_commit_request,
)
from git0.core.models import CommitRequest, Episode, Fact, NewFact, Procedure
from git0.core.queries import Q
from git0.core.repo import new_id
from git0.llm.client import strict_schema


def ext(
    facts=(),
    removed_keys=(),
    derived=(),
    procedures=(),
    cited_keys=(),
    reply="ok",
) -> Extraction:
    return Extraction(
        reply=reply,
        facts=list(facts),
        removed_keys=list(removed_keys),
        derived=list(derived),
        procedures=list(procedures),
        cited_keys=list(cited_keys),
    )


def visible(s, p, o, fid=None) -> Fact:
    return Fact(id=fid or new_id(), s=s, p=p, o=o, key=f"{s}|{p}")


def episode() -> Episode:
    return Episode(id=new_id(), text="msg", session_id="s1")


def to_req(e, view=()):
    return to_commit_request(e, list(view), branch="main", agent_id="planner", msg="m", episode=episode())


def test_normalise_entity_lowercases_and_joins_whitespace_and_hyphens():
    assert normalise_entity("  Launch-Date  ") == "launch_date"
    assert normalise_entity("Acme   Corp") == "acme_corp"
    assert normalise_entity("   ") == ""


def test_extraction_schema_converts_to_groq_strict_form():
    schema = strict_schema(Extraction)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "reply",
        "facts",
        "removed_keys",
        "derived",
        "procedures",
        "cited_keys",
    }


def test_facts_get_normalised_subjects_and_empty_subjects_are_dropped():
    req, _ = to_req(
        ext(
            facts=[
                ExtractedFact(s="Launch Date", p="deadline", o="fri"),
                ExtractedFact(s="   ", p="owner", o="ann"),
            ]
        )
    )
    assert [(f.s, f.p, f.o) for f in req.facts] == [("launch_date", "deadline", "fri")]


def test_duplicate_key_keeps_last_value():
    req, _ = to_req(
        ext(
            facts=[
                ExtractedFact(s="Launch", p="deadline", o="fri"),
                ExtractedFact(s="launch", p="deadline", o="mon"),
            ]
        )
    )
    assert [(f"{f.s}|{f.p}", f.o) for f in req.facts] == [("launch|deadline", "mon")]


def test_removed_keys_resolve_to_visible_ids_except_keys_the_commit_sets():
    view = [visible("launch", "owner", "ann", "old-owner"), visible("launch", "deadline", "fri", "old-dl")]
    req, _ = to_req(
        ext(
            facts=[ExtractedFact(s="launch", p="deadline", o="mon")],
            removed_keys=["Launch|Owner", "launch|deadline", "gone|owner"],
        ),
        view,
    )
    # deadline is replaced by the new fact (commit_cas retires it); gone|owner is not visible.
    assert req.removed == ["old-owner"]


def test_derived_child_must_be_new_and_parent_prefers_new_fact():
    view = [visible("launch", "deadline", "fri", "old-dl")]
    req, _ = to_req(
        ext(
            facts=[
                ExtractedFact(s="launch", p="budget", o="10k"),
                ExtractedFact(s="launch", p="deadline", o="mon"),
            ],
            derived=[ExtractedLink(child_key="launch|budget", parent_key="launch|deadline")],
        ),
        view,
    )
    new = {f"{f.s}|{f.p}": f.id for f in req.facts}
    assert [(d.child, d.parent) for d in req.derived] == [(new["launch|budget"], new["launch|deadline"])]


def test_derived_parent_falls_back_to_visible_fact():
    view = [visible("launch", "deadline", "fri", "old-dl")]
    req, _ = to_req(
        ext(
            facts=[ExtractedFact(s="launch", p="budget", o="10k")],
            derived=[ExtractedLink(child_key="launch|budget", parent_key="launch|deadline")],
        ),
        view,
    )
    assert [d.parent for d in req.derived] == ["old-dl"]


def test_repeated_derived_link_gives_one_derivation():
    view = [visible("launch", "deadline", "fri", "old-dl")]
    link = ExtractedLink(child_key="launch|budget", parent_key="launch|deadline")
    req, _ = to_req(
        ext(facts=[ExtractedFact(s="launch", p="budget", o="10k")], derived=[link, link]),
        view,
    )
    assert len(req.derived) == 1
    assert req.derived[0].parent == "old-dl"


def test_derived_links_with_unknown_parent_or_non_new_child_are_dropped():
    view = [visible("launch", "deadline", "fri", "old-dl")]
    req, _ = to_req(
        ext(
            facts=[ExtractedFact(s="launch", p="budget", o="10k")],
            derived=[
                ExtractedLink(child_key="launch|budget", parent_key="nope|owner"),
                ExtractedLink(child_key="launch|deadline", parent_key="launch|budget"),
                ExtractedLink(child_key="launch|budget", parent_key="launch|budget"),
            ],
        ),
        view,
    )
    assert req.derived == []


def test_procedures_become_json_step_lists_with_fresh_ids():
    req, _ = to_req(
        ext(procedures=[ExtractedProcedure(trigger="launch date moves", steps=["tell venue", "rebook"])])
    )
    (proc,) = req.procedures
    assert proc.trigger == "launch date moves"
    assert json.loads(proc.steps) == ["tell venue", "rebook"]
    assert proc.id


def test_cited_keys_map_to_new_or_visible_ids_and_skip_unknown():
    view = [visible("launch", "owner", "ann", "old-owner")]
    req, cited = to_req(
        ext(
            facts=[ExtractedFact(s="launch", p="deadline", o="mon")],
            cited_keys=["Launch|Deadline", "Launch|Owner", "nope|status"],
        ),
        view,
    )
    assert cited == {"launch|deadline": req.facts[0].id, "launch|owner": "old-owner"}


def test_prompt_lists_entities_facts_procedures_predicates_and_message():
    view = [
        visible("venue", "status", "held", "f2"),
        visible("launch", "deadline", "fri", "f1"),
    ]
    procs = [Procedure(id="p1", trigger="launch date moves", steps=json.dumps(["tell venue", "rebook"]))]
    prompt = build_prompt(view, procs, "move launch to monday")
    assert "launch, venue" in prompt
    assert "launch|deadline = fri" in prompt and "venue|status = held" in prompt
    assert "launch date moves: tell venue; rebook" in prompt
    for predicate in ["deadline", "owner", "status", "location", "budget", "decision"]:
        assert predicate in prompt
    assert prompt.rstrip().endswith("move launch to monday")


def test_prompt_is_deterministic_regardless_of_view_order():
    a = [visible("launch", "deadline", "fri", "f1"), visible("venue", "status", "held", "f2")]
    assert build_prompt(a, [], "hi") == build_prompt(list(reversed(a)), [], "hi")


async def test_commit_round_trip_on_graph_writes_derivation(repo):
    parent = visible("launch", "deadline", "fri")
    await repo.commit(
        CommitRequest(
            branch="main",
            agent_id="planner",
            msg="seed",
            facts=[NewFact(id=parent.id, s="launch", p="deadline", o="fri")],
        )
    )
    view = await repo.checkout("main")
    req, cited = to_commit_request(
        ext(
            facts=[ExtractedFact(s="Launch", p="budget", o="10k")],
            # The same link twice must still land as exactly one DERIVED_FROM edge.
            derived=[
                ExtractedLink(child_key="launch|budget", parent_key="launch|deadline"),
                ExtractedLink(child_key="launch|budget", parent_key="launch|deadline"),
            ],
            cited_keys=["launch|deadline"],
        ),
        view,
        branch="main",
        agent_id="planner",
        msg="budget",
        episode=episode(),
    )
    await repo.commit(req)
    child_id = next(f.id for f in req.facts if f.p == "budget")
    edges = await repo.graph.ro_query(Q["derived_edge_count"], {"child": child_id, "parent": parent.id})
    assert edges.result_set[0][0] == 1
    facts = {f.key: f for f in await repo.checkout("main")}
    assert facts["launch|budget"].o == "10k"
    assert cited == {"launch|deadline": parent.id}
    children = {d["id"] for d in await repo.dependents(parent.id)}
    assert facts["launch|budget"].id in children
