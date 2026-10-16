# Tech stack (decided 2026-10-16)

Versions are what `uv sync` / `pnpm install` resolved today. Full research with sources is in [`docs/research/`](research/). Decisions with trade-offs are in [`docs/adr/`](adr/).

## Backend
| Piece | Choice | Version | Why |
|-|-|-|-|
| Language | Python | 3.12 (`.python-version`) | Every FalkorDB/LLM SDK is first-class. Matches the Docker image |
| Package mgr | uv | 0.12+ | Lockfile, fast CI, `uv sync --frozen` in Docker |
| Graph DB | FalkorDB | `falkordb/falkordb:latest` | Track sponsor. Multigraph per tenant, Cypher, algorithms, GRAPH.COPY |
| DB client | `falkordb` (asyncio) | 1.8.0 | `FalkorDB.from_url`, `select_graph`, `query`/`ro_query` with params |
| API | FastAPI + uvicorn | 0.143 | Native SSE (`fastapi.sse`, ≥0.135), OpenAPI → typed TS client |
| Models | Pydantic v2 + pydantic-settings | 2.14 | Shared contracts. LLM output validation |
| LLM primary | `groq` SDK, `openai/gpt-oss-20b` | 1.7 | Strict `json_schema` structured outputs (gpt-oss only). Fast |
| LLM fallback | `google-genai`, Gemini Flash | 2.31 | Free tier, response schema. Check the model name in AI Studio |
| MCP | `mcp` SDK | 2.3 | Should-have: Membranch as memory for Claude Code/Cursor |
| Tests | pytest + pytest-asyncio | 9.1 / 1.4 | Run against a **real** FalkorDB, never mocks |
| Lint | ruff | 0.17 | Lint + format in CI |

## Frontend (`web/`)
| Piece | Choice | Why |
|-|-|-|
| Build | Vite + React + TypeScript (~5.9, pinned for openapi-typescript) | Fast dev, static build served by FastAPI |
| Styling | Tailwind CSS v4 (`@tailwindcss/vite`) | No config file |
| Commit DAG | `@xyflow/react` + `@dagrejs/dagre` | Clickable nodes, path highlight. gitgraph.js is unmaintained |
| Memory graph | `@falkordb/canvas` (web component, v0.3.x) | Same renderer as the FalkorDB Browser. Fallback: `force-graph` |
| Data | TanStack Query + `openapi-fetch` (types from `/openapi.json`) | One source of truth for the API shape |
| Realtime | SSE (`EventSource`) | One-way stream of agent replies + scorecard. Simpler than WS |
| Tests | Vitest + Testing Library | |

## Infra
| Piece | Choice | Why |
|-|-|-|
| Local DB | `compose.yaml` (podman or docker) | `make db-up` |
| Deploy | **GCP (free-trial credit)**: Cloud Run `membranch-api` (min 1 instance, asia-south1) + private FalkorDB `e2-medium` VM via Direct VPC egress. Secrets in Secret Manager. Keyless CD via Workload Identity Federation ([ADR 0005](adr/0005-deploy-gcp.md), runbook `deploy/gcp/README.md`) | Managed HTTPS URL, no cold starts, ~$20-30 of credit for the week. Railway (ADR 0004) is the fallback. FalkorDB Cloud free tier stops after 1 idle day, has no TLS, deletes after 7 days: rejected |
| Image | One Dockerfile: node stage builds `web/dist`, uv stage serves it via FastAPI `StaticFiles` | One URL, no CORS in prod |
| CD | `.github/workflows/deploy.yml`: after `ci` passes on `main` → build → Artifact Registry → new Cloud Run revision → `/api/health` smoke test | Inert until `deploy/gcp/setup.sh github` sets the repo variables |
| CI | GitHub Actions: ruff, Cypher-docs drift check, pytest with a `falkordb/falkordb` service container, web lint/typecheck/test/build | Same commands as `make check` |

## Integration optimisations (why the repo looks like this)
1. **`cypher/` is the single source of truth.** Python loads the queries by name (`core/queries.py`). `docs/CYPHER.md` is generated from them (submission requirement), and CI fails if it drifts.
2. **Contract-first.** `core/models.py` plus stub signatures let B, C and D build in parallel against A's interface from hour 0.
3. **One write = one query.** No multi-query transactions in FalkorDB, so commit/merge/revert each send one query. This also makes concurrency provable (M6).
4. **Ancestors list on each commit.** Checkout and merge-base become an `IN` filter instead of a `PARENT*` walk, which stays fast on merge-heavy DAGs. The traversal version is kept for the README and cross-checked in tests.
5. **Tests hit real FalkorDB** (local container / CI service). Each test gets a throwaway graph, so tests run in parallel and leave no state.
6. **LLM disk cache keyed by sha256.** The benchmark is reproducible offline, judging doesn't burn the Groq quota, and "tokens saved" is measurable.
7. **Per-tenant graph** (`team_<id>`) with a TTL. Isolation (M7) and the 2 h cleanup are cheap `GRAPH.DELETE`s.
8. **Single deploy unit.** FastAPI serves the SPA, so the live demo has one URL and one health check.

## Rejected
- **LiteLLM**: 1.82.7/1.82.8 were backdoored (2026-03). Adds a layer we don't need for 2 providers ([ADR 0002](adr/0002-llm-direct-sdks.md)).
- **LangGraph + FalkorDBSaver**: second state store blurs "graph is the only channel" and reads as a wrapper ([ADR 0003](adr/0003-plain-agent-loop.md)).
- **Graphiti / Mem0 / Cognee** as the memory layer: judges see a wrapper. Our original Cypher is the product.
- **`EXISTS {}` subqueries**: not supported by FalkorDB (verified).
