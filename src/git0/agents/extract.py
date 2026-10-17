"""Extraction schema and commit mapping (Person B, Phase 1-2).

The LLM returns an `Extraction` with no ids and keys as plain text. `to_commit_request` turns it into one
CommitRequest: ids are assigned here and keys are normalised here, so the model cannot create a second
key for the same entity by spelling it differently.
"""

import json
import re
from typing import get_args

from pydantic import BaseModel, Field

from git0.core.models import (
    CommitRequest,
    Derivation,
    Episode,
    Fact,
    NewFact,
    NewProcedure,
    Predicate,
    Procedure,
)
from git0.core.repo import new_id


class ExtractedFact(BaseModel):
    s: str = Field(description="subject entity; reuse a known entity id when the message refers to it")
    p: Predicate
    o: str


class ExtractedLink(BaseModel):
    child_key: str = Field(
        description="key 'subject|predicate' of a fact in this reply that depends on the parent"
    )
    parent_key: str = Field(description="key 'subject|predicate' the child was derived from")


class ExtractedProcedure(BaseModel):
    trigger: str
    steps: list[str]


class Extraction(BaseModel):
    reply: str
    facts: list[ExtractedFact]
    removed_keys: list[str] = Field(description="keys 'subject|predicate' the message retracts")
    derived: list[ExtractedLink]
    procedures: list[ExtractedProcedure]
    cited_keys: list[str] = Field(description="keys 'subject|predicate' of facts the reply relies on")


def normalise_entity(s: str) -> str:
    """Lowercase, and turn each run of whitespace or hyphens into one underscore.

    Keeps 'Launch Date' and 'launch-date' on the same fact key.
    """
    return re.sub(r"[\s-]+", "_", s.strip().lower())


def _key(raw: str) -> str | None:
    """Normalise a 'subject|predicate' string the way fact keys are built. None when it has no '|'."""
    s, sep, p = raw.rpartition("|")
    if not sep:
        return None
    return f"{normalise_entity(s)}|{p.strip().lower()}"


def build_prompt(view: list[Fact], procedures: list[Procedure], user_msg: str) -> str:
    """Context for the extractor. Sorted so the same memory always renders the same prompt."""
    entities = sorted({f.s for f in view})
    facts = [f"{f.key} = {f.o}" for f in sorted(view, key=lambda f: f.key)]
    procs = [
        f"{p.trigger}: {'; '.join(json.loads(p.steps))}"
        for p in sorted(procedures, key=lambda p: (p.trigger, p.id))
    ]
    sections = [
        "Known entities (reuse one of these ids when the message refers to them): "
        + (", ".join(entities) or "none"),
        "Current facts (key = value):\n" + ("\n".join(facts) or "none"),
        "Active procedures:\n" + ("\n".join(procs) or "none"),
        "Predicates (use only these): " + ", ".join(get_args(Predicate)),
        "User message:\n" + user_msg,
    ]
    return "\n\n".join(sections)


def to_commit_request(
    extraction: Extraction,
    view: list[Fact],
    *,
    branch: str,
    agent_id: str,
    msg: str,
    episode: Episode,
) -> tuple[CommitRequest, dict[str, str]]:
    """Map an extraction onto one commit. Returns the request and a key -> fact id map for cited keys."""
    # One value per (s, p): a later duplicate overrides an earlier one, as the model's final word.
    new_by_key: dict[str, NewFact] = {}
    for f in extraction.facts:
        s = normalise_entity(f.s)
        if not s:
            continue
        new_by_key[f"{s}|{f.p}"] = NewFact(id=new_id(), s=s, p=f.p, o=f.o)
    new_ids = {k: f.id for k, f in new_by_key.items()}
    visible = {f.key: f for f in view}

    # Keys this commit sets are retired by commit_cas already, so only plain retractions are listed.
    removed_keys = sorted({k for raw in extraction.removed_keys if (k := _key(raw))})
    removed = [visible[k].id for k in removed_keys if k not in new_ids and k in visible]

    derived: list[Derivation] = []
    seen: set[tuple[str, str]] = set()
    for link in extraction.derived:
        child, parent = _key(link.child_key), _key(link.parent_key)
        if child not in new_ids or parent is None:
            continue
        parent_id = new_ids.get(parent) or (visible[parent].id if parent in visible else None)
        if parent_id is None or parent_id == new_ids[child]:  # unknown parent, or a fact derived from itself
            continue
        # commit_cas CREATEs one DERIVED_FROM edge per pair, so a repeated link must not be sent twice.
        pair = (new_ids[child], parent_id)
        if pair in seen:
            continue
        seen.add(pair)
        derived.append(Derivation(child=pair[0], parent=pair[1]))

    procedures = [
        NewProcedure(id=new_id(), trigger=p.trigger, steps=json.dumps(p.steps)) for p in extraction.procedures
    ]

    cited: dict[str, str] = {}
    for raw in extraction.cited_keys:
        k = _key(raw)
        if k is None:
            continue
        if k in new_ids:
            cited[k] = new_ids[k]
        elif k in visible:
            cited[k] = visible[k].id

    req = CommitRequest(
        branch=branch,
        agent_id=agent_id,
        msg=msg,
        facts=list(new_by_key.values()),
        removed=removed,
        procedures=procedures,
        derived=derived,
        episodes=[episode],
    )
    return req, cited
