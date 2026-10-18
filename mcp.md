# git0 MCP: integration reference

git0's memory and code-relay operations are exposed as an MCP server, so a coding agent (Claude Code, Cursor, Gemini CLI, a custom harness) can read and write the same FalkorDB graph the web app uses. Everything below describes code that is in this repository.

## Two ways to run it

| Where | How | Who uses it |
|-|-|-|
| Mounted in the API at `/mcp/` | starts with the app (`make api`, or the deployed container) | the `/ide/` relay demo's hooks, in the same process |
| Standalone `git0-mcp` CLI | `uv run git0-mcp` (entry point in `pyproject.toml`, code in `src/git0/mcp/server.py`) | an external agent harness on your machine |

The mounted endpoint is local-only on purpose: it is built with `host="127.0.0.1"`, so MCP's DNS-rebinding check rejects any other `Host` header (public requests through Caddy get 421). The server has no authentication and every tool takes a `tenant` argument, so keep it bound to localhost.

### Standalone transports

```bash
uv run git0-mcp                          # stdio (default): for an MCP client config
uv run git0-mcp --sse --port 8001        # SSE, default port 8001
uv run git0-mcp --http --port 8002       # streamable HTTP at http://127.0.0.1:8002/mcp, default port 8001
```

`--http` wraps the app in CORS (`allow_origins=["*"]`, `expose_headers=["mcp-session-id"]`) so a browser page or a script can reuse the MCP session id. All transports need FalkorDB (`make db-up`) and use the same settings as the API (`.env`).

Example client entry (stdio):

```json
{ "mcpServers": { "git0": { "command": "uv", "args": ["run", "git0-mcp"], "cwd": "/path/to/git0" } } }
```

## Tools

Memory (shared team memory with branches and merges):

| Tool | What it does |
|-|-|
| `seed_tenant(tenant)` | create the demo launch-plan room (safe to repeat) |
| `checkout(tenant, branch)` | facts visible on a branch |
| `log(tenant, branch, limit)` | commit history of a branch |
| `graph_view(tenant, branch, ...)` | nodes + links for a graph view |
| `why(tenant, fact_id)` | provenance: fact, commit, agent, chat turn |
| `scorecard(tenant)` | live Track 02 counts |
| `commit_facts(tenant, branch, agent_id, ...)` | write structured facts to a branch |
| `agent_message(tenant, agent_id, text)` | one LLM-backed agent turn (needs an LLM key) |
| `merge_preview(tenant, source, target)` | 3-way semantic merge plan with conflicts |
| `merge_resolve(tenant, source, target, choices, agent_id)` | apply a merge with the chosen sides |
| `list_agents(tenant)` | built-in agents and their branches |
| `watch_branch(tenant, branch, ...)` | wait for new commits on a branch |

Code relay (catch conflicts between two agents editing the same repo):

| Tool | What it does |
|-|-|
| `code_announce_intent(tenant, agent, task, symbols)` | record which functions an agent plans to touch |
| `code_check_edit(tenant, agent, path, old_source, new_source)` | before a write: does it collide with the peer's unseen changes (same function, changed signature, or reachable through `CALLS*1..3`)? |
| `code_record_edit(...)` | after a write: record the changed symbols and signatures |
| `code_peer_activity(tenant, agent)` | the peer's changes this agent has not seen yet |
| `code_acknowledge(tenant, agent, change_ids)` | mark peer changes as seen |
| `code_record_conflicts(tenant, agent, conflicts)` | store conflicts for a human |
| `code_resolve_conflicts(tenant, conflict_ids, resolution)` | record the human's choice: `adopt`, `override` or `pause` |

Parameters and return shapes are in the tool docstrings in `src/git0/mcp/server.py`.

## The hooks in this repo

`src/git0/ide/hooks.py` (`RelayHooks`) is the Pre/PostToolUse layer every agent tool call in the `/ide/` demo goes through (driven by `src/git0/ide/harness.py`):

- **PreToolUse, `write_file`:** calls `code_check_edit`; a hit denies the write and shows the conflict.
- **PreToolUse, other tools:** calls `code_peer_activity` and injects the peer's new changes as context.
- **PostToolUse, `write_file`:** calls `code_record_edit`.

To wire another harness the same way, register the MCP server above, call `code_check_edit` before each file write (block on a hit), and call `code_record_edit` after it. This repository does not ship hook scripts or skill files for external harnesses; `hooks.py` is the reference implementation.

## Rules the tools enforce

- **Predicates** are a closed set: `deadline`, `owner`, `status`, `location`, `budget`, `decision`, `preference`, `depends_on`, `contact`.
- **Tenant names** match `[a-z0-9_]{1,40}` (underscores, no hyphens).
- **One value per key per commit:** two facts with the same subject and predicate in one `commit_facts` call are rejected (`duplicate (s, p) in facts`).

## Troubleshooting

- `421 Misdirected Request` on `/mcp/`: the request did not come from `127.0.0.1`. Use the standalone CLI on your machine instead of the deployed server.
- `Invalid graph operation on empty key`: the tenant has no graph yet; call `seed_tenant` first.
- `agent_message` errors: check that an LLM key (`GROQ_API_KEY` or `GEMINI_API_KEY`) is set in `.env`.
