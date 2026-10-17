"""Arbiter (Person B, Phase 2): explains merge conflicts and re-derives what a merge invalidated.

Neither function decides anything (CLAUDE.md rule 5): `explain` only words what `plan_merge` already
computed, and `rederive` only asks the owning agents to re-plan facts the human's choice removed.
"""

import re

from pydantic import BaseModel

from git0.agents.base import AgentReply, LLMCall, step
from git0.agents.specs import AGENTS
from git0.core.models import Conflict, Fact, MergeResult
from git0.core.repo import MemoryRepo
from git0.llm import client
from git0.llm.client import LLMError

SYSTEM = (
    "You are the Arbiter. For each conflict, write one or two plain sentences saying who disagrees, "
    "about what, and what each choice would leave stale. Plain words only: no git terms such as "
    "merge, branch, commit or HEAD. Use the agent names given. Never invent facts."
)


class ConflictExplanation(BaseModel):
    key: str
    text: str


class Explanations(BaseModel):
    """LLM output schema: one entry per conflict key."""

    items: list[ConflictExplanation]


class RederiveResult(BaseModel):
    replies: list[AgentReply]
    tokens: int
    owners: list[str]
    skipped: list[str] = []  # owners with no spec in AGENTS (e.g. a human): nothing to re-run


def _side(label: str, f: Fact | None, dependents: list[Fact]) -> str:
    if f is None:
        return f"{label}: removed"
    line = f"{label}: {f.o!r} (by {f.agent_id or 'unknown'})"
    if dependents:
        line += "; facts relying on it: " + ", ".join(f"{d.s}|{d.p}={d.o}" for d in dependents)
    return line


def _describe(c: Conflict) -> str:
    lines = [
        f"key: {c.key}",
        f"reason: {c.reason}",
        f"base: {c.base.o!r}" if c.base else "base: none",
        _side("ours (target)", c.ours, c.dependents_ours),
        _side("theirs (source)", c.theirs, c.dependents_theirs),
    ]
    if c.precedent:
        lines.append(f"precedent: {c.precedent}")
    return "\n".join(lines)


async def explain(plan: MergeResult, *, tenant: str, llm: LLMCall | None = None) -> list[ConflictExplanation]:
    """One LLM call for all conflicts. A conflict the model skipped raises: no fabricated text."""
    if not plan.conflicts:
        return []
    llm = llm or client.complete_json
    prompt = "Explain each conflict. Return one item per key, using the key exactly as given.\n\n" + (
        "\n\n".join(_describe(c) for c in plan.conflicts)
    )
    out, _ = await llm(prompt, Explanations, system=SYSTEM, tenant=tenant)
    by_key = {e.key: e for e in out.items}
    missing = [c.key for c in plan.conflicts if c.key not in by_key]
    if missing:
        raise LLMError(f"explanation missing for conflict keys: {', '.join(missing)}")
    return [by_key[c.key] for c in plan.conflicts]  # extra keys the model added are dropped


def _owner_spec_id(agent_id: str | None) -> str | None:
    """`planner-2` (a handoff successor) -> `planner`; None when no agent spec matches."""
    base = re.sub(r"-\d+$", "", agent_id or "")
    return base if base in AGENTS else None


async def rederive(
    repo: MemoryRepo,
    invalidated: list[Fact],
    *,
    target: str,
    tenant: str,
    session_id: str,
    llm: LLMCall | None = None,
) -> RederiveResult:
    """Ask each owner of an invalidated fact, once, to re-plan those facts against `target`'s facts now."""
    groups: dict[str, list[Fact]] = {}
    for f in invalidated:
        groups.setdefault(f.agent_id or "", []).append(f)

    replies: list[AgentReply] = []
    owners: list[str] = []
    skipped: list[str] = []
    for owner, facts in groups.items():
        spec_id = _owner_spec_id(owner)
        if spec_id is None:
            skipped.append(owner)
            continue
        lines = "\n".join(f"- {f.s}|{f.p} = {f.o}" for f in sorted(facts, key=lambda f: f.key))
        msg = (
            f"A merge changed facts these depended on, so they were removed from {target}:\n{lines}\n"
            "Re-plan them against the current facts, adding derived links to the facts they now rely on."
        )
        replies.append(
            await step(AGENTS[spec_id], repo, msg, session_id, tenant=tenant, llm=llm, branch=target)
        )
        owners.append(owner)
    tokens = sum(r.usage.prompt_tokens + r.usage.completion_tokens for r in replies if r.usage)
    return RederiveResult(replies=replies, tokens=tokens, owners=owners, skipped=skipped)
