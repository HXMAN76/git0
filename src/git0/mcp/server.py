"""MCP server that exposes git0/membranch as tools for agents (DeepSeek Harness, Claude, etc.).

Run:
    python -m git0.mcp.server          # stdio transport (default, for MCP clients)
    python -m git0.mcp.server --sse    # SSE transport on port 8001

Bidirectional context flow:
  Agent A (analyser) calls commit_facts / agent_message  →  FalkorDB tenant branch
  Agent B (reasoner) calls checkout / log / graph_view   ←  same FalkorDB tenant

Any number of agents can share one tenant; branches track whose knowledge is whose.
"""

import asyncio
import json
import logging

from mcp.server.mcpserver import MCPServer as FastMCP

from git0.agents.base import step
from git0.agents.specs import AGENTS
from git0.config import get_settings
from git0.core.db import ensure_schema, get_db, tenant_graph
from git0.core.merge import apply_merge, plan_merge
from git0.core.models import CommitRequest
from git0.core.repo import MemoryRepo, new_id
from git0.llm import client as llm_client
from git0.seed import seed

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "git0-membranch",
    instructions=(
        "Tools for the Membranch multi-agent memory system. "
        "Each tenant is an isolated project (e.g. the repo name). "
        "Agents write structured facts to their own branch; use merge_* to reconcile. "
        "Use agent_message for a full LLM-backed turn; use commit_facts to store raw extractions."
    ),
)


# ── helpers ──────────────────────────────────────────────────────────────────


async def _repo(tenant: str) -> MemoryRepo:
    try:
        graph = tenant_graph(tenant)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return MemoryRepo(graph)


async def _ensure(tenant: str) -> MemoryRepo:
    repo = await _repo(tenant)
    await ensure_schema(repo.graph)
    return repo


# ── read tools ───────────────────────────────────────────────────────────────


@mcp.tool()
async def checkout(tenant: str, branch: str = "main") -> list[dict]:
    """
    Return all facts currently on a branch as a list of {key, s, p, o, id} dicts.
    Use this to read the shared memory state before reasoning over a task.

    - tenant: project identifier (e.g. "myrepo" or "demo")
    - branch: "main", an agent branch like "planner", or any other branch name
    """
    repo = await _repo(tenant)
    facts = await repo.checkout(branch)
    return [f.model_dump() for f in facts]


@mcp.tool()
async def log(tenant: str, branch: str = "main", limit: int = 20) -> list[dict]:
    """
    Return the commit history for a branch (newest first).
    Poll this to detect when another agent has committed new knowledge.

    Each entry has: id, kind, agent_id, message, timestamp_ms, fact_count.
    """
    repo = await _repo(tenant)
    commits = await repo.log(branch, limit)
    return [c.model_dump() for c in commits]


@mcp.tool()
async def graph_view(
    tenant: str,
    branch: str = "main",
    limit: int = 200,
) -> dict:
    """
    Return the full knowledge graph for a branch as {nodes, edges, episodes}.
    Useful for understanding relationships between facts across agents.
    """
    repo = await _repo(tenant)
    view = await repo.graph_view(branch, limit, True)
    return view.model_dump()


@mcp.tool()
async def why(tenant: str, fact_id: str) -> list[dict]:
    """
    Explain why a fact exists: returns the chain of commits and derivations.
    fact_id is the 'id' field from a checkout() result.
    """
    repo = await _repo(tenant)
    return await repo.why(fact_id)


@mcp.tool()
async def scorecard(tenant: str) -> dict:
    """Return high-level metrics: commits, merges, handoffs, conflicts resolved."""
    repo = await _repo(tenant)
    card = await repo.scorecard()
    prefix = get_settings().tenant_graph_prefix
    card.tenants = sum(1 for g in await get_db().list_graphs() if g.startswith(prefix))
    return card.model_dump()


# ── write tools ──────────────────────────────────────────────────────────────


@mcp.tool()
async def seed_tenant(tenant: str) -> dict:
    """
    Seed a tenant with the default demo data (Planner / Scheduler / Notes agents).
    Call this once before using a new tenant. Safe to call again (idempotent per branch).
    """
    repo = await _repo(tenant)
    if repo.graph.name not in await get_db().list_graphs():
        summary = await seed(repo)
        await ensure_schema(repo.graph)
        await repo.touch()
        return {"seeded": True, **summary}
    await repo.touch()
    return {"seeded": False, "note": "tenant already exists"}


@mcp.tool()
async def commit_facts(
    tenant: str,
    branch: str,
    agent_id: str,
    message: str,
    facts: list[dict],
    removed_keys: list[str] | None = None,
) -> dict:
    """
    Directly commit a set of extracted facts to a branch without an LLM call.
    Use this when YOUR reasoning has already produced structured facts.

    Each fact dict must have: s (subject), p (predicate), o (object).
    Optionally: id (stable key like "launch|deadline"), deps (list of parent fact ids).

    Returns {commit_id, branch, fact_count}.
    """
    from git0.core.models import NewFact

    repo = await _repo(tenant)
    # Auto-create branch if it doesn't exist yet
    try:
        await repo.head(branch)
    except KeyError:
        await repo.create_branch(branch, from_branch="main")
    # Auto-assign id if caller omitted it (stable key = "s|p|o" so two facts
    # with the same subject+predicate but different objects don't collide)
    fact_inputs = [
        NewFact(id=f.get("id") or f"{f['s']}|{f['p']}|{f['o']}", **{k: v for k, v in f.items() if k != "id"})
        for f in facts
    ]
    req = CommitRequest(
        branch=branch,
        agent_id=agent_id,
        msg=message,
        facts=fact_inputs,
        removed=removed_keys or [],
    )
    commit, _retries = await repo.commit(req)
    await repo.touch()
    return {
        "commit_id": commit.id,
        "branch": branch,
        "fact_count": len(facts),
    }


