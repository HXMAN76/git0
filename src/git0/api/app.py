"""FastAPI app (Person D owns routes/UI wiring; Person A owns the repo calls behind them)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from redis.exceptions import ResponseError

from git0 import __version__
from git0.agents.handoff import HandoffResult, handoff
from git0.config import get_settings
from git0.core.db import close_db, ensure_schema, get_db, tenant_graph
from git0.core.merge import apply_merge, plan_merge
from git0.core.models import (
    Commit,
    CommitRequest,
    Fact,
    MergeApplied,
    MergeResult,
    Procedure,
    RevertResult,
    Scorecard,
)
from git0.core.repo import CommitConflictError, MemoryRepo, new_id
from git0.core.revert import revert
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


@app.exception_handler(ResponseError)
async def graph_error_handler(_: Request, exc: ResponseError) -> JSONResponse:
    # FalkorDB says this when a read hits a tenant graph that was never created (no init/seed yet).
    if "Invalid graph operation on empty key" in str(exc):
        detail = "tenant not initialised: POST /api/{tenant}/init or /seed first"
        return JSONResponse({"detail": detail}, status_code=404)
    raise exc  # anything else is a real DB failure: fail loudly (500)


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
