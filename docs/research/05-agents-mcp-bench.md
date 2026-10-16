# 05 - Agent layer, MCP server, concurrency test, benchmark harness, prior art

Research date: 2026-10-16. Versions below are from PyPI JSON endpoints fetched on this date unless marked otherwise.
Items marked **(unverified)** were not confirmed against primary docs in this pass.

## Version snapshot

| Package | Latest | Uploaded | Python | Notes |
|---|---|---|---|---|
| mcp (official Python SDK) | 2.3.0 | 2026-10-02 | >=3.10 | deps: pydantic>=2.12, starlette, uvicorn |
| langgraph | 1.2.15 | 2026-10-12 | >=3.10 | deps: langchain-core, langgraph-checkpoint, langgraph-prebuilt, langgraph-sdk, pydantic, xxhash |
| langchain-falkordb | 0.2.0 | 2026-07-06 | >=3.10,<4 | optional `[langgraph]` extra; pins falkordb<2, langgraph<2 |
| falkordb (Python client) | 1.8.0 | 2026-10-14 | >=3.10 | ships `falkordb.asyncio` |
| locust | 2.46.7 | not confirmed | >=3.11 | |
| pytest | 9.1.1 | not confirmed | >=3.10 | |
| pytest-asyncio | 1.4.0 | 2026-05-26 | >=3.10 | |
| pytest-benchmark | 5.3.0 | 2026-08-23 | >=3.10 | |
| pydantic | 2.16.0 | 2026-10-14 | >=3.11 | |
| pydantic-settings | 2.14.1 | ~2026-10-11 | >=3.10 (inferred) | version from GitHub changelog, not PyPI JSON |
| fastapi | 0.143.2 | not confirmed | >=3.10 | |
| ruff | 0.17.1 | not confirmed | >=3.7 | |
| uv | 0.13.1 | not confirmed | >=3.8 | |
| agmem | 0.3.0 | 2026-02-02 | - | MIT |

Conflict noted: a second page summary gave pydantic-settings as 2.14.1 and pydantic as 2.16.0. Both were taken from PyPI/changelog pages; re-check with `uv lock` before pinning.

---

## 1. Agent orchestration: LangGraph vs plain async loop

**Recommendation: plain async Python loop. Do not use LangGraph for the 3-day build.**

Reasoning:

- **The graph must be the only channel between agents.** LangGraph's value is state, reducers and checkpointing. `FalkorDBSaver` (`from langchain_falkordb.checkpoint import FalkorDBSaver`, install `pip install langchain-falkordb[langgraph]`) persists LangGraph thread state in FalkorDB. That creates a second state store next to the memory graph. Judges asking "where does agent B learn what agent A knew?" get a murky answer: the checkpointer also carries it. The plain loop keeps one channel: `checkout(branch)` in, `commit_facts` out.
- **Judge risk: "framework wrapper".** A LangGraph graph whose nodes just call an LLM and then call Git0 reads as a wrapper around an LLM call. The novelty is the memory VCS; the orchestration should look thin and obvious.
- **Build cost.** LangGraph 1.2.15 brings langchain-core, langgraph-prebuilt, langgraph-sdk and checkpoint packages. Each new abstraction is a debugging surface during a hackathon.
- **What LangGraph would buy us** (parallel fan-out, interrupts, human-in-the-loop) is not on the critical path. `asyncio.gather` covers fan-out.

Per-agent step = system prompt + rendered `checkout(branch)` view + one LLM call with a `commit_facts` tool schema + commit. Pseudo-code is in the Recommendation section.

Sources: https://pypi.org/project/langgraph/ ; https://pypi.org/project/langchain-falkordb/ ; https://github.com/FalkorDB/langchain-falkordb

---

## 2. MCP server in Python (FastMCP / MCPServer) and FastAPI mount

Key facts for SDK v2 (mcp 2.3.0, released 2026-10-02):

