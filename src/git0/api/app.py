"""FastAPI app (Person D owns routes/UI wiring; Person A owns the repo calls behind them)."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from git0 import __version__
from git0.config import get_settings
from git0.core.db import close_db, ensure_schema, get_db, tenant_graph
from git0.core.models import Commit, CommitRequest, Fact, Scorecard
from git0.core.repo import MemoryRepo
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


@app.post("/api/{tenant}/commits")
async def commit(tenant: str, req: CommitRequest) -> dict:
    c, retries = await (await repo_for(tenant)).commit(req)
    return {"commit": c, "retries": retries}


@app.get("/api/{tenant}/facts/{fact_id}/why")
async def why(tenant: str, fact_id: str) -> list[dict]:
    return await (await repo_for(tenant)).why(fact_id)


if WEB_DIST.is_dir():  # single deploy: FastAPI serves the built React app (mounted last)
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
