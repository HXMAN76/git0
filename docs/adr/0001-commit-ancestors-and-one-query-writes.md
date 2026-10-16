# ADR 0001: Commit `ancestors` list + one-query writes

**Status:** accepted 2026-10-16 · **Owner:** Person A

## Context
Checkout and merge-base need "all ancestors of HEAD". A `PARENT*0..200` walk explodes on merge-heavy DAGs (many paths to the same node). FalkorDB serialises writes and has no multi-query transactions.

## Decision
- Each `Commit` stores `ancestors: [ids]`, computed once at creation (`h.ancestors + [h.id]`; merges: `list.dedup(a.ancestors + b.ancestors + [a.id, b.id])`). Commits are immutable, so the list never goes stale.
- Every write (commit, merge, revert, purge) is one Cypher query: CAS on HEAD, then `CALL { WITH n UNWIND ... }` unit subqueries for facts, removals, episodes and derivations.
- Keep `PARENT` edges for the DAG view, why-paths and one showcase traversal (`cypher/checkout_traversal.cypher`).

## Consequences
- Checkout measured at 17 / 40 / 103 ms for 250 / 500 / 1000 commits. Merge-base 2-6 ms. The `IN` on a WITH-bound list doesn't use the index, so cost is O(facts × history).
- Memory is O(N²) in history length (~21 MB per 1000-commit tenant). Acceptable with the 2 h tenant TTL and demo histories under 200 commits.
- **Escape hatch (P3, Person A):** `CALL algo.bfs(h, 100000, 'PARENT') YIELD nodes` (start node excluded, so add `h`) gives the ancestor set in ~ms without stored lists. Switch checkout to it if the bench shows memory or latency trouble. Keep `ancestors` for merge-base (8 ms vs ~200 ms with BFS, per research).
- A bare `UNWIND` after the CAS is forbidden: an empty list drops the row, a successful commit looks like a CAS miss, and the retry duplicates it. Verified on FalkorDB, covered by `test_empty_commit_is_not_reported_as_cas_failure`.
