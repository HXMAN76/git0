# Architecture

> One line: **agents get their own memory branches; FalkorDB merges what they learned by meaning, not by text, and every answer shows the commit path it came from.**

Source plan: `git-for-memory-winplan.md` (2026-10-16). This file covers what we actually build and the contracts between the four owners.

## 1. System map

```
             ┌──────────────────────── web/ (Person D) ───────────────────────┐
             │ ChatPanel │ CommitDag (xyflow+dagre) + MemoryCanvas (@falkordb/canvas) │ Scorecard │
             └──────────────┬──────────────────────────────────────▲─────────┘
                    REST (openapi-fetch)                      SSE (agent stream, scorecard)
             ┌──────────────▼──────────────────────────────────────┴─────────┐
             │ src/git0/api  FastAPI (Person D)   /api/{tenant}/...       │
             ├─────────────────────────────┬──────────────────────────────────┤
             │ agents/ + llm/ (Person B)   │ mcp/ (Person B, should-have)      │
             │ Planner, Scheduler, Notes,  │ checkout / commit_facts / log /   │
             │ Arbiter: checkout -> LLM -> │ merge / why  for Claude Code etc. │
             │ commit. NO other channel.   │                                   │
             ├─────────────────────────────┴──────────────────────────────────┤
             │ core/ (Person A)  MemoryRepo: init, branch, commit (CAS), checkout, │
             │ log, merge_base, plan_merge, apply_merge, revert, why, lookup       │
             │ every method = one query from cypher/*.cypher                       │
             └──────────────────────────────┬─────────────────────────────────┘
                                            │ falkordb (async, redis protocol)
                           ┌────────────────▼───────────────┐
                           │ FalkorDB: one graph per tenant  │  team_<id>
                           └────────────────────────────────┘
      bench/ (Person C) drives the same MemoryRepo + 2 baselines with scripted scenarios.
```

## 2. Graph model (per tenant graph `team_<id>`)

```
(:Agent {id, name, role})
(:Session {id, started_at})-[:HAS_TURN]->(:Episode {id, text, session_id, ts})
(:Branch {name})-[:HEAD]->(:Commit)
(:Commit {id, seq, msg, ts, agent_id, kind, ancestors:[ids]})-[:PARENT]->(:Commit)   // 2 parents on merge
(:Commit)-[:FROM_EPISODE]->(:Episode)
(:Agent)-[:AUTHORED]->(:Commit)
(:Fact {id, s, p, o, key: s+'|'+p, confidence, agent_id, created_at})
(:Fact)-[:ADDED_IN]->(:Commit)
(:Fact)-[:REMOVED_IN]->(:Commit)
(:Fact)-[:DERIVED_FROM]->(:Fact)   // not versioned; a restored copy inherits its original's edges
(:Procedure {trigger, steps, agent_id, confidence})-[:ADDED_IN|REMOVED_IN]->(:Commit)  // procedural memory
(:Agent)-[:READ {ts}]->(:Fact)
(:Conflict {key, status, side, ts})-[:SIDE_A|SIDE_B|BASE]->(:Fact)
(:Conflict)-[:RESOLVED_IN]->(:Commit)   // the merge commit that resolved it
(:Conflict)-[:RESOLVED_BY]->(:Precedent {key_pattern, choice, count})
(:Rule {p, strategy})          // deadline/owner: needs-review, preference: latest-wins
```

Invariants (tests enforce these; do not break them):
1. **Commits are immutable.** `ancestors` is computed once at creation, so it never goes stale.
2. **`seq` strictly increases along PARENT.** Merge commit seq = max(parent seqs) + 1. `merge_base` relies on it.
3. **Every write is ONE Cypher query** (M15). FalkorDB has no multi-query transactions. It serialises writes and runs each query atomically.
4. **Facts are never edited or deleted.** A change = `REMOVED_IN` the old fact plus `ADDED_IN` a new one. History stays complete.
5. **Agents read memory only through `checkout(branch)`** (M2). No in-process caches, no message passing between agents.
6. Fixed predicates: `deadline, owner, status, location, budget, decision, preference, depends_on, contact`.
7. **One visible value per key per branch.** A commit that adds `s|p` must `REMOVED_IN` the fact currently visible for that key. Enforced in `commit_cas`, which `REMOVED_IN`s the visible same-key fact; `CommitRequest` rejects duplicate keys within one commit. Test: `test_one_visible_value_per_key`.
8. Every agent turn is an `(:Episode)` under a `(:Session)` (`HAS_TURN`) and linked to its commit (`FROM_EPISODE`). Done in `commit_cas`.

