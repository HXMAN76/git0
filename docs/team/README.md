# Team split (4 people)

Official owners (for the submission and CODEOWNERS). In practice we swap work when someone is blocked or ahead. See **Swapping work** below.

| Role | Name / GitHub | Owns (code) | Review buddy | One-line mission |
|-|-|-|-|-|
| **A: Graph core** | Hari Heman V K · [@HXMAN76](https://github.com/HXMAN76) | `cypher/`, `src/git0/core/` | B | Make every git verb one fast, correct Cypher query. The "original FalkorDB implementation" judges read |
| **B: Agents + LLM** | Roshan T · [@Git-Roshan09](https://github.com/Git-Roshan09) | `src/git0/llm/`, `agents/`, `mcp/` | A | Agents that only know what `checkout` tells them, plus a deterministic merge they can explain |
| **C: Bench + concurrency** | Raghav N · [@Rag-795](https://github.com/Rag-795) | `bench/`, `scripts/`, README results | D | Measured proof: "LWW silently lost X%, Git0 lost 0" |
| **D: UI + API + deploy** | Sai Nivedh · [@SaiNivedh26](https://github.com/SaiNivedh26) | `src/git0/api/`, `web/`, `Dockerfile`, `deploy/` | C | A judge who opens the link reaches the conflict card in 60 seconds |

"winplan §N" in these docs = [`docs/plan/WINPLAN.md`](../plan/WINPLAN.md) (judge flow §8, video script §9, benchmark §7).

Docs per person: [A](person-a-graph-core.md) · [B](person-b-agents-llm.md) · [C](person-c-bench-concurrency.md) · [D](person-d-ui-deploy.md). Shared: [ARCHITECTURE](../ARCHITECTURE.md) · [PHASES](../PHASES.md) · [GIT_WORKFLOW](../GIT_WORKFLOW.md) · [STACK](../STACK.md).

## Swapping work (we cut each other slack)
Roles are the official split, not walls. When someone is blocked, sick, or ahead:
1. **Say it in the channel** ("I'll take #13 from Roshan"), then move the issue: `gh issue edit 13 --add-assignee @me --remove-assignee Git-Roshan09`.
2. **Read the owner's `person-*.md`** for that task first. It lists the contract, the test that proves it, and the gotchas.
3. **The original owner reviews the PR.** That's how knowledge flows back. CODEOWNERS lists owner + buddy for every area, so either can approve.
4. **Contracts don't move silently.** Changing `core/models.py`, stub signatures, API routes or the scenario schema still needs every consumer tagged.
5. **M14 still applies.** Before the video, each of us can explain the graph model, the core queries and the deploy. The 12:00 walkthrough on Oct 18 is where we check that.

Natural swap pairs (overlapping context): **A↔B** (graph ↔ agents share `MemoryRepo`), **C↔D** (bench ↔ API share the load-test endpoint and README), **D↔A** for deploy (both have run `deploy/aws/setup.sh`).

## Dependency graph between people
```
A.models + repo (DONE in setup) ──► B.agents ──► D.chat UI
A.plan_merge (P1-P2) ─────────────► B.arbiter, D.conflict card, C.git0 backend
B.llm cache (P1) ─────────────────► C.reproducible bench
D.deploy (P0) ────────────────────► everyone's gate checks
```
Nobody waits: code against the contract (`core/models.py` + stub signatures). The stub raises `NotImplementedError`, so use a local fake in your tests until the real one merges.

## Must-have tracker (tick at each gate, on `main` + deployed)
| # | Must-have | Owner | P | Status |
|-|-|-|-|-|
| M1 | Semantic 3-way merge with dependents + Arbiter | A (+B) | 2 | ☐ |
| M2 | Graph is the only channel between agents | B | 1 | ☐ |
| M3 | All Track 02 focus items live on the scorecard | D (+A counts) | 2-3 | ☐ |
| M4 | Deterministic merge authority (Cypher rules, LLM explains only) | A | 2 | ☐ |
| M5 | Why-path on every answer | A + D | 2 | ☐ |
| M6 | Concurrency proof (20 writers, 0 lost, p95) | C (+A) | 2-3 | ☐ baseline test exists |
| M7 | Tenant isolation by graph | D (+A) | 3 | ☐ |
| M8 | Benchmark vs 2 baselines, JSON in repo | C | 2-3 | ☐ |
| M9 | Precedent reuse | A | 2-3 | ☐ |
| M10 | "Not in memory" no-path proof | A + B | 2 | ☐ query exists |
| M11 | Live 60 s judge flow | D | 2 | ☐ |
| M12 | Fail loudly (no canned output) | B + D | 3 | ☐ |
| M13 | Submission basics (repo, README, Cypher list, video, URL, disclosure) | C + D | 4 | ☐ |
| M14 | Everyone explains model + queries | All | 4 | ☐ |
| M15 | Every commit is one atomic Cypher query | A | 0 | ☑ `commit_cas.cypher` |
| M16 | Entity reuse + strict JSON extraction | B | 1 | ☐ |

## Rituals (short, fixed)
- **Stand-ups (10 min):** 09:00, 14:00, 21:00 IST. Each person answers: done since last, next, blocked on whom.
- **Integration points:** I1 Oct 17 09:00, I2 16:00, I3 21:00 (see PHASES). Whole team: pull `main`, `make check`, click through the deployed flow.
- **Channel:** one chat channel for the build. Post your PR link when you open it. A review takes ≤ 30 min, so ping your buddy.
- **AI assistants:** allowed and disclosed (README section). Rule M14: you must be able to explain every line you merge. When an assistant writes a query, run it and read the result before committing.
