"""FastAPI app (Person D owns routes/UI wiring; Person A owns the repo calls behind them)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from redis.exceptions import ResponseError

from git0 import __version__
from git0.agents.arbiter import ConflictExplanation, RederiveResult, explain, rederive
from git0.agents.base import AgentReply, LLMCall, step
from git0.agents.handoff import HandoffResult, handoff
from git0.agents.specs import AGENTS
from git0.config import get_settings
from git0.core.db import close_db, ensure_schema, get_db, tenant_graph
from git0.core.merge import apply_merge, plan_merge
from git0.core.models import (
    Commit,
    CommitRequest,
    Fact,
    GraphView,
    MergeApplied,
    MergeResult,
    Procedure,
    RevertResult,
    Scorecard,
)
from git0.core.repo import CommitConflictError, MemoryRepo, new_id
from git0.core.revert import revert
from git0.llm import client as llm_client
from git0.llm.client import LLMError
from git0.seed import seed

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_db()


app = FastAPI(title="Git0", version=__version__, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(CommitConflictError)
async def commit_conflict_handler(_: Request, exc: CommitConflictError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(LLMError)
async def llm_error_handler(_: Request, exc: LLMError) -> JSONResponse:
    # Bad gateway: the model provider failed, not this API. The UI shows `detail` in a red banner (M12).
    return JSONResponse({"detail": str(exc)}, status_code=502)


@app.exception_handler(ResponseError)
async def graph_error_handler(request: Request, exc: ResponseError) -> JSONResponse:
    # FalkorDB says this when a read hits a tenant graph that was never created (no init/seed yet).
    if "Invalid graph operation on empty key" in str(exc):
        tenant = request.path_params.get("tenant", "<tenant>")
        detail = f"tenant not initialised: POST /api/{tenant}/init or /api/{tenant}/seed first"
        return JSONResponse({"detail": detail}, status_code=404)
    raise exc  # anything else is a real DB failure: fail loudly (500)


def get_llm() -> LLMCall:
    """The structured-output LLM call routes use. A FastAPI dependency so tests swap in a fake with
    `app.dependency_overrides[get_llm]`. Looked up at call time so patching the client module also works."""
    return llm_client.complete_json


async def repo_for(tenant: str) -> MemoryRepo:
    try:
        graph = tenant_graph(tenant)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return MemoryRepo(graph)


@app.get("/api/health")
async def health() -> dict:
    graphs = await get_db().list_graphs()  # fail loudly if FalkorDB is down (M2: no graph, no product)
    return {"ok": True, "version": __version__, "graphs": len(graphs)}


@app.post("/api/{tenant}/init")
async def init_tenant(tenant: str) -> dict:
    repo = await repo_for(tenant)
    await repo.init()
    await ensure_schema(repo.graph)
    return {"tenant": tenant, "head": await repo.head("main")}


_seed_locks: dict[str, asyncio.Lock] = {}


@app.post("/api/{tenant}/seed")
async def seed_tenant(tenant: str) -> dict:
    repo = await repo_for(tenant)
    # One seed per tenant at a time: concurrent seeds race on the same branch and commit steps.
    async with _seed_locks.setdefault(tenant, asyncio.Lock()):
        try:
            summary = await seed(repo)  # seed() creates the graph, so indexes come after it
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        await ensure_schema(repo.graph)
    return summary


@app.post("/api/{tenant}/branches/{name}")
async def create_branch(tenant: str, name: str, from_branch: str = "main") -> dict:
    repo = await repo_for(tenant)
    try:
        return {"branch": name, "head": await repo.create_branch(name, from_branch)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/{tenant}/branches/{name}/checkout")
async def checkout(tenant: str, name: str) -> list[Fact]:
    return await (await repo_for(tenant)).checkout(name)


@app.get("/api/{tenant}/branches/{name}/log")
async def log(tenant: str, name: str, limit: int = 50) -> list[Commit]:
    return await (await repo_for(tenant)).log(name, limit)


@app.get("/api/{tenant}/graph")
async def graph_view(
    tenant: str,
    branch: str = "main",
    limit: int = Query(200, ge=1, le=1000),  # facts; the canvas gets sluggish past ~1000 nodes
    episodes: bool = True,
) -> GraphView:
    """Live memory graph for the UI canvas. FalkorDB is private on the server, so this is the only way in."""
    try:
        return await (await repo_for(tenant)).graph_view(branch, limit, episodes)
    except KeyError as exc:  # unknown branch
        raise HTTPException(404, str(exc.args[0])) from exc


@app.get("/api/{tenant}/scorecard")
async def scorecard(tenant: str) -> Scorecard:
    card = await (await repo_for(tenant)).scorecard()
    prefix = get_settings().tenant_graph_prefix
    card.tenants = sum(1 for g in await get_db().list_graphs() if g.startswith(prefix))
    return card


@app.get("/api/{tenant}/branches/{name}/procedures")
async def procedures(tenant: str, name: str) -> list[Procedure]:
    return await (await repo_for(tenant)).procedures(name)


class MergeRequest(BaseModel):
    source: str
    target: str


class ResolveRequest(MergeRequest):
    choices: dict[str, str]  # conflict key -> chosen fact id (or DELETE)
    agent_id: str = "human"
    # The heads the human previewed (MergeResult.target_head/source_head). When sent, a branch that moved
    # since then is a 409 instead of silently merging commits nobody looked at.
    target_head: str | None = None
    source_head: str | None = None


class RederiveRequest(BaseModel):
    target: str
    fact_ids: list[str]  # MergeApplied.invalidated ids
    session_id: str = "arbiter"


class RevertRequest(BaseModel):
    branch: str
    commit_id: str
    agent_id: str = "human"


@app.post("/api/{tenant}/merge/preview")
async def merge_preview(tenant: str, req: MergeRequest) -> MergeResult:
    try:
        return await plan_merge(await repo_for(tenant), req.source, req.target)
    except (ValueError, KeyError) as exc:  # KeyError = unknown branch from repo.head
        raise HTTPException(400, str(exc.args[0])) from exc


@app.post("/api/{tenant}/merge/explain")
async def merge_explain(
    tenant: str, req: MergeRequest, llm: Annotated[LLMCall, Depends(get_llm)]
) -> list[ConflictExplanation]:
    try:
        plan = await plan_merge(await repo_for(tenant), req.source, req.target)
    except (ValueError, KeyError) as exc:  # KeyError = unknown branch from repo.head
        raise HTTPException(400, str(exc.args[0])) from exc
    return await explain(plan, tenant=tenant, llm=llm)


@app.post("/api/{tenant}/arbiter/rederive")
async def arbiter_rederive(
    tenant: str, req: RederiveRequest, llm: Annotated[LLMCall, Depends(get_llm)]
) -> RederiveResult:
    repo = await repo_for(tenant)
    try:
        await repo.head(req.target)  # unknown branch is a client error, not a silent new branch
    except KeyError as exc:
        raise HTTPException(400, str(exc.args[0])) from exc
    facts = await repo.facts_by_ids(req.fact_ids)
    return await rederive(repo, facts, target=req.target, tenant=tenant, session_id=req.session_id, llm=llm)


@app.post("/api/{tenant}/merge/resolve")
async def merge_resolve(tenant: str, req: ResolveRequest) -> MergeApplied:
    repo = await repo_for(tenant)
    try:
        # Re-plan so choices are checked against the heads as they are now, not a stale preview.
        plan = await plan_merge(repo, req.source, req.target)
        previewed = (req.target_head or plan.target_head, req.source_head or plan.source_head)
        if previewed != (plan.target_head, plan.source_head):
            raise HTTPException(409, "branch moved since preview; preview again")
        return await apply_merge(repo, plan, req.choices, req.agent_id)
    except (ValueError, KeyError) as exc:  # KeyError = unknown branch from repo.head
        raise HTTPException(400, str(exc.args[0])) from exc


@app.post("/api/{tenant}/revert")
async def revert_commit(tenant: str, req: RevertRequest) -> RevertResult:
    try:
        return await revert(await repo_for(tenant), req.branch, req.commit_id, req.agent_id)
    except (ValueError, KeyError) as exc:  # KeyError = unknown branch from repo.head
        raise HTTPException(400, str(exc.args[0])) from exc


class MessageRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = Field(default_factory=new_id)  # the UI keeps one per chat tab so turns group together


@app.post("/api/{tenant}/agents/{agent_id}/messages")
async def agent_message(
    tenant: str, agent_id: str, req: MessageRequest, llm: Annotated[LLMCall, Depends(get_llm)]
) -> AgentReply:
    """One chat turn: the agent reads its branch, makes one LLM call and commits. Plain JSON for now;
    SSE token streaming is issue #10. An LLM failure raises before any write and comes back as 502."""
    agent = AGENTS.get(agent_id)
    if agent is None:
        raise HTTPException(404, f"unknown agent {agent_id!r}; one of {sorted(AGENTS)}")
    repo = await repo_for(tenant)
    return await step(agent, repo, req.message, req.session_id, tenant=tenant, llm=llm)


@app.post("/api/{tenant}/agents/{agent_id}/kill")
async def kill_agent(tenant: str, agent_id: str) -> HandoffResult:
    """Hand the agent's branch to its successor (agent-2, agent-3, ...). Unknown agent or branch is 404."""
    try:
        return await handoff(await repo_for(tenant), agent_id, session_id=new_id())
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc


@app.post("/api/{tenant}/commits")
async def commit(tenant: str, req: CommitRequest) -> dict:
    c, retries = await (await repo_for(tenant)).commit(req)
    return {"commit": c, "retries": retries}


@app.get("/api/{tenant}/facts/{fact_id}/why")
async def why(tenant: str, fact_id: str) -> list[dict]:
    return await (await repo_for(tenant)).why(fact_id)


if WEB_DIST.is_dir():  # single deploy: FastAPI serves the built React app (mounted last)
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