## 3. Verified FalkorDB behaviour (tested 2026-10-16 on `falkordb/falkordb:latest`)

| Construct | Result | Consequence |
|-|-|-|
| `EXISTS { ... }` subquery | **Syntax error** | Use `OPTIONAL MATCH` + `collect` + `none()` |
| `CALL { WITH n UNWIND ... CREATE ... }` (unit subquery) | Works; outer row survives an empty list | Used for facts, removals, episodes, derivations in `commit_cas` |
| Bare `... WITH n UNWIND [] AS f CREATE ...  RETURN n.id` | **Commit lands but returns 0 rows** | Would look like a CAS failure and trigger a duplicate retry. Never use a bare UNWIND after the CAS |
| CAS with stale `$expected` | 0 rows, nothing written | The retry loop is safe |
| `list.dedup([..])`, `collect(DISTINCT x)` | Work | Use for merge-commit `ancestors` |
| `[:PARENT*0..200]` | Works | Showcase checkout + DAG view |
| `GRAPH.COPY` | Works locally | "Fork team memory" button (measure ms) |
| 20 concurrent CAS writers | 21 commits, linear seq, 0 lost | M6 baseline (`tests/core/test_repo.py`) |
| Default `TIMEOUT` | 1000 ms | Raised to 5000 in `compose.yaml`; set the same on the AWS host (`deploy/aws/compose.prod.yaml`) |
| Engine version | `latest` = graph module **4.22.1** (2026-10-14) | Pinned `falkordb/falkordb:v4.22.1` in compose + CI + AWS host |
| `CALL algo.bfs(h, 100000, 'PARENT') YIELD nodes` | Works, ~2 ms. **Excludes the start node** | Alternative to `ancestors` lists (see below) |
| Pattern predicate `WHERE NOT (n)-[:R]->()` | Works | Use instead of `EXISTS` |
| `WHERE c.id IN anc` with `anc` from a previous `WITH` | Label scan, no index | Checkout is O(facts × history) |
| Checkout / merge-base at 250 · 500 · 1000 linear commits | 17 · 40 · 103 ms / 2 · 3 · 6 ms | Fine for the demo (<200 commits per tenant) |
| `ancestors` list memory | O(N²): ~21 MB at 1000 commits, ~82 MB at 2000 (research agent, FalkorDBLite) | OK with 2 h tenant TTL on the AWS host (t3.small: 2 GB, so keep tenants small). Person A measures BFS-based checkout in P3 and switches if needed |
| `[:PARENT*0..200]` on merge diamonds | Exponential (16.7M paths / 2.4 s at 22 diamonds) | Showcase only. Never on the hot path |
| Property values | Primitives or arrays of primitives only (no maps, no nulls in arrays) | Store structured payloads (e.g. Procedure steps) as JSON strings |
| Nested pattern comprehensions | Wrong results observed | Use a second query |

## 4. Request flows

**Agent turn** (`agents/`): `checkout(branch)` → prompt with the current entity list (reuse ids) → `complete_json(Extraction)` (Groq gpt-oss-20b strict schema) → `commit(CommitRequest{facts, removed, derived, episodes})` → reply cites fact ids → UI can open the why-path.

**Merge to main** (`core/merge.py`): `merge_base` → checkout base/ours/theirs → classify by `key` → `(:Rule)` picks the strategy → conflicts get dependents and a precedent (a one-sided change is also a conflict, `reason=dependency`, when the other side derived facts from the value being replaced) → UI conflict card → human picks → `apply_merge` = one merge commit plus a saved `(:Precedent)` → Arbiter re-runs only the owners of invalidated derived facts.

