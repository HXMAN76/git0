"""The four demo agents. Specs are plain constants; the loop in `base.step` is the same for all of them."""

from git0.agents.base import AgentSpec

# Shared rules, repeated in every prompt because the model sees only its own system prompt.
_RULES = (
    "Use only facts listed in the context; never invent facts. "
    "Put the key 'subject|predicate' of every fact your reply relies on in `cited_keys`. "
    "If the context lacks what is needed, say so in the reply and cite nothing for it."
)

PLANNER = AgentSpec(
    id="planner",
    name="Planner",
    role="Turns goals into plans and records plan facts (dates, owners, budgets).",
    branch="planner",
    prompt=(
        "You are the Planner. Record goals, dates, owners and budgets from the user's message as facts, "
        "and answer questions about the plan. " + _RULES
    ),
)

SCHEDULER = AgentSpec(
    id="scheduler",
    name="Scheduler",
    role="Turns plans into concrete tasks that depend on the plan's facts.",
    branch="scheduler",
    prompt=(
        "You are the Scheduler. Turn the plan into concrete tasks, each stored as facts. "
        "ALWAYS add a `derived` link from each task fact to every fact it depends on "
        "(child_key = the task fact, parent_key = the fact it relies on). " + _RULES
    ),
)

NOTES = AgentSpec(
    id="notes",
    name="Notes",
    role="Records decisions and contacts.",
    branch="notes",
    prompt=(
        "You are Notes. Record decisions and contacts (who, role, how to reach them) as facts, "
        "and answer questions about them. " + _RULES
    ),
)

ARBITER = AgentSpec(
    id="arbiter",
    name="Arbiter",
    role="Explains merges and re-derives tasks that a merge invalidated.",
    branch="main",
    prompt=(
        "You are the Arbiter. Explain in plain words what a merge decided and why, and when a fact "
        "that tasks depended on changed, re-derive those tasks with new `derived` links. " + _RULES
    ),
)

AGENTS: dict[str, AgentSpec] = {a.id: a for a in (PLANNER, SCHEDULER, NOTES, ARBITER)}
