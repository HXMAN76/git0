# Membranch

**Agents get their own memory branches. FalkorDB merges what they learned by meaning, not by text, and every answer shows the commit path it came from.**

Built for **WeMakeDevs × FalkorDB Graph Hacks**: Track 02 (Agent Memory and Coordination), also entered in Track 03.

> Status: early build (Phase 0). The graph core (commit, checkout, log, merge-base, why-path) works and is tested against FalkorDB. Merge, agents, UI and benchmark are in progress (see [docs/PHASES.md](docs/PHASES.md)).

## Quickstart (3 commands)
```bash
make setup        # uv sync + pnpm install
make db-up        # FalkorDB on :6379 (browser UI on :3000), via podman or docker
make test         # core tests against the real graph
```
Then `cp .env.example .env`, add a Groq key, `make api` (http://localhost:8000/docs) and `make web` (http://localhost:5173).

## How it works
- Each agent (Planner, Scheduler, Notes) commits facts to **its own branch**. Agents read memory **only** through `checkout(branch)`. FalkorDB is the only channel between them.
- **Merge to main** runs a 3-way semantic merge: merge base vs ours vs theirs, keyed by `(subject, predicate)`. Deterministic Cypher rules decide auto-merge vs needs-review. The LLM only explains. Conflicts show their **dependent memories** on each side.
- Every commit is **one atomic compare-and-set Cypher query**, so concurrent agents never lose an update.
- Every tenant/team gets **its own graph** (`team_<id>`).

## Graph data model
See [docs/ARCHITECTURE.md §2](docs/ARCHITECTURE.md#2-graph-model-per-tenant-graph-team_id).
```
(:Branch)-[:HEAD]->(:Commit {ancestors})-[:PARENT]->(:Commit)
(:Fact {s,p,o,key})-[:ADDED_IN|REMOVED_IN]->(:Commit)<-[:AUTHORED]-(:Agent)
(:Fact)-[:DERIVED_FROM]->(:Fact)      (:Commit)-[:FROM_EPISODE]->(:Episode)
(:Conflict)-[:RESOLVED_BY]->(:Precedent)      (:Rule {p, strategy})
```

## Cypher queries the product depends on
All queries live in [`cypher/`](cypher/) and are listed with explanations in [docs/CYPHER.md](docs/CYPHER.md) (generated, CI-checked).

## What breaks without FalkorDB
Everything: checkout, commit (CAS), merge-base, conflict detection, revert cascade, why-paths, "not in memory" proofs, tenant isolation and the scorecard are Cypher queries. Agents hold no state between turns.

## Benchmark
_Coming in Phase 3: Membranch vs last-write-wins vs text-git across 30 scenarios. Results JSON in `bench/results/`._

## Repo map
| Path | What | Owner |
|-|-|-|
| `cypher/` | every query, single source of truth | A |
| `src/membranch/core/` | `MemoryRepo`, merge, models (contracts) | A |
| `src/membranch/llm/`, `agents/`, `mcp/` | LLM client, agents, MCP server | B |
| `bench/` | scenarios, baselines, load test | C |
| `src/membranch/api/`, `web/` | FastAPI + React UI | D |
| `docs/` | architecture, stack, phases, team split, git workflow, research, ADRs | all |

## Team docs
[Team split](docs/team/README.md) · [Phases & gates](docs/PHASES.md) · [Git workflow](docs/GIT_WORKFLOW.md) · [Stack](docs/STACK.md) · [Architecture](docs/ARCHITECTURE.md)

## AI assistance disclosure
We used AI coding assistants (Claude Code) for research, scaffolding and parts of the implementation. Commits with meaningful AI help carry an `Assisted-by:` trailer. Every team member reviewed, ran and can explain the graph model, the queries and the architecture.

## License
MIT
