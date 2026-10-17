"""Handoff: a successor agent takes over an agent's branch (Track 02 shared state).

Nothing is copied. The successor reads the same branch through checkout and log, and one `handoff` commit
puts the takeover into history, so the log and the scorecard show it. The summary is built without an LLM
so a handoff still works when the model provider is down.
"""

import re

from pydantic import BaseModel

from git0.agents.specs import AGENTS
from git0.core.models import Commit, CommitRequest, Episode, Fact
from git0.core.repo import MemoryRepo, new_id

SUMMARY_FACT_LINES = 10
# The suffix and the commit count need the whole history: log() alone returns only the newest 50 commits.
LOG_ALL = 100_000


class HandoffResult(BaseModel):
    successor: str
    branch: str
    inherited: list[Fact]
    commits: int
    commit_id: str
    summary: str


def _successor_id(agent_id: str, log: list[Commit]) -> str:
    """`<agent>-2` for the first takeover, then one more than the latest handoff's suffix."""
    latest = next((c for c in log if c.kind == "handoff"), None)  # log is newest first
    match = re.fullmatch(rf"{re.escape(agent_id)}-(\d+)", latest.agent_id or "") if latest else None
    return f"{agent_id}-{int(match.group(1)) + 1}" if match else f"{agent_id}-2"


def _summary(successor: str, branch: str, agent_id: str, inherited: list[Fact], commits: int) -> str:
    # Facts sorted by key and capped, so the episode stays short and the same on every run.
    head = (
        f"{successor} took over {branch} from {agent_id}: "
        f"inherited {len(inherited)} facts from {commits} commits."
    )
    lines = [f"{f.key} = {f.o}" for f in sorted(inherited, key=lambda f: f.key)[:SUMMARY_FACT_LINES]]
    return "\n".join([head, *lines])


async def handoff(repo: MemoryRepo, agent_id: str, *, session_id: str) -> HandoffResult:
    """Hand the agent's branch to its successor. Raises KeyError for an unknown agent or a missing branch."""
    spec = AGENTS.get(agent_id)
    if spec is None:
        raise KeyError(f"unknown agent: {agent_id}")
    branch = spec.branch
    await repo.head(branch)  # KeyError when the branch does not exist: nothing to inherit

    log = await repo.log(branch, limit=LOG_ALL)
    inherited = await repo.checkout(branch)
    commits = sum(1 for c in log if c.kind is not None)  # the kind-less root from init is not a commit here
    successor = _successor_id(agent_id, log)
    summary = _summary(successor, branch, agent_id, inherited, commits)

    commit, _ = await repo.commit(
        CommitRequest(
            branch=branch,
            agent_id=successor,
            msg=f"handoff: {agent_id} -> {successor}",
            kind="handoff",
            episodes=[Episode(id=new_id(), text=summary, session_id=session_id)],
        )
    )
    return HandoffResult(
        successor=successor,
        branch=branch,
        inherited=inherited,
        commits=commits,
        commit_id=commit.id,
        summary=summary,
    )
