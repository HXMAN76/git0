# Person D: API + UI + deploy + video

**You own:** `src/membranch/api/`, `web/`, `Dockerfile`, `deploy/gcp/`, the demo video. **Buddy reviewer:** C.
**Your output is the 60-second judge flow (M11).** Deploy on day 1, not at the end.

## Read first
`docs/research/03-frontend.md` (versions, canvas API, SSE), `docs/research/07-aws-deploy.md` + `deploy/aws/README.md` (AWS runbook), ADR 0006, winplan §8 (judge flow) and §9 (video).

## Phase 0 (→ Oct 16 18:00)
- [ ] With whoever has the AWS credentials: run the `deploy/aws/setup.sh` steps from `deploy/aws/README.md`
- [ ] `/api/health` ok on the `cloudfront.net` URL (proves CloudFront → EC2 → FalkorDB with password)
- [ ] SSE check: `curl -N` shows events streaming one by one through CloudFront. **Every SSE endpoint sends a `: ping` comment every 15 s** (CloudFront cuts an origin that's silent for 60 s)
- [ ] Push a trivial PR to `main` → `deploy` workflow goes green → new revision live

## Phase 1 (→ Oct 17 10:00)
- [ ] API: `POST /api/{tenant}/agents/{agent_id}/messages` streaming SSE events (`token`, `commit`, `error`). Use FastAPI native SSE
- [ ] `pnpm gen:api` after every API change. Web uses `openapi-fetch` types only (no hand-written fetch shapes)
- [ ] Web: 3-column shell. CommitDag fed by `/log` of each branch (xyflow + dagre). Branch colours per agent

## Phase 2 (→ Oct 17 22:00)
- [ ] ChatPanel: one tab per agent (Planner, Scheduler, Notes), SSE streaming, cited facts clickable
- [ ] **Merge to main** button → `plan_merge` → ConflictCard: base / Planner value / Scheduler value, dependents on each side, author + source chat turn, Arbiter explanation, "resolved same way N times" precedent chip → pick → `apply_merge` → "3 re-derived, 37 unchanged"
- [ ] WhyPath: click an answer → why-path lit on MemoryCanvas (`@falkordb/canvas`) + query ms
- [ ] Scorecard: polls/streams A's `scorecard` query. Each Track 02 item with a live number (M3)
- [ ] No git jargon in the UI: "Planner and Scheduler disagree", not "merge conflict on HEAD"

## Phase 3 (→ Oct 18 12:00)
- [ ] Tenant per visitor: first visit → `team_<random>` → init + seed the launch-plan story. TTL 2 h (M7). Show the cross-tenant query returning nothing
- [ ] Buttons: Kill Scheduler (handoff), 20 agents at once (C's `run_load`), Revert commit (A's cascade), Fork memory (GRAPH.COPY, show measured ms), Restart server (session-resume proof)
- [ ] Error states: any `LLMError`/API error shows a red banner with the real message (M12)
- [ ] Mobile/phone check of the live URL

## Phase 4
- [ ] Record the 3-min video by 14:00 (script: winplan §9). Upload. Put the link in the README
- [ ] Submit by 20:00: repo, video, live URL, Tracks 02 + 03, AI disclosure

## Explain-it test (M14)
How does a request reach FalkorDB? Why SSE? Where does each scorecard number come from (which query)? What does the tenant id map to?
