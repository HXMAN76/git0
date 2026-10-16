# Phases, gates and integration points

Times are **IST**. Submissions close **Oct 18 23:59 IST**. We submit by **Oct 18 20:00**. Each phase ends at a **gate**: a demo-able state on `main`, CI green, deployed. A gate that fails triggers the cut list (bottom), not an all-nighter on a nice-to-have.

```
Oct 16 ─ P0 setup ─┬─ P1 foundations ─┬── P2 hero flow ──┬─ P3 harden+prove ─┬─ P4 ship ─┐
       now   18:00 │        Oct 17 10:00 G1       Oct 17 22:00 G2       Oct 18 12:00 G3   20:00 submit
```

Every phase uses the same loop for each task: **issue → branch → test first (red) → code → `make check` → PR → buddy review → squash-merge → auto-deploy → tick the gate box.**

---

## Phase 0: Setup (Oct 16, now → 18:00)
Goal: everyone runs the stack locally, the deploy pipeline is live, contracts are understood.

| Who | Task | Done when |
|-|-|-|
| All | Clone, `make setup`, `make db-up`, `make test` | 10 core tests green on each laptop |
| All | Read `docs/ARCHITECTURE.md` §2-3 and your `docs/team/person-*.md` | Can explain CAS commit + checkout in 2 minutes (M14) |
| A | Walk the team through `cypher/commit_cas.cypher` + `checkout.cypher` | 15-min call |
| B | Get Groq + Gemini keys. Record real free-tier limits in `docs/research/02-llm.md` | Keys in each `.env`, numbers recorded |
| C | Create `bench/` skeleton (scenario schema) | `bench/README.md` merged |
| D | Railway project: FalkorDB template + api service from `main`. Hello page live | `/api/health` returns ok on the public URL |
| Lead | GitHub repo, branch protection, labels, milestones, issues from this file | Board populated |

**Gate G0:** live URL `/api/health` ok · CI green on `main` · 4 people ran tests locally.

## Phase 1: Foundations (Oct 16 18:00 → Oct 17 10:00 = Gate G1)
Goal: every layer works on its own against the real graph; one vertical slice end to end.

| Who | Task | Test that proves it |
|-|-|-|
| A | `(:Rule)` seed + `merge_commit` query (2 parents, `list.dedup` ancestors, one query) | merge commit visible in checkout of both sides; seq rule holds |
| A | `plan_merge` part 1: classify keys → auto / conflict (no dependents yet) | table test: 6 base/ours/theirs combos |
| B | `llm/client.py` (Groq strict → Gemini fallback → cache → `LLMError`) | unit test with cached fixture; one `@pytest.mark.llm` live test |
| B | Extractor prompt (fixed predicates, reuse entity ids from checkout) + `agents/base.step()` for Planner | 5 sample messages → expected triples (cached) |
| C | Scenario YAML schema, runner, baseline 1 (LWW dict) + baseline 2 (`git merge-file`) | 3 scenarios run on both baselines → JSON in `bench/results/` |
| D | API: `POST /api/{t}/agents/{id}/messages` (SSE stream), `GET /log`, `/checkout`. Web: 3-column shell, CommitDag from real `/log` | Playwright/Vitest smoke. Deployed |

**Integration point I1 (Oct 17 09:00):** B's Planner commits through A's repo, D renders the commit in the DAG. Whole team on a call, 30 min max.
**Gate G1 (winplan):** commit/checkout/merge-base working **on the deployed FalkorDB**. 1 agent message → commit → DAG node, live.

## Phase 2: Hero flow (Oct 17 10:00 → 22:00 = Gate G2)
Goal: the 60-second judge flow (M11) works end to end.

| Who | Task | Test |
|-|-|-|
| A | `plan_merge` complete: dependents both sides, precedent lookup. `apply_merge` + save Precedent. Revert cascade query | scenario "launch moved to Monday": 3 dependents found, 37 others unchanged |
| A | why-path + `fact_lookup` endpoints wired | why-path returns Fact←Commit←Agent←Episode |
| B | Scheduler + Notes agents. Derived tasks (`derived` edges). Arbiter: explains the conflict, re-invokes only owners of invalidated facts | cached run of the judge script yields the expected commits |
| B | Handoff: kill Scheduler → new agent checks out its branch, summarises `log` | test asserts the inherited facts list |
| C | 30 scenarios. 20-writer load test with p50/p95 + retries. Metrics JSON | `make bench` produces all JSON; Membranch lost = 0 |
| D | ChatPanel (SSE), ConflictCard (base/A/B + dependents + who/where), WhyPath highlight, Scorecard from live Cypher counts | manual run of the judge flow on deploy |

**Integration point I2 (Oct 17 16:00):** merge button → conflict card with real data. **I3 (21:00):** full flow rehearsal on the live URL.
**Gate G2:** full 60 s flow on the live URL, clicked by someone who didn't build it.

## Phase 3: Harden + prove (Oct 17 22:00 → Oct 18 12:00 = Gate G3)
| Who | Task |
|-|-|
| A | Perf numbers (`GRAPH.PROFILE`, p95 for checkout/merge-base/merge). Index check. Procedures (`(:Procedure)` adopted after merge). Tenant TTL cleanup |
| B | Fail-loud errors (red banner), prompt polish, MCP server (should-have), rate limit per tenant |
| C | Final benchmark run → README results table. Concurrency button backend. Blog draft (AirPods prize) |
| D | Tenant per visitor + seed data on first visit. Buttons: Kill Scheduler, 20 agents at once, Revert, Fork (GRAPH.COPY ms). Polish. Video storyboard |

**Gate G3:** every M1-M16 must-have ticked in `docs/team/README.md`. README complete. Benchmark numbers final.

## Phase 4: Ship (Oct 18 12:00 → 20:00)
| Time | What |
|-|-|
| 12:00-12:15 | 15-min walkthrough: every teammate explains model + queries (M14) |
| 12:15-14:00 | Record the 3-min video (script in the winplan §9). D drives, C narrates numbers |
| 14:00-17:00 | Fix only what the recording exposed. README final pass. `docs/CYPHER.md` regenerated. AI disclosure |
| 17:00-19:00 | Fresh-clone test: a teammate follows the README from zero. Live URL check from a phone |
| **≤ 20:00** | Submit (repo, video, live URL, Track 02 + Track 03, AI disclosure). Blog post published |

## Cut order if a gate slips
MCP server → forget/purge receipt → betweenness badge → 3rd agent (Notes) → GRAPH.COPY fork. **Never cut M1-M8.**
