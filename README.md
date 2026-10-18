# Git0

**Agents get their own memory branches. FalkorDB merges what they learned by meaning, not by text, and every answer shows the commit path it came from.**

Built for **WeMakeDevs × FalkorDB Graph Hacks**: Track 02 (Agent Memory and Coordination), also entered in Track 03.

**Live demo: https://15-252-11-70.sslip.io/ide/** (Git0 Relay IDE, two AI agents on two laptops) and https://15-252-11-70.sslip.io/ (memory-branch team room).

## Git0 Relay: merge conflicts caught before they happen
Two developers clone the same repo and each work with an AI coding agent. Every tool call the agents make passes
**PreToolUse / PostToolUse hooks** that talk to the **git0 MCP server** (`/mcp`, streamable HTTP). The server keeps
one shared **code-context graph in FalkorDB**: files, functions, who calls what (`CALLS`), and every change an agent
made (`Change`) or plans to make (`Intent`).

- **PostToolUse** (after a write): `code_record_edit` parses the file and records which symbols changed and whether
  a signature changed.
- **PreToolUse** (before a write): `code_check_edit` runs graph queries against the peer's unseen changes:
  same function (`same_symbol`), calling a function whose signature the peer changed (`dependency`), changing a
  function the peer's new code calls through `CALLS*1..3` (`reverse_dependency`), and announced intents (`intent`).
  A blocking hit **denies the write** and the human chooses: pull the peer's change and rework on top, keep mine,
  or pause.
- **PreToolUse** (before a read): `code_peer_activity` injects heads-ups about teammate changes into the agent's context.

The demo IDE (`/ide/`) runs two open-source **pydantic-ai** agents on Gemini (`gemini-3.1-flash-lite`), each in its
own clone. Every visitor gets a fresh copy of `demo_project/` and a private graph `ide_<session>`; both are deleted
on "End session", on tab close, after 15 min idle, and on server restart. Spec: [docs/plans/2026-10-18-ide-demo.md](docs/plans/2026-10-18-ide-demo.md).
Code: `src/git0/code/` (parser + relay), `cypher/code_*.cypher`, `src/git0/ide/` (sessions, harness, hooks, API),
`web/src/ide/` (UI). Connect your own harness (Claude Code, Gemini CLI, Cursor) to the same MCP tools: see [mcp.md](mcp.md).

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
_Coming in Phase 3: Git0 vs last-write-wins vs text-git across 30 scenarios. Results JSON in `bench/results/`._

## Repo map
| Path | What | Owner |
|-|-|-|
| `cypher/` | every query, single source of truth | A |
| `src/git0/core/` | `MemoryRepo`, merge, models (contracts) | A |
| `src/git0/llm/`, `agents/`, `mcp/` | LLM client, agents, MCP server | B |
| `bench/` | scenarios, baselines, load test | C |
| `src/git0/api/`, `web/` | FastAPI + React UI | D |
| `docs/` | architecture, stack, phases, team split, git workflow, research, ADRs | all |

## Team
Hari Heman V K (graph core) · Roshan T (agents + LLM) · Raghav N (benchmark) · Sai Nivedh (UI, API, deploy)

## Team docs
[Team split](docs/team/README.md) · [Phases & gates](docs/PHASES.md) · [Git workflow](docs/GIT_WORKFLOW.md) · [Stack](docs/STACK.md) · [Architecture](docs/ARCHITECTURE.md)

## AI assistance disclosure
We used AI coding assistants (Claude Code) for research, scaffolding and parts of the implementation. Commits with meaningful AI help carry an `Assisted-by:` trailer. Every team member reviewed, ran and can explain the graph model, the queries and the architecture.

## License
MIT