- v1 `from mcp.server.fastmcp import FastMCP` now raises `ModuleNotFoundError`. Use `from mcp.server.mcpserver import MCPServer, Context`.
- Transport options moved from the constructor to methods. HTTP app: `mcp.streamable_http_app(json_response=True, ...)`. SSE: `sse_app()`.
- **Lifespan is mandatory when mounting.** The host app must enter `mcp.session_manager.run()` inside its lifespan, otherwise requests fail with `RuntimeError: Task group is not initialized`. `mcp.session_manager` only exists after `streamable_http_app()` has been called, so build the app at module level.
- `transport_security` is a `TransportSecuritySettings` passed to the app/run method, not the constructor. When omitted and the host is localhost/127.0.0.1/::1, DNS-rebinding protection turns on and requests without a port in `Host` get `421 Invalid Host header`. Set `allowed_hosts` explicitly.
- `streamablehttp_client` was removed; use `streamable_http_client`.
- Caution: standalone `fastmcp` (gofastmcp.com, 3.x) has a different API (`from fastmcp import FastMCP`, `mcp.http_app()`). Do not mix the two.

Minimal server (tool bodies call the same service layer as REST; no raw Cypher exposed):

```python
# git0/mcp_server.py
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("git0")


@mcp.tool()
async def checkout(branch: str) -> dict:
    """Return the rendered memory view of a branch. The ONLY read path for agents."""
    return await service.checkout(branch)


@mcp.tool()
async def commit_facts(branch: str, facts: list[dict], parent_hash: str) -> dict:
    return await service.commit(branch, facts, parent_hash)


@mcp.tool()
async def log(branch: str, limit: int = 20) -> list[dict]:
    return await service.log(branch, limit)


@mcp.tool()
async def merge(source: str, target: str) -> dict:
    """3-way semantic merge of source into target; returns merge commit + conflicts."""
    return await service.merge(source, target)


@mcp.tool()
async def why(branch: str, fact_id: str) -> dict:
    """Provenance: which commit/branch/agent introduced or changed this fact."""
    return await service.why(branch, fact_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")  # stdio entrypoint; verify run() signature in v2
```

Mount into the existing FastAPI app (same process, one FalkorDB pool, one lifespan):

```python
# git0/api/app.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from mcp.server.transport_security import TransportSecuritySettings
from git0.mcp_server import mcp

mcp_app = mcp.streamable_http_app(
    json_response=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=["localhost:*", "127.0.0.1:*"],
        allowed_origins=["http://localhost:*"],
    ),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(lifespan=lifespan)
# ... REST routes ...
app.mount("/", mcp_app)  # inner route is /mcp by default; mount LAST so REST routes win
```

Note: the mount-at-`/` form follows the migration guide's example (`Mount("/", app=mcp.streamable_http_app(json_response=True))`). Verify the final client URL (`http://host/mcp`) and the stdio path with a real client before the demo.

Sources: https://github.com/modelcontextprotocol/python-sdk (migration.md, fetched via raw.githubusercontent.com); https://pypi.org/project/mcp/ ; https://gofastmcp.com/getting-started/upgrading/from-mcp-sdk-v2.md (for the contrast with standalone fastmcp)

---

## 3. Concurrency load test: "20 agents commit at the same time"

**Tool choice: custom asyncio harness with `falkordb.asyncio`.** Use locust only if the goal is HTTP/MCP end-to-end throughput.

- `falkordb` 1.8.0 exposes `from falkordb.asyncio import FalkorDB`, with `BlockingConnectionPool` from `redis.asyncio` passed as `connection_pool`. `await g.query(...)` returns a result with `.result_set`.
- **FalkorDB concurrency model matters for the result.** Per the FalkorDB docs, reads on a graph run in parallel (thread pool sized by `THREAD_COUNT`) but writes to the same graph are queued FIFO and run one at a time. So 20 writers to one graph serialize. Expect latency to grow with queue depth; the benchmark should show that rather than assume parallel speedup. Source: https://docs.falkordb.com/design/concurrency
- **Two contention levels, test both:**
  1. *Agent-private branches* (each agent commits to its own branch): branch-level CAS conflicts are rare by design; contention is graph-level write queuing.
  2. *Shared target* (20 agents merging or committing into `main`): branch-level CAS matters and retries are real.
- **Atomic CAS in one statement.** Read-then-write from Python is racy even with serialized writes between round trips. Put the head check and the update in a single Cypher query (`MATCH (b:Branch {name:$b}) WHERE b.head = $expected SET b.head = $new ... RETURN b.head`) and treat zero rows as a conflict.

Harness sketch:

