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
             │ src/membranch/api  FastAPI (Person D)   /api/{tenant}/...       │
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
(:Commit {id, seq, msg, ts, agent_id, ancestors:[ids]})-[:PARENT]->(:Commit)   // 2 parents on merge
(:Commit)-[:FROM_EPISODE]->(:Episode)
(:Agent)-[:AUTHORED]->(:Commit)
(:Fact {id, s, p, o, key: s+'|'+p, confidence, agent_id, created_at})
(:Fact)-[:ADDED_IN]->(:Commit)
(:Fact)-[:REMOVED_IN]->(:Commit)
(:Fact)-[:DERIVED_FROM]->(:Fact)
(:Procedure {trigger, steps, agent_id, confidence})-[:ADDED_IN]->(:Commit)      // procedural memory
(:Agent)-[:READ {ts}]->(:Fact)
(:Conflict {key, status})-[:SIDE_A|SIDE_B|BASE]->(:Fact)
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

**Merge to main** (`core/merge.py`): `merge_base` → checkout base/ours/theirs → classify by `key` → `(:Rule)` picks the strategy → conflicts get dependents and a precedent → UI conflict card → human picks → `apply_merge` = one merge commit plus a saved `(:Precedent)` → Arbiter re-runs only the owners of invalidated derived facts.

**Revert cascade**: revert commit C = new commit that `REMOVED_IN` the facts C added, plus every fact reached by `DERIVED_FROM*1..6` from them, on the branch (and on branches that merged C).

## 5. What breaks without FalkorDB (README section, M2)

Checkout, commit (CAS), log, merge-base, conflict detection, dependents/revert cascade, why-path, "not in memory" proofs, tenant isolation and the scorecard all run as Cypher. Agents hold no state between turns. Stop the container and agents know nothing. Demo this.

## 6. Integration contracts (who depends on whom)

| Contract | Owner | Consumers | File |
|-|-|-|-|
| Pydantic models (`Fact`, `CommitRequest`, `Conflict`, `MergeResult`) | A | B, C, D | `src/membranch/core/models.py` |
| `MemoryRepo` methods | A | B, C, D | `src/membranch/core/repo.py` |
| `plan_merge` / `apply_merge` | A | B (Arbiter), C, D | `src/membranch/core/merge.py` |
| `complete_json` + `LLMError` | B | B (agents), C (cached bench) | `src/membranch/llm/client.py` |
| `AgentSpec`, `AgentReply`, `step()` | B | D | `src/membranch/agents/base.py` |
| REST + SSE endpoints (OpenAPI) | D | web | `src/membranch/api/app.py` → `pnpm gen:api` |
| Scenario YAML schema + result JSON | C | README, video | `bench/` |

Rule: a change to a contract file needs a PR that tags every consumer. Stubs raise `NotImplementedError` with a pointer to the owner's doc, so consumers code against the signature and swap in the real thing when it lands.
