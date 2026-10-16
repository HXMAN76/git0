"""Agent loop (Person B, Phase 1). Plain async loop, no LangGraph (docs/adr/0003).

async def step(agent: AgentSpec, repo: MemoryRepo, user_msg: str, session_id: str) -> AgentReply:
    facts = await repo.checkout(agent.branch)             # the ONLY way an agent learns anything
    extraction = await complete_json(render(facts, user_msg), Extraction, system=agent.prompt, ...)
    commit, _ = await repo.commit(CommitRequest(branch=agent.branch, agent_id=agent.id, ...,
                                                episodes=[Episode(text=user_msg, ...)]))
    return AgentReply(text=..., commit_id=commit.id, cited_fact_ids=[...])  # cited ids -> why-path
"""

from pydantic import BaseModel


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