```python
import asyncio, time
from falkordb.asyncio import FalkorDB
from redis.asyncio import BlockingConnectionPool


async def agent(i, barrier, g, out):
    await barrier.wait()  # all 20 start together
    head = await get_head(g, f"agent-{i}")
    for k in range(M):  # M commits per agent
        attempts = 0
        while True:
            attempts += 1
            t0 = time.perf_counter()
            ok = await cas_commit(g, f"agent-{i}", head, facts_for(i, k))
            out.lat.append(time.perf_counter() - t0)
            if ok:
                head = await get_head(g, f"agent-{i}")
                break
            out.retries += 1
            head = await get_head(g, f"agent-{i}")


async def main():
    pool = BlockingConnectionPool(max_connections=32, timeout=None, decode_responses=True)
    db = FalkorDB(connection_pool=pool)
    g = db.select_graph("git0_bench")
    barrier = asyncio.Barrier(20)
    out = Results()
    await asyncio.gather(*(agent(i, barrier, g, out) for i in range(20)))
    lost = expected_fact_ids() - await fetch_all_fact_ids(g)  # oracle
    report = {
        "p50": pct(out.lat, 50),
        "p95": pct(out.lat, 95),
        "retries": out.retries,
        "lost_updates": len(lost),
    }
    await pool.aclose()
```

**Metrics and definitions:**

- p50/p95 (and p99) commit latency via `time.perf_counter`, per attempt and per successful commit.
- Retries = CAS-rejected attempts. Report separately for scenario 1 (private branches, expect ~0) and scenario 2 (shared target).
- **Lost updates = expected fact IDs missing from the final graph.** Each agent writes uniquely-ID'd facts, so the oracle is set difference. Must be 0. Also check no branch head forks (each commit's parent is the previous head).
- Use `asyncio.Barrier` (Python 3.11+, fine on 3.12) so contention is real, not staggered.
- Run 5+ repetitions; report the spread, not one number.

pytest-benchmark measures repeated timing of a single callable; it is the wrong shape for this 20-writer scenario. Keep it for micro-benchmarks only.

Sources: https://pypi.org/project/falkordb/ ; https://github.com/FalkorDB/falkordb-py ; https://docs.falkordb.com/design/concurrency ; https://pypi.org/project/locust/

---

## 4. Benchmark harness design

**Recommendation: one interface, three backends, deterministic scenario files, a custom runner that emits JSON. Use pytest only for the contract tests.**

Backend interface (Protocol, all async for uniformity):

```python
class MemoryBackend(Protocol):
    name: str

    async def reset(self) -> None: ...
    async def fork(self, src: str, new: str) -> None: ...
    async def checkout(self, branch: str) -> str: ...  # rendered view
    async def commit(self, branch: str, edits: list[Edit]) -> CommitResult: ...
    async def merge(self, src: str, dst: str) -> MergeResult: ...  # conflicts list
```

The three backends:

1. **LWW dict**: flat `dict[key -> value]`, last-write-wins, no branches (fork = copy). Baseline for "what everyone does today".
2. **Text-git**: one text file per memory; branches are git branches in a temp repo; merge via `git merge-file -p --diff3 ours base theirs` (subprocess; conflicts reported through exit code and markers). Verified against git-merge-file man page from memory, not fetched in this pass. Python `difflib` does not do 3-way merge, so do not use it for the merge step.
3. **Git0 graph**: real FalkorDB via docker-compose; the MCP/service layer is called directly.

Scenario files (YAML, validated by a pydantic model):

```yaml
id: two_agents_conflicting_fact
seed: 42
agents: [planner, coder]
base:
  - {key: api.auth, value: "JWT HS256", source: seed}
ops:
  - {agent: planner, branch: planner, edit: {key: api.auth, value: "JWT RS256"}}
  - {agent: coder,   branch: coder,   edit: {key: api.auth, value: "session cookie"}}
  - {merge: [coder, planner]}
expect:
  conflicts: 1
  final: {api.auth: {one_of: ["JWT RS256", "session cookie"], needs_review: true}}
  lost_updates: 0
```

Scripted agents (deterministic edits, no LLM) for backend comparison. LLM-driven agents only in a separate end-to-end demo. This keeps numbers reproducible across backends.

Output: `results/<scenario_id>.json` with fields `backend`, `scenario`, `merge_accuracy` (expected facts present / expected), `conflicts_detected`, `false_conflicts`, `lost_updates`, `latency_ms: {p50,p95}`, `commit_count`, `seed`, `git_sha`, `timestamp`.

Layout:

