"""Room cleanup sweep (#30) against the real FalkorDB. Each test sweeps its own graph prefix, so it never
deletes the developer's real `team_*` rooms."""

import asyncio
import uuid

import pytest

from git0.core.repo import MemoryRepo
from git0.core.rooms import sweep

TTL_S = 60


@pytest.fixture
async def rooms(db):
    """make(name, touch=True) builds a room under a throwaway prefix; everything left is deleted after."""
    prefix = f"sweeptest_{uuid.uuid4().hex[:8]}_"

    async def make(name: str, touch: bool = True) -> int:
        repo = MemoryRepo(db.select_graph(prefix + name))
        await repo.init()
        if touch:
            await repo.touch()
        seen = await repo.last_seen()
        await asyncio.sleep(0.01)  # distinct ms stamps, so "oldest first" is well defined
        return seen

    make.prefix = prefix
    yield make
    for g in await db.list_graphs():
        if g.startswith(prefix):
            await db.select_graph(g).delete()


async def alive(db, prefix: str) -> set[str]:
    return {g.removeprefix(prefix) for g in await db.list_graphs() if g.startswith(prefix)}


async def test_ttl_deletes_only_idle_rooms(db, rooms):
    await rooms("pinned")
    await rooms("legacy", touch=False)  # predates the Room node: judged by its root commit ts
    old = await rooms("old")
    await rooms("fresh")
    now = old + TTL_S * 1000 + 1  # just past the TTL for "old", inside it for "fresh"

    deleted = await sweep(db, now_ms=now, ttl_s=TTL_S, max_rooms=100, pinned=["pinned"], prefix=rooms.prefix)

    assert sorted(deleted) == [("legacy", "ttl"), ("old", "ttl")]
    assert await alive(db, rooms.prefix) == {"pinned", "fresh"}


async def test_cap_evicts_least_recently_seen_first(db, rooms):
    for name in ["pinned", "r1", "r2", "r3", "r4"]:
        now = await rooms(name)
    # Touch r1 again: it is now the most recently seen, so r2 and r3 go first.
    await MemoryRepo(db.select_graph(rooms.prefix + "r1")).touch()

    deleted = await sweep(db, now_ms=now, ttl_s=TTL_S, max_rooms=3, pinned=["pinned"], prefix=rooms.prefix)

    assert deleted == [("r2", "cap"), ("r3", "cap")]  # pinned is oldest but still counts toward the cap
    assert await alive(db, rooms.prefix) == {"pinned", "r4", "r1"}


async def test_cap_only_sweep_ignores_ttl(db, rooms):
    seen = await rooms("idle")
    far_future = seen + 10 * TTL_S * 1000

    assert await sweep(db, now_ms=far_future, ttl_s=None, max_rooms=1, pinned=[], prefix=rooms.prefix) == []
    assert await sweep(db, now_ms=far_future, ttl_s=None, max_rooms=0, pinned=[], prefix=rooms.prefix) == [
        ("idle", "cap")
    ]


async def test_pinned_rooms_survive_ttl_and_cap(db, rooms):
    seen = await rooms("demo")
    far_future = seen + 10 * TTL_S * 1000

    deleted = await sweep(
        db, now_ms=far_future, ttl_s=TTL_S, max_rooms=0, pinned=["demo"], prefix=rooms.prefix
    )

    assert deleted == []
    assert await alive(db, rooms.prefix) == {"demo"}


async def test_sweep_without_rooms_is_a_noop(db, rooms):
    assert await sweep(db, now_ms=0, ttl_s=TTL_S, max_rooms=0, pinned=[], prefix=rooms.prefix) == []


async def test_touch_keeps_one_room_node_and_created_at(repo):
    first = await repo.touch()
    await asyncio.sleep(0.01)
    second = await repo.touch()

    res = await repo.graph.ro_query("MATCH (r:Room) RETURN r.created_at, r.last_seen")
    assert len(res.result_set) == 1
    created_at, last_seen = res.result_set[0]
    assert created_at == first and last_seen == second > first
