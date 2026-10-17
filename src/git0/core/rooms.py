"""Room cleanup (#30): every visitor gets a tenant graph, so the 2 GiB host needs rooms to go away again.

Deterministic, no LLM: a room is deleted when it has been idle longer than the TTL ("ttl"), or, while there
are more rooms than `max_rooms`, when it is among the least recently seen ("cap", LRU). Pinned rooms (the
shared demo link) are never deleted but still count toward the cap, since they use memory too.
"""

import asyncio
import logging

from falkordb.asyncio import FalkorDB

from git0.config import get_settings
from git0.core.repo import MemoryRepo

log = logging.getLogger(__name__)


async def sweep(
    db: FalkorDB,
    *,
    now_ms: int,
    ttl_s: int | None,
    max_rooms: int,
    pinned: list[str],
    prefix: str | None = None,
) -> list[tuple[str, str]]:
    """Delete idle and over-cap rooms. Returns [(tenant, reason)] in deletion order.

    `ttl_s=None` skips the TTL pass (the cap-only sweep before seeding a new room).
    `prefix` defaults to TENANT_GRAPH_PREFIX; tests pass their own so they never touch real rooms.
    """
    prefix = prefix if prefix is not None else get_settings().tenant_graph_prefix
    tenants = [g.removeprefix(prefix) for g in await db.list_graphs() if g.startswith(prefix)]
    candidates = [t for t in tenants if t not in pinned]
    stamps = await asyncio.gather(*(MemoryRepo(db.select_graph(prefix + t)).last_seen() for t in candidates))
    seen = {t: ts or 0 for t, ts in zip(candidates, stamps, strict=True)}  # empty graph = oldest possible

    doomed: dict[str, str] = {}
    if ttl_s is not None:
        doomed |= {t: "ttl" for t, ts in seen.items() if now_ms - ts > ttl_s * 1000}
    survivors = sorted((t for t in seen if t not in doomed), key=seen.__getitem__)  # oldest first
    excess = len(tenants) - len(doomed) - max_rooms
    doomed |= {t: "cap" for t in survivors[: max(excess, 0)]}

    for tenant, reason in doomed.items():
        await db.select_graph(prefix + tenant).delete()
        idle_min = (now_ms - seen[tenant]) // 60_000
        log.info("room deleted tenant=%s idle_minutes=%d reason=%s", tenant, idle_min, reason)
    return list(doomed.items())