```
bench/
  pyproject.toml                  # uv workspace member
  membench/
    __init__.py
    models.py                     # pydantic: Scenario, Edit, MergeResult, ScenarioResult
    backends/
      base.py                     # Protocol
      lww.py
      textgit.py
      git0.py
    scenarios/                    # *.yaml, one per scenario
    runner.py                     # python -m membench.runner --backend all --out results/
    metrics.py
  tests/
    test_backend_contract.py      # pytest, parametrized over the 3 backends
    test_concurrency.py           # the 20-agent test from section 3
  results/                        # gitignored
```

Sources: https://pypi.org/project/pytest-benchmark/ (scope); https://git-scm.com/docs/git-merge-file (unverified in this pass)

---

## 5. Prior art (what to differentiate against)

- **gitmem** (PyPI): "version-controlled memory system for LLM agents" in `.gitmem/`; `branch` forks a reasoning path, `merge` uses an LLM to synthesize branch insights. Closest in name to a memgit-style tool. Source: https://pypi.org/project/gitmem/ (search snippet only). Differentiator: LLM-synthesized merge, not a deterministic 3-way graph merge with provenance.
- **agmem** 0.3.0 (MIT, 2026-02-02): git-style CLI (`branch`, `checkout`, `merge`, `log`, `blame`, `reflog`, remotes). Merge rule depends on memory type: episodic appends, semantic consolidates with conflict markers, procedural prefers newer. Closest functional match. Differentiator: type heuristics on files, not a semantic graph; no per-fact `why` provenance query as far as the listing shows. Source: https://pypi.org/project/agmem/ (fetched).
- **Memoria** (MatrixOrigin): snapshot, branch, merge and rollback for agent memory on MatrixOne's copy-on-write engine. Differentiator: versioning at the DB-engine layer, not an agent-facing checkout/merge contract. Source: https://www.sourcepulse.org/projects/29043951 (search snippet).
- **git-ai-memory**: memory lives on the default branch; feature branches inherit rather than fork it; union merge by record ID. Differentiator: no real per-agent branches. Source: search snippet (GitHub r0han7/git-ai-memory).
- **Letta Code / Context Repositories** (launched Feb 2026): git-backed MemFS of markdown files; agents commit via bash; memory subagents run in git worktrees. Differentiator: one agent's memory repo, text-level, not multi-agent semantic merge. Source: https://www.letta.com/blog/context-repositories ; https://docs.letta.com/letta-code/memory/index.md (search snippets).
- **Graphiti** (getzep/graphiti, Apache 2.0, package `graphiti-core`): temporal knowledge graph with bi-temporal edges (event time and ingestion time); invalidates facts instead of overwriting; FalkorDB is a supported backend. Differentiator: time, not branches. Source: https://github.com/getzep/graphiti (search snippet).
- **Mem0**: marketed as shared memory across agents; no native branch/merge found. A Mesh Memory Protocol paper's comparison table marks Mem0 as not supporting multi-agent. Source: https://arxiv.org/pdf/2604.19540 (search snippet); Mem0 pages are vendor marketing.
- Related academic work: ChronoMem (arXiv 2607.27773), version control and semantic rollback for agent memory. Only the front matter was seen. Source: https://arxiv.org/pdf/2607.27773.
- "memgit" by that exact name was not found.

Positioning line: "Branching and 3-way merging are not new in agent memory (agmem, gitmem, Memoria, Letta). Ours differs in being a semantic graph with provenance (`why`) and an agent-facing contract where checkout(branch) is the only read path."

---

## 6. Python project setup

- **uv workspace**: root `pyproject.toml` with `[tool.uv.workspace] members = ["apps/*", "bench"]`; one lockfile; `uv run` per member. uv 0.13.1 per PyPI JSON.
- **Python**: 3.12 (all listed packages support it; pydantic 2.16 needs >=3.11).
- **ruff** 0.17.1: `[tool.ruff] target-version = "py312"`, `line-length = 100`, enable `I`, `B`, `UP`, `ASYNC`.
- **pytest 9.1.1 + pytest-asyncio 1.4.0**: `[tool.pytest.ini_options] asyncio_mode = "auto"`. Use session-scoped FalkorDB fixture with a fresh graph name per test.
- **pytest-benchmark 5.3.0**: micro-benchmarks only (section 4).
- **pydantic 2.16 + pydantic-settings 2.14.1**: `Settings(BaseSettings)` with `model_config = SettingsConfigDict(env_file=".env", extra="ignore")`; fields `falkordb_host`, `falkordb_port`, `falkordb_graph`, `anthropic_api_key` (SecretStr), `mcp_allowed_hosts`.
- **FastAPI** 0.143.2 for the API; `falkordb` 1.8.0 (with `falkordb.asyncio`).

