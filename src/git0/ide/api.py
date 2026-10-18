"""FastAPI routes for the Relay IDE demo, mounted at /api/ide (see git0/api/app.py)."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from git0.config import get_settings
from git0.ide.harness import AgentBusy, TurnLimitReached
from git0.ide.session import Session, SessionBusy, SessionNotFound, get_manager

router = APIRouter(prefix="/api/ide", tags=["ide"])

# The three scripted scenarios. A and B collide on shop/cart.py::calculate_total (same symbol) and
# B's gift cards call apply_tax, whose signature A changes (dependency conflict).
PRESETS: list[dict[str, str]] = [
    {
        "id": "A-regional-tax",
        "agent": "A",
        "label": "A: Regional tax",
        "title": "Regional tax",
        "text": (
            "Add region-based tax. Change `apply_tax` in shop/pricing.py to `apply_tax(amount, region)` "
            "using a `TAX_RATES` dict (US 0.08, EU 0.20, IN 0.18), and make `calculate_total` in "
            'shop/cart.py take a `region="US"` argument and pass it through.'
        ),
    },
    {
        "id": "B-free-shipping",
        "agent": "B",
        "label": "B: Free shipping",
        "title": "Free shipping",
        "text": (
            "Add shipping: in shop/cart.py change `calculate_total` to add a $5 shipping fee when the "
            "subtotal is under $50, and show the shipping line in shop/receipts.py `format_receipt`."
        ),
    },
    {
        "id": "B-gift-cards",
        "agent": "B",
        "label": "B: Gift cards",
        "title": "Gift cards",
        "text": (
            "Add gift cards: in shop/checkout.py let `checkout` accept `gift_card=0` and subtract it from "
            "the total after tax by calling `apply_tax` on the discounted amount."
        ),
    },
]


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class AnswerIn(BaseModel):
    choice: str


def _session(sid: str) -> Session:
    try:
        return get_manager().get(sid)
    except SessionNotFound as exc:
        raise HTTPException(404, "session expired") from exc


def _sse(event: dict[str, Any] | None) -> str:
    if event is None:
        return ": ping\n\n"  # comment line keeps proxies and the browser from timing the stream out
    return f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"


@router.get("/presets")
async def presets() -> list[dict[str, str]]:
    return PRESETS


@router.post("/sessions")
async def create_session() -> dict[str, Any]:
    try:
        session = await get_manager().create()
    except SessionBusy as exc:
        raise HTTPException(503, str(exc)) from exc
    except RuntimeError as exc:  # e.g. GEMINI_API_KEY missing or template not found: say so, do not hide it
        raise HTTPException(503, f"IDE demo is not configured: {exc}") from exc
    return {
        "session_id": session.id,
        "agents": get_manager().agent_info(),
        "files": session.file_list("A"),
        "presets": PRESETS,
    }


@router.get("/sessions/{sid}/events")
async def events(sid: str) -> StreamingResponse:
    session = _session(sid)

    async def stream():
        async for event in session.events():
            yield _sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions/{sid}/files")
async def files(sid: str, agent: str = Query("A", pattern="^[AB]$")) -> dict[str, str]:
    session = _session(sid)
    root = session.workspaces[agent]
    out: dict[str, str] = {}
    for rel in session.file_list(agent):
        out[rel] = (root / rel).read_bytes().decode("utf-8", "replace")
    return out


@router.get("/sessions/{sid}/graph")
async def graph(sid: str) -> dict[str, Any]:
    return await _session(sid).relay.view()


@router.post("/sessions/{sid}/agents/{agent}/messages", status_code=202)
async def send_message(sid: str, agent: str, body: MessageIn) -> dict[str, bool]:
    session = _session(sid)
    try:
        coding_agent = session.agent(agent)
    except KeyError as exc:
        raise HTTPException(404, f"unknown agent: {agent!r}") from exc
    try:
        coding_agent.send(body.text)
    except AgentBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except TurnLimitReached as exc:
        raise HTTPException(429, str(exc)) from exc
    return {"ok": True}


@router.post("/sessions/{sid}/questions/{qid}/answer")
async def answer(sid: str, qid: str, body: AnswerIn) -> dict[str, bool]:
    session = _session(sid)
    try:
        session.answer(qid, body.choice)
    except KeyError as exc:
        raise HTTPException(404, "question not pending (already answered or timed out)") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True}


@router.post("/sessions/{sid}/merge-check")
async def merge_check(sid: str) -> dict[str, Any]:
    """What plain git would say: a 3-way `git merge-file` of A's and B's files against their common ancestor
    (the template, or the version pulled on "adopt", which is what the merge base becomes after a pull)."""
    session = _session(sid)
    if shutil.which("git") is None:
        raise HTTPException(501, "git is not installed on this server: merge-check needs `git merge-file`")
    template = Path(get_settings().ide_template_dir)
    results = []
    for rel in session.file_list("A"):
        base_path = template / rel
        if rel in session.pull_base:
            base = session.pull_base[rel]
        elif base_path.is_file():
            base = base_path.read_bytes()
        else:
            continue  # a file the agent created has no base: git would call it an add/add, skip it here
        ours = (session.workspaces["A"] / rel).read_bytes()
        theirs = (
            (session.workspaces["B"] / rel).read_bytes()
            if (session.workspaces["B"] / rel).is_file()
            else base
        )
        if ours == base and theirs == base:
            continue
        merged, conflicts = await _merge_file(ours, base, theirs, rel)
        results.append(
            {
                "path": rel,
                "conflicted": conflicts > 0,
                "conflicts": conflicts,
                "merged": merged,
                "base": "pulled" if rel in session.pull_base else "template",
            }
        )
    return {"files": results}


async def _merge_file(ours: bytes, base: bytes, theirs: bytes, rel: str) -> tuple[str, int]:
    """`git merge-file -p --diff3 A base B`. Exit code = number of conflict hunks; 0 is clean."""
    with tempfile.TemporaryDirectory(prefix="git0-merge-") as tmp:
        paths = {}
        for name, data in (("a", ours), ("base", base), ("b", theirs)):
            p = Path(tmp) / name
            p.write_bytes(data)
            paths[name] = p
        proc = await asyncio.create_subprocess_exec(
            "git",
            "merge-file",
            "-p",
            "--diff3",
            "-L",
            "A",
            "-L",
            "base",
            "-L",
            "B",
            str(paths["a"]),
            str(paths["base"]),
            str(paths["b"]),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
    if (
        proc.returncode < 0 or proc.returncode >= 128
    ):  # git reports errors as 255 or negative; hunks stay small
        raise HTTPException(500, f"git merge-file failed for {rel}: {err.decode(errors='replace').strip()}")
    return out.decode("utf-8", "replace"), proc.returncode


@router.post("/sessions/{sid}/end")
async def end_session(sid: str) -> dict[str, bool]:
    # Also called by navigator.sendBeacon on page close, which sends a text/plain body we ignore.
    try:
        await get_manager().end(sid, reason="ended by visitor")
    except SessionNotFound as exc:
        raise HTTPException(404, "session expired") from exc
    return {"ok": True}