**Revert cascade** (`core/revert.py`): revert C on branch B = one `kind=revert` commit on B only (other branches get it by merging B). It `REMOVED_IN`s the still-visible facts C added plus their visible `DERIVED_FROM*1..6` dependents, and re-adds fresh copies (with the original's `DERIVED_FROM` lineage) of values C replaced whose key is now empty. Reverting a merge commit undoes only that merge commit's own `ADDED_IN`/`REMOVED_IN` edges, not the facts the merge brought in.

## 5. What breaks without FalkorDB (README section, M2)

Checkout, commit (CAS), log, merge-base, conflict detection, dependents/revert cascade, why-path, "not in memory" proofs, tenant isolation and the scorecard all run as Cypher. Agents hold no state between turns. Stop the container and agents know nothing. Demo this.

## 6. Integration contracts (who depends on whom)

| Contract | Owner | Consumers | File |
|-|-|-|-|
| Pydantic models (`Fact`, `CommitRequest`, `Conflict`, `MergeResult`, `MergeApplied`, `RevertResult`, `Scorecard`) | A | B, C, D | `src/git0/core/models.py` |
| `MemoryRepo` methods | A | B, C, D | `src/git0/core/repo.py` |
| `plan_merge` / `apply_merge` | A | B (Arbiter), C, D | `src/git0/core/merge.py` |
| `complete_json` + `LLMError` | B | B (agents), C (cached bench) | `src/git0/llm/client.py` |
| `AgentSpec`, `AgentReply`, `step()` | B | D | `src/git0/agents/base.py` |
| REST + SSE endpoints (OpenAPI) | D | web | `src/git0/api/app.py` → `pnpm gen:api` |
| Scenario YAML schema + result JSON | C | README, video | `bench/` |

### REST endpoints (contract between B and D; implement in `api/app.py`)
| Method + path | Body → response | Backend | Status |
|-|-|-|-|
| `GET /api/health` | → `{ok, version, graphs}` | — | done |
| `POST /api/{t}/init` | → `{tenant, head}` | A | done |
| `POST /api/{t}/seed` | → `{created, branches, facts_on_main, facts_on_scheduler}`: launch-plan room (main, planner, scheduler) | A `seed.py` | done |
| `POST /api/{t}/branches/{name}` · `GET .../checkout` · `GET .../log` | `Fact[]` / `Commit[]` | A | done |
| `POST /api/{t}/commits` | `CommitRequest` → `{commit, retries}` | A | done |
| `GET /api/{t}/facts/{id}/why` | → why-path rows | A | done |
| `GET /api/{t}/branches/{name}/procedures` | → `Procedure[]` | A | done |
| `POST /api/{t}/agents/{agent}/messages` (SSE) | `{message, session_id}` → events `token`, `commit`, `error`, `: ping` every 15 s | B `agents.step` | P1 |
| `POST /api/{t}/merge/preview` | `{source, target}` → `MergeResult` | A `plan_merge` | done |
| `POST /api/{t}/merge/resolve` | `{source, target, choices, agent_id?, target_head?, source_head?}` → `MergeApplied` (`invalidated` = facts for the Arbiter to re-derive). Send the previewed heads back: if either branch moved since, 409 "preview again" | A `apply_merge` | done |
| `POST /api/{t}/revert` | `{branch, commit_id, agent_id?}` → `RevertResult` | A `revert` | done |
| `GET /api/{t}/graph?branch=main&limit=200&episodes=true` | → `GraphView` (`branch`, `nodes: {id, label, kind, ...}[]`, `links: {source, target, type}[]`, `truncated`); 404 unknown branch | D (canvas) + A query | done |
| `POST /api/{t}/merge/explain` | `{source, target}` → `ConflictExplanation[]` (`{key, text}`, one per conflict; one LLM call, cached) | B `arbiter.explain` | done |
| `POST /api/{t}/arbiter/rederive` | `{target, fact_ids, session_id?}` → `RederiveResult` (`replies`, `tokens` spent, `owners`, `skipped`). Send `MergeApplied.invalidated[].id` as `fact_ids` | B `arbiter.rederive` | done |
| `POST /api/{t}/agents/{agent}/kill` | → `HandoffResult` (`successor`, `branch`, `inherited: Fact[]`, `commits`, `commit_id`, `summary`). Unknown agent or branch is 404 | B `handoff` | done |
| `POST /api/{t}/load-test` | `{writers}` → `{commits, lost, retries, p50_ms, p95_ms}` | C `run_load` | P2 |
| `GET /api/{t}/scorecard` | → live Track 02 counts | A `scorecard.cypher` | done |
| `POST /api/{t}/fork` | → `{graph, ms}` (GRAPH.COPY) | A | P3 |

Any `LLMError` (provider failure, offline cache miss, tenant rate limit) comes back as **502 `{detail}`**, never 429 and never fabricated output (M12); the UI shows `detail` in a red banner. An SSE stream that has already started cannot use the 502: it sends an `error` event instead.

Rule: a change to a contract file needs a PR that tags every consumer. Stubs raise `NotImplementedError` with a pointer to the owner's doc, so consumers code against the signature and swap in the real thing when it lands.