Sources: https://pypi.org/pypi/{uv,ruff,pytest,pytest-asyncio,pytest-benchmark,pydantic,pydantic-settings,fastapi}/json (fetched 2026-10-16; pydantic-settings from GitHub changelog).

---

## Recommendation

### Agent loop (pseudo-code)

```python
async def run_agent(agent_id: str, branch: str, task: str) -> CommitResult:
    head, view = await mcp.checkout(branch)  # only read path
    out = await llm.complete(
        system=AGENT_PROMPTS[agent_id],  # role + rules, no memory
        user=render(view) + "\n\nTASK:\n" + task,
        tools=[COMMIT_FACTS_SCHEMA],  # one call, structured output
    )
    facts = out.tool_input["facts"]
    for attempt in range(3):
        res = await mcp.commit_facts(branch, facts, parent_hash=head)
        if res.ok:
            return res
        head, _ = await mcp.checkout(branch)  # re-read head; no LLM re-call
    raise CommitConflict(branch)


async def orchestrate(agents, task):
    await asyncio.gather(*(run_agent(a.id, a.branch, task) for a in agents))
    for src in agents:  # merges serialized per target
        await mcp.merge(src.branch, "main")  # the only 3-way merge step
```

Key points: each agent commits only to its own branch (CAS rarely fires); `merge` is the only operation that combines knowledge and is serialized per target branch. The LLM is called once per agent step.

### MCP placement

- Mount `streamable_http_app` into the existing FastAPI app at `/` (inner route `/mcp`), with one lifespan entering `mcp.session_manager.run()`. One process, one FalkorDB pool.
- Add a stdio entrypoint (`python -m git0.mcp_server`) for editor and Claude-based agents, sharing the same service layer.
- Expose exactly five tools: `checkout`, `commit_facts`, `log`, `merge`, `why`. No raw Cypher. Enforces "checkout is the only read path".
- Set `TransportSecuritySettings` explicitly to avoid 421s.

### Bench folder layout

```
bench/
  pyproject.toml
  membench/{models.py, runner.py, metrics.py}
  membench/backends/{base.py, lww.py, textgit.py, git0.py}
  membench/scenarios/*.yaml        # scripted agents, deterministic seed
  tests/test_backend_contract.py   # pytest, same tests across 3 backends
  tests/test_concurrency.py        # 20-agent asyncio harness, lost_updates == 0
  results/                         # JSON per scenario, gitignored
```

### Open items to verify before the build

1. Run `mcp` 2.3.0 mount example end to end with a real streamable-HTTP client; confirm the `/mcp` path and `mcp.run(transport="stdio")` signature.
2. Measure FalkorDB 20-writer latency on one graph vs per-branch graphs (write serialization per graph).
3. Confirm the `git merge-file` exit-code semantics for conflict counts on the installed git version.
4. Re-check pydantic and pydantic-settings versions with `uv lock`.

---

## Sources

- https://pypi.org/pypi/mcp/2.3.0/json ; https://github.com/modelcontextprotocol/python-sdk (docs/migration.md)
- https://gofastmcp.com/getting-started/upgrading/from-mcp-sdk-v2.md
- https://pypi.org/project/langgraph/ ; https://pypi.org/project/langchain-falkordb/ ; https://github.com/FalkorDB/langchain-falkordb
- https://pypi.org/project/falkordb/ ; https://github.com/FalkorDB/falkordb-py
- https://docs.falkordb.com/design/concurrency
- https://pypi.org/project/locust/
- https://pypi.org/project/agmem/ ; https://pypi.org/project/gitmem/ ; https://www.sourcepulse.org/projects/29043951
- https://www.letta.com/blog/context-repositories ; https://docs.letta.com/letta-code/memory/index.md
- https://github.com/getzep/graphiti
- https://arxiv.org/pdf/2604.19540 ; https://arxiv.org/pdf/2607.27773
- PyPI JSON: pytest, pytest-asyncio, pytest-benchmark, pydantic, pydantic-settings, fastapi, ruff, uv
