import os
import uuid

import pytest
from falkordb.asyncio import FalkorDB

from git0.core.db import ensure_schema
from git0.core.repo import MemoryRepo

FALKORDB_URL = os.environ.get("FALKORDB_URL", "redis://localhost:6379")


@pytest.fixture(scope="session")
async def db():
    client = FalkorDB.from_url(FALKORDB_URL)
    try:
        await client.list_graphs()
    except Exception as exc:  # fail loudly: tests need a real FalkorDB (make db-up)
        pytest.exit(f"FalkorDB not reachable at {FALKORDB_URL}: {exc}", returncode=2)
    yield client
    await client.aclose()


@pytest.fixture
async def repo(db):
    """Fresh tenant graph per test, deleted afterwards."""
    graph = db.select_graph(f"test_{uuid.uuid4().hex[:8]}")
    r = MemoryRepo(graph)
    await r.init()
    await ensure_schema(graph)
    yield r
    await graph.delete()
