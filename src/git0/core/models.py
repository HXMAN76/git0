"""Shared contracts. Every team member codes against these types; change them only via PR + team ping."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

# Fixed predicate list keeps LLM extraction reliable (winplan section 5).
Predicate = Literal[
    "deadline",
    "owner",
    "status",
    "location",
    "budget",
    "decision",
    "preference",
    "depends_on",
    "contact",
]


class NewFact(BaseModel):
    """A fact an agent wants to add. ids are assigned client-side so DERIVED_FROM can reference them."""

    id: str
    s: str = Field(description="subject entity id, lowercase, reused from checkout when possible")
    p: Predicate
    o: str
    confidence: float = 1.0


class Fact(BaseModel):
    id: str
    s: str
    p: str
    o: str
    key: str
    confidence: float | None = None
    agent_id: str | None = None
    created_at: int | None = None  # ms; latest-wins compares it


class NewProcedure(BaseModel):
    """Procedural memory: a learned workflow, versioned on branches like facts."""

    id: str
    trigger: str = Field(description="when this applies, e.g. 'launch date moves'")
    steps: str = Field(description="JSON-encoded list of steps (FalkorDB properties can't hold maps)")
    confidence: float = 1.0


class Procedure(BaseModel):
    id: str
    trigger: str
    steps: str
    confidence: float | None = None
    agent_id: str | None = None


class Episode(BaseModel):
    """One chat turn or tool call that produced a commit (episodic memory)."""

    id: str
    text: str
    session_id: str


class Derivation(BaseModel):
    child: str
    parent: str


class CommitRequest(BaseModel):
    branch: str
    agent_id: str
    msg: str
    facts: list[NewFact] = []
    removed: list[str] = []
    procedures: list[NewProcedure] = []
    removed_procedures: list[str] = []
    derived: list[Derivation] = []
    episodes: list[Episode] = []
    kind: Literal["commit", "merge", "revert", "handoff", "seed"] = "commit"

    @model_validator(mode="after")
    def _one_fact_per_key(self):
        # commit_cas retires the old value per key; two new values for one key would both stay visible.
        keys = [(f.s, f.p) for f in self.facts]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate (s, p) in facts: one value per key per commit")
        return self


class Commit(BaseModel):
    id: str
    seq: int
    msg: str | None = None
    agent_id: str | None = None
    ts: int | None = None
    kind: str | None = None
    added: int = 0
    removed: int = 0


class MergeStrategy(StrEnum):
    AUTO = "auto"  # non-colliding change, merged without asking
    LATEST_WINS = "latest-wins"
    NEEDS_REVIEW = "needs-review"  # human picks; LLM only explains


class Conflict(BaseModel):
    key: str
    base: Fact | None
    ours: Fact | None
    theirs: Fact | None
    strategy: MergeStrategy
    dependents_ours: list[Fact] = []
    dependents_theirs: list[Fact] = []
    precedent: str | None = None
    precedent_choice: str | None = None
    precedent_count: int = 0


class MergeResult(BaseModel):
    source: str
    target: str
    base_commit: str
    target_head: str
    source_head: str
    removals: list[str] = []  # fact ids the merge commit removes for auto-resolved keys
    unchanged: int = 0  # keys identical on base, target and source
    auto_merged: list[Fact] = []
    conflicts: list[Conflict] = []
    merge_commit: str | None = None  # None while conflicts await review