@mcp.tool()
async def agent_message(
    tenant: str,
    agent_id: str,
    text: str,
    session_id: str | None = None,
) -> str:
    """
    Run one full agent turn: the agent reads its branch memory, calls the LLM,
    extracts facts, commits them, and returns its reply text.

    agent_id must be one of: planner, scheduler, notes.
    Returns a JSON string: {text, commit_id, branch, cited_fact_ids, usage, error?}.

    This uses the same LLM as the web UI. For raw fact commits without LLM, use commit_facts.
    """
    spec = AGENTS.get(agent_id)
    if spec is None:
        raise ValueError(f"unknown agent: {agent_id!r}. Available: {list(AGENTS)}")

    repo = await _repo(tenant)
    sid = session_id or new_id()

    try:
        reply = await step(spec, repo, text, sid, tenant=tenant, llm=llm_client.complete_json)
        await repo.touch()
        return json.dumps(
            {
                "text": reply.text,
                "commit_id": reply.commit_id,
                "branch": reply.branch,
                "agent_id": reply.agent_id,
                "cited_fact_ids": reply.cited_fact_ids,
                "usage": reply.usage.model_dump() if reply.usage else None,
            }
        )
    except Exception as exc:
        return json.dumps({"error": str(exc), "agent_id": agent_id})


# ── merge tools ──────────────────────────────────────────────────────────────


@mcp.tool()
async def merge_preview(tenant: str, source: str, target: str) -> dict:
    """
    Preview what merging source branch into target would look like.
    Returns {conflicts: [...], fast_forward, source_head, target_head}.
    Use this before merge_resolve to understand what needs human/agent decisions.
    """
    repo = await _repo(tenant)
    try:
        plan = await plan_merge(repo, source, target)
    except (ValueError, KeyError) as exc:
        raise ValueError(str(exc.args[0])) from exc
    await repo.touch()
    return plan.model_dump()


@mcp.tool()
async def merge_resolve(
    tenant: str,
    source: str,
    target: str,
    choices: dict[str, str],
    agent_id: str = "agent",
) -> dict:
    """
    Apply a merge resolution. choices maps conflict key → chosen fact id (or "DELETE").
    Get conflict keys and fact ids from merge_preview first.
    Returns {merged_facts, invalidated, source_head, target_head}.
    """
    repo = await _repo(tenant)
    try:
        plan = await plan_merge(repo, source, target)
        applied = await apply_merge(repo, plan, choices, agent_id)
    except (ValueError, KeyError) as exc:
        raise ValueError(str(exc.args[0])) from exc
    await repo.touch()
    return applied.model_dump()


@mcp.tool()
async def list_agents(tenant: str | None = None) -> dict:
    """
    List available agent IDs and their roles.
    Pass tenant to also see which branches exist in that project.
    """
    agents = {aid: {"prompt_preview": spec.prompt[:120] + "..."} for aid, spec in AGENTS.items()}
    result: dict = {"agents": agents}
    if tenant:
        try:
            repo = await _repo(tenant)
            graphs = await get_db().list_graphs()
            result["tenant_exists"] = repo.graph.name in graphs
        except Exception:
            result["tenant_exists"] = False
    return result


# ── context subscription (polling helper) ────────────────────────────────────


@mcp.tool()
async def watch_branch(
    tenant: str,
    branch: str = "main",
    since_commit_id: str | None = None,
    timeout_s: float = 30.0,
) -> dict:
    """
    Poll a branch until a new commit appears after since_commit_id (or immediately
    if there are already newer commits). Returns {new_commits: [...], head}.

    Use this to receive context pushed by another agent on the same project:
      1. Call checkout() to get current state.
      2. Note the head commit id from log().
      3. Call watch_branch(since_commit_id=<head>) — returns when new facts arrive.
      4. Call checkout() again to read the updated state.

    timeout_s: max seconds to wait before returning (returns empty list on timeout).
    """
    repo = await _repo(tenant)
    deadline = asyncio.get_event_loop().time() + timeout_s

    while True:
        commits = await repo.log(branch, 50)
        if commits:
            head = commits[0].id
            if since_commit_id is None:
                return {"new_commits": [c.model_dump() for c in commits[:1]], "head": head}
            new = []
            for c in commits:
                if c.id == since_commit_id:
                    break
                new.append(c.model_dump())
            if new:
                return {"new_commits": new, "head": head}

        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            head = commits[0].id if commits else None
            return {"new_commits": [], "head": head}
        await asyncio.sleep(min(2.0, remaining))


# ── entrypoint ───────────────────────────────────────────────────────────────


def main() -> None:
    import sys

    if "--sse" in sys.argv:
        port = 8001
        if "--port" in sys.argv:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        mcp.run(transport="sse", port=port)
    elif "--http" in sys.argv:
        import asyncio
        import uvicorn
        from starlette.middleware.cors import CORSMiddleware

        port = 8001
        if "--port" in sys.argv:
            port = int(sys.argv[sys.argv.index("--port") + 1])

        # Wrap with CORS so the browser DAG viewer can reach localhost:8002
        app = mcp.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["mcp-session-id"],
        )
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
