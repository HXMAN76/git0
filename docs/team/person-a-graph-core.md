# Person A: Graph core (Cypher)

**You own:** `cypher/*.cypher`, `src/membranch/core/`, `tests/core/`. **Buddy reviewer:** B.
**Your output is what judges call "the original FalkorDB implementation".** Every query must be explainable, measured and listed in `docs/CYPHER.md`.

## Already done in setup (read and own it)
- `init_repo`, `create_branch`, `commit_cas`, `checkout`, `checkout_traversal`, `log`, `merge_base`, `dependents`, `why_path`, `fact_lookup`
- `MemoryRepo` with CAS retry and exponential backoff. `ensure_schema` range indexes
- 9 core tests, including 20 concurrent writers with 0 lost commits
- Verified FalkorDB gotchas: `docs/ARCHITECTURE.md` §3 (no `EXISTS {}`, no bare `UNWIND` after CAS)

## How to add a query
1. Write `cypher/<name>.cypher` with `// name: <name>` and a comment that says why it exists
2. Try it raw: `redis-cli GRAPH.QUERY scratch "<query>"` or the browser UI at http://localhost:3000
3. Add a `MemoryRepo` method (one query per method; writes go through `query`, reads through `ro_query`)
4. Add a test in `tests/core/`, then `make cypher-docs` (CI fails if `docs/CYPHER.md` is stale)

## Phase 1 (→ Oct 17 10:00)
- [ ] `cypher/seed_rules.cypher`: `(:Rule {p, strategy})` for each predicate (deadline/owner/budget/decision = needs-review, preference/status = latest-wins, rest = needs-review)
- [ ] `cypher/merge_commit.cypher`: CAS on the **target** HEAD, `PARENT` to both heads, `ancestors = list.dedup(ha.ancestors + hb.ancestors + [ha.id, hb.id])`, `seq = max + 1`, plus `CALL {}` blocks for chosen facts / removals. **One query.**
- [ ] `plan_merge` part 1 in `core/merge.py`: three checkouts → dicts by `key` → classify. Table-driven test with 6 combos (one side changed / both same / both different / added on one side / removed on one side / removed vs changed)
- [ ] Deploy check (gate G1): on the live HTTPS URL, `POST /api/g1/init`, `POST /api/g1/commits`, `GET .../checkout` and `/log` return the right data (tests aren't shipped in the image, so check through the API)

## Phase 2 (→ Oct 17 22:00)
- [ ] `plan_merge` complete: dependents on both sides (`dependents.cypher`), `Rule` → strategy, precedent lookup (`MATCH (pr:Precedent {key_pattern:$p}) RETURN pr ORDER BY pr.count DESC LIMIT 1`)
- [ ] `apply_merge(choices)`: merge commit + `(:Conflict)-[:RESOLVED_BY]->(:Precedent)` with count increment (`MERGE` + `ON MATCH SET`)
- [ ] `revert(commit_id)`: one query that removes the facts the commit added **plus** their `DERIVED_FROM*1..6` dependents visible on the branch. Return the list for the UI ("3 reverted, 37 unchanged")
- [ ] Scorecard counts query (`cypher/scorecard.cypher`): episodes, facts on main, precedents reused, sessions, handoffs, commits, tenants. All live, no hard-coding (M3)

## Phase 3 (→ Oct 18 12:00)
- [ ] `GRAPH.PROFILE` each hot query. Record p50/p95 at 100/500/1000 commits in `docs/research/01-falkordb.md`
- [ ] Compare `algo.bfs` checkout vs `ancestors` checkout (time + `GRAPH.MEMORY USAGE`) on a merge-heavy history. Switch checkout if BFS wins (ADR 0001 escape hatch)
- [ ] `(:Procedure)` nodes: commit, merge, and `procedures(branch)` checkout
- [ ] Tenant TTL: `created_at` on root commit, cleanup task `GRAPH.DELETE` for graphs older than `TENANT_TTL_SECONDS`
- [ ] Optional: `algo.betweenness` "load-bearing memory" badge. `GRAPH.COPY` fork with measured ms
- [ ] README "Graph data model" + "What breaks without FalkorDB"

## Explain-it test (M14)
You can answer without notes: why `ancestors` instead of `PARENT*`? Why is 0 rows from `commit_cas` safe to retry? Why must the commit be one query? How does merge-base pick the LCA? What does `none(x IN rs WHERE x IN anc)` do?
