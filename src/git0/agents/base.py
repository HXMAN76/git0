"""Agent loop (Person B, Phase 1). Plain async loop, no LangGraph (docs/adr/0003).

One `step` = read memory (checkout/procedures) -> one structured LLM call -> one commit.
An agent learns anything only through `MemoryRepo.checkout`; there are no caches and no agent-to-agent
messages, so everything an agent knows is on its branch and visible in `log`.
"""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from git0.agents.extract import Extraction, _key, build_prompt, to_commit_request
from git0.core.models import Episode
from git0.core.repo import MemoryRepo, new_id
from git0.llm import client
from git0.llm.client import Usage

LLMCall = Callable[..., Awaitable[tuple[BaseModel, Usage]]]


class AgentSpec(BaseModel):
    id: str  # planner | scheduler | notes | arbiter
    name: str
    role: str
    branch: str
    prompt: str


class AgentReply(BaseModel):
    agent_id: str
    text: str
    commit_id: str | None = None
    cited_fact_ids: list[str] = []
    missing_keys: list[str] = []
    usage: Usage | None = None
    branch: str = ""


async def step(
    agent: AgentSpec,
    repo: MemoryRepo,
    user_msg: str,
    session_id: str,
    *,
    tenant: str,
    llm: LLMCall | None = None,
    branch: str | None = None,
) -> AgentReply:
    """Run one turn. `branch` overrides `agent.branch` (the Arbiter works on whatever branch is asked).

    An LLM failure raises before anything is written, so a failed turn leaves no commit behind.
    """
    b = branch or agent.branch
    llm = llm or client.complete_json
    try:
        await repo.head(b)
    except KeyError:
        await repo.create_branch(b)  # agents start from team memory (main)

    view = await repo.checkout(b)
    procs = await repo.procedures(b)
    prompt = build_prompt(view, procs, user_msg)
    extraction, usage = await llm(prompt, Extraction, system=agent.prompt, tenant=tenant)

    # Always commit, even when nothing new was extracted: the episode keeps the turn in history.
    req, cited = to_commit_request(
        extraction,
        view,
        branch=b,
        agent_id=agent.id,
        msg=f"{agent.id}: {user_msg[:60]}",
        episode=Episode(id=new_id(), text=user_msg, session_id=session_id),
    )
    commit, _ = await repo.commit(req)

    # A cited key that did not resolve to a fact id is checked against the branch after the commit.
    missing: list[str] = []
    for raw in extraction.cited_keys:
        key = _key(raw)
        if key is None:
            missing.append(raw)
        elif key not in cited and not await repo.lookup(b, key) and key not in missing:
            missing.append(key)

    text = extraction.reply
    if missing:
        text += f"\n\nNot in team memory (no path from {b} HEAD): {', '.join(missing)}"

    cited_ids: list[str] = []
    for raw in extraction.cited_keys:
        fid = cited.get(_key(raw) or "")
        if fid and fid not in cited_ids:
            cited_ids.append(fid)

    return AgentReply(
        agent_id=agent.id,
        text=text,
        commit_id=commit.id,
        cited_fact_ids=cited_ids,
        missing_keys=missing,
        usage=usage,
        branch=b,
    )
