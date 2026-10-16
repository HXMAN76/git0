"""FalkorDB connection + per-tenant graph handles (M7: one graph per team)."""

import re

from falkordb.asyncio import FalkorDB
from falkordb.asyncio.graph import AsyncGraph

from membranch.config import get_settings

_TENANT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_db: FalkorDB | None = None


def get_db() -> FalkorDB:
    global _db
    if _db is None:
        _db = FalkorDB.from_url(get_settings().falkordb_url)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.aclose()
        _db = None


def tenant_graph(tenant: str, db: FalkorDB | None = None) -> AsyncGraph:
    if not _TENANT_RE.match(tenant):
        raise ValueError(f"invalid tenant id: {tenant!r}")
    return (db or get_db()).select_graph(get_settings().tenant_graph_prefix + tenant)


async def ensure_schema(graph: AsyncGraph) -> None:
    """Range indexes from the perf guardrails. Re-running is safe: existing indexes are skipped."""
    wanted = [("Commit", "id"), ("Branch", "name"), ("Fact", "id"), ("Fact", "key"), ("Agent", "id")]
    existing = {(row[0], tuple(row[1])) for row in (await graph.list_indices()).result_set}
    for label, prop in wanted:
        if (label, (prop,)) not in existing:
            await graph.create_node_range_index(label, prop)
