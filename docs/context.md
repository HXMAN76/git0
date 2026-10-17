# Person D — Implementation Context & Demo Guide

**Issues:** #10 (SSE route + 3-column shell + CommitDag) · #15 (ChatPanel, ConflictCard, WhyPath, Scorecard)

---

## What Was Built

### Backend

#### SSE Agent Messages Route (`src/git0/api/app.py`)
`POST /api/{tenant}/agents/{agent_id}/messages`

Streams agent replies as Server-Sent Events:
- `event: token` — full reply text
- `event: commit` — `commit_id`, `cited_fact_ids`, `branch`
- `event: error` — surfaced error message (never silent)

Uses `StreamingResponse(media_type="text/event-stream")` with `X-Accel-Buffering: no` to prevent Caddy buffering.

#### Gemini Fallback Chain (`src/git0/config.py`, `src/git0/llm/client.py`)
Primary model: `gemini-3.6-flash`. On 503/overload, retries in order:
1. `gemini-3.8-flash`
2. `gemini-3.5-flash-lite`
3. `gemini-3.1-flash-lite`
4. `gemini-2.5-flash-lite`

First success wins. Only raises `LLMError` if all five fail simultaneously.

#### Agent Update Rule (`src/git0/agents/specs.py`)
Added to `_RULES` shared across all agents: when asked to UPDATE or CHANGE an existing fact, the agent must add the new value to `facts` AND put the old key in `removed_keys` so the old value is retracted. Without this, agents answered update requests conversationally without writing to the graph.

---

### Frontend

#### ChatPanel (`web/src/components/ChatPanel.tsx`)
Three agent tabs: Planner / Scheduler / Notes. All kept mounted so history is preserved when switching.

SSE via `fetch` + `ReadableStream` (not `EventSource` — that's GET-only):
- Manually parses SSE buffer split on `\n\n`
- `event: token` → streaming text bubble with animate-pulse placeholder
- `event: commit` → cited fact "why?" buttons (one per `cited_fact_id`)
- `event: error` → red error bubble

`onFactClick(factId)` lifts fact IDs to App for WhyPath + MemoryCanvas highlight.
`onAgentChange(agentId)` tells App which branch is active (drives ConflictCard source).

#### CommitDag (`web/src/components/CommitDag.tsx`)
Fetches `/branches/{name}/log` for planner / scheduler / notes / main every 4s. Infers parent edges from `seq` ordering within each branch (the API `Commit` schema has no explicit `parents` field). Uses `@dagrejs/dagre` with `rankdir: TB` for layout. Branch color coding: planner=purple, scheduler=blue, notes=green, main=pink.

#### ConflictCard (`web/src/components/ConflictCard.tsx`)
"Merge `{branch}` → main" button at the bottom of the left column. Flow:

1. `POST /api/{tenant}/merge/preview` → inspect conflicts
2. **No conflicts** → calls `POST /api/{tenant}/merge/resolve` immediately with `choices: {}` → green success with commit ID and auto-merged count
3. **Conflicts exist** → renders each conflict with `subject · predicate: object` for base/ours/theirs, precedent chip, dependent counts, radio picks
4. "Resolve & merge" → `POST /api/{tenant}/merge/resolve` with chosen fact IDs

Branch label updates when user switches agent tabs.

#### WhyPath (`web/src/components/WhyPath.tsx`)
On "why?" click: calls `GET /api/{tenant}/facts/{fact_id}/why`. The route returns provenance rows with `fact_id`, `commit_id`, `agent_id`, `episode_id`. All four are graph node IDs — WhyPath collects them all and passes to App's `highlight` state. MemoryCanvas dims everything not in the set.

#### Scorecard (`web/src/components/Scorecard.tsx`)
Polls `GET /api/{tenant}/scorecard` every 3s. Maps 7 Track 02 counters: facts on main, episodes, procedures, sessions resumed, handoffs, total commits, tenants live.

---

## Demo Flow (Full Pipeline)

### Setup
```bash
# Terminal 1 — FalkorDB
docker run -p 6380:6379 falkordb/falkordb

# Terminal 2 — API (from git0/)
set -a && source .env && set +a
uv run uvicorn git0.api.app:app --reload --port 8000

# Terminal 3 — Frontend (from git0/web/)
pnpm run dev
```
Open `http://localhost:5173`. The seed endpoint runs automatically on first room visit.

---

### Demo 1: Basic Fact Query + Why-Path

1. **Planner tab** → type: `What tasks are currently in progress?`
2. Agent streams a reply citing facts from FalkorDB memory
3. Click any **"why?"** button on the response
4. Center panel switches to **Memory graph** — 4 nodes light up: the fact, the commit that wrote it, the agent, and the episode (chat turn) that triggered it
5. This is the provenance chain — every answer is auditable back to the exact commit

---

### Demo 2: 3-Way Semantic Conflict

1. **Planner tab** → type: `Update the launch deadline to Monday`
   - Agent writes `launch|deadline = monday` to planner branch, retracts old value
2. Click **"Merge planner → main"** → auto-merges, scorecard Facts on main increments
3. **Scheduler tab** → type: `Update the launch deadline to Thursday`
   - Agent writes `launch|deadline = thursday` to scheduler branch
4. Click **"Merge scheduler → main"**
5. **ConflictCard appears** with:
   - base: `friday` (common ancestor)
   - main: `monday` (from planner merge)
   - scheduler: `thursday` (new value)
6. Pick a side → "Resolve & merge" → new merge commit appears in CommitDag

This is the core thesis: concurrent agents diverge, the graph detects it, a human resolves it with full dependency context.

---

### Demo 3: Auto-Merge (No Human Needed)

1. **Scheduler tab** → type: `Record that the venue is now booked for Friday`
2. Agent commits a new fact to scheduler branch
3. Click **"Merge scheduler → main"**
4. Since main doesn't have this key yet → **auto-merged**, green card shows commit ID and fact count
5. CommitDag updates within 4s showing the new merge commit on main

---

## Architecture Notes

- Agents hold **zero state between turns** — every checkout, commit and merge is a Cypher query against FalkorDB
- `cited_fact_ids` in the SSE `commit` event are real FalkorDB fact IDs — the "why?" buttons are a direct proof that the answer came from a specific graph node, not hallucinated
- Tenant isolation: each browser visitor gets `team_<random>` graph; share the room via `?team=<id>` URL param
- The merge ConflictCard shows `dependents_ours` / `dependents_theirs` counts — if you pick one side, those downstream facts cascade-update automatically (implemented in `apply_merge`)
