# git0 MCP — Integration Reference

Complete documentation of the git0 MCP server, the relay hook, and how to wire them into any coding-agent harness.

---

## Overview

git0 exposes a **streamable-HTTP MCP server** that lets any coding agent (Claude Code / cmdc, Cursor, Copilot, custom) read and write a shared FalkorDB knowledge graph. Two or more agents running in separate sessions use this to:

- Broadcast intent (which files they will touch, which approach they chose)
- Receive peer context automatically before every file edit (via a `PreToolUse` hook)
- Surface merge conflicts to a human for approval

```
Agent A (folder1/)          Agent B (folder2/)
   │                              │
   │── PreToolUse hook ──────────▶│ polls peer branches
   │                              │
   └──▶ git0-mcp (port 8002) ◀───┘
              │
         FalkorDB (port 6380)
```

---

## Component Map

| File | Purpose |
|---|---|
| `src/git0/mcp/server.py` | MCP server — exposes all tools, CORS-enabled for browser |
| `src/git0/mcp/__init__.py` | Package init, re-exports `mcp` object |
| `pyproject.toml` | Adds `git0-mcp` as a console-script entry point |
| `harness/folder1/.commandcode/hooks/git0-relay-inject.py` | PreToolUse hook for agent 1 |
| `harness/folder2/.commandcode/hooks/git0-relay-inject.py` | PreToolUse hook for agent 2 (identical) |
| `harness/folder1/.commandcode/skills/git0-relay/SKILL.md` | Agent skill (instructions for `/git0-relay`) |
| `harness/folder2/.commandcode/skills/git0-relay/SKILL.md` | Same skill, copied to each agent folder |
| `harness/folder1/.commandcode/settings.json` | Hook registration for folder1 session |
| `harness/folder2/.commandcode/settings.json` | Hook registration for folder2 session |
| `harness/.relay-sessions/` | Shared directory — branch name files for peer discovery |
| `harness/dag-viewer.html` | Live browser DAG viewer polling git0-mcp |

---

## 1. MCP Server (`src/git0/mcp/server.py`)

### What changed

The server was extended with:

1. **`--http` mode with CORS** — allows browser clients and the relay hook (which uses `urllib`) to reach it from any origin.
2. **`--port` flag** — run on any port (defaults to 8001 for SSE, 8002 used in practice for HTTP mode).
3. **`git0-mcp` entry point** in `pyproject.toml` — `uv run git0-mcp --http --port 8002`.

### Transport options

```
# stdio (default — for IDE MCP config, e.g. Claude Code settings.json)
uv run python -m git0.mcp.server

# SSE (legacy, port 8001)
uv run python -m git0.mcp.server --sse --port 8001

# Streamable-HTTP (used by relay hook + DAG viewer + browser)
uv run python -m git0.mcp.server --http --port 8002
```

### CORS added (required for browser + hook)

```python
# src/git0/mcp/server.py  ── main() ── --http branch
from starlette.middleware.cors import CORSMiddleware

app = mcp.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["mcp-session-id"],  # ← required: hook reads this header
)
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
```

`expose_headers=["mcp-session-id"]` is critical — the relay hook reads this header from the MCP `initialize` response to reuse the session across multiple hook firings.

### Available tools

| Tool | Description |
|---|---|
| `seed_tenant(tenant)` | Initialize a tenant (safe to call repeatedly) |
| `commit_facts(tenant, branch, agent_id, message, facts)` | Write structured facts to a branch |
| `checkout(tenant, branch)` | Read all facts on a branch |
| `log(tenant, branch, limit)` | Commit history for a branch |
| `graph_view(tenant, branch)` | Full knowledge graph as nodes + edges |
| `merge_preview(tenant, source, target)` | Preview conflicts before merge |
| `merge_resolve(tenant, source, target, choices, agent_id)` | Apply merge, resolving conflicts |
| `watch_branch(tenant, branch, since_commit_id)` | Long-poll for new commits |
| `why(tenant, fact_id)` | Explain derivation chain for a fact |
| `scorecard(tenant)` | High-level metrics |
| `list_agents(tenant)` | List available built-in agents + branches |
| `agent_message(tenant, agent_id, text)` | Full LLM-backed agent turn |

### Valid predicates (closed set)

`deadline`, `owner`, `status`, `location`, `budget`, `decision`, `preference`, `depends_on`, `contact`

### Tenant naming

Tenant names must match `[a-z0-9_]{1,40}` — **underscores only, no hyphens**.

### Commit constraint

Each `(subject, predicate)` pair must be unique within one `commit_facts` call. Two facts with the same `s` AND `p` cause a Pydantic `ValidationError: duplicate (s, p) in facts`. Use distinct `s` values per file.

---

## 2. Relay Hook (`git0-relay-inject.py`)

Lives at `.commandcode/hooks/git0-relay-inject.py` inside each agent's project folder.

### What it does

Fires before every `write`, `edit`, `shell`, or `read` tool call. It:

1. Initializes (or reuses) an MCP session with git0-mcp
2. Reads `.relay-sessions/*.branch` to discover which peer branches are active
3. Calls `log()` on each peer branch to check for new commits since last seen
4. If new commits exist, injects a `systemMessage` into the agent's context before the tool runs

### Configuration (top of file)

```python
GIT0_URL = os.environ.get("GIT0_MCP_URL", "http://127.0.0.1:8002/mcp")
TENANT = os.environ.get("GIT0_TENANT", "shop_demo")
MY_BRANCH = os.environ.get("GIT0_MY_BRANCH", "")
SESSIONS_DIR = os.environ.get("GIT0_SESSIONS_DIR", "/absolute/path/to/.relay-sessions")
```

All four are overridable via env vars. For desktop app sessions (where env vars aren't guaranteed), hardcode `_default_sessions` directly in the file.

### Skip guard (prevents recursion)

```python
tool_name = hook_input.get("tool_name", "")
if "git0" in tool_name or tool_name in ("read_file", "list_directory", "search"):
    print(json.dumps({"action": "allow"}))
    return
```

git0 tool calls skip the hook to avoid infinite recursion.

### MCP session reuse

The hook stores its MCP `session_id` in `/tmp/git0-relay-<agent_session_id>.json` and reuses it across firings. Each agent session gets one MCP session.

### Branch registration

When the agent writes its `.branch` file (per the skill's Step 2), the hook reads it automatically on the next firing — no restart needed.

### Injected message format

```
⚡ [git0-relay] New commits on peer branch `fix_jwt_secret`:
  • [abc12345] Starting work on ISSUE-42 (by fix_jwt_secret, +4 facts)
  → call git0 checkout(tenant="shop_demo", branch="fix_jwt_secret") to read their latest state before editing shared files.
```

---

## 3. Agent Skill (`skills/git0-relay/SKILL.md`)

Lives at `.commandcode/skills/git0-relay/SKILL.md`. Triggered with `/git0-relay` in cmdc.

### Steps the skill runs

1. `seed_tenant(tenant="<tenant>")` — idempotent setup
2. Pick unique branch name; write `.branch` file to shared relay dir
3. `log(tenant, branch="main", limit=5)` — check peer state
4. `commit_facts(...)` — broadcast intent + decisions before editing
5. Work normally (hook auto-injects peer context)
6. `commit_facts(...)` — mark files unlocked, issues fixed
7. **Mandatory**: `merge_preview(...)` → surface conflicts → `merge_resolve(...)`

### Conflict resolution protocol

- `merge_preview` returns `{conflicts: [...], auto_merged: [...]}`
- If `conflicts` non-empty → STOP, present ⚠️ block to human, wait for answer, then call `merge_resolve` with `choices={"s|p": "winning_fact_id"}`
- If `conflicts` empty → scan `auto_merged` for same-file `decision` facts with different values (semantic conflict) → surface the same way
- After human approves (or no conflict): `merge_resolve(..., choices={})` to finalize
- **`choices` keys must match keys in the tool's own `conflicts` array** — you cannot pass arbitrary keys; `choices={}` is valid for clean/semantic merges

---

## 4. Settings (`settings.json`)

Hook registration for cmdc / Claude Code:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "write|edit|shell|read",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .commandcode/hooks/git0-relay-inject.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

The `matcher` is a regex applied to `tool_name`. Timeout is 5s — if git0-mcp is unreachable, the hook exits cleanly (returns `{"action": "allow"}`).

---

## 5. Shared Relay Bus (`.relay-sessions/`)

A plain directory on the shared filesystem. Each agent writes one file:

```
.relay-sessions/
  fix_auth.branch       ← contains "fix_auth"
  fix_jwt_secret.branch ← contains "fix_jwt_secret"
```

Filename = branch name. The hook globs `*.branch` on every firing. For two agents on the same machine, any path works. For cross-machine setups, use a shared NFS mount or replace with a FalkorDB-backed store.

---

## Connecting git0-relay to Any Harness

### Prerequisites

1. **FalkorDB** running on port 6380:
   ```bash
   docker run -d --name falkordb-dev -p 6380:6379 falkordb/falkordb:latest
   ```

2. **git0-mcp** running on port 8002:
   ```bash
   cd /path/to/git0
   uv run python -m git0.mcp.server --http --port 8002
   ```

3. **Python 3.10+** available as `python3` (hook uses stdlib only — no pip installs needed)

### Step-by-step for a new agent folder

**1. Create the config file** (`.git0-relay` in your project root):
```
GIT0_MCP_URL=http://127.0.0.1:8002/mcp
GIT0_SESSIONS_DIR=/path/to/shared/.relay-sessions
GIT0_TENANT=your_project_name
```

**2. Copy the hook:**
```bash
mkdir -p .commandcode/hooks
cp /path/to/git0/harness/folder1/.commandcode/hooks/git0-relay-inject.py \
   .commandcode/hooks/git0-relay-inject.py
```

Edit the `_default_sessions` line near the top to match your `GIT0_SESSIONS_DIR`.

**3. Copy the skill:**
```bash
mkdir -p .commandcode/skills/git0-relay
cp /path/to/git0/harness/folder1/.commandcode/skills/git0-relay/SKILL.md \
   .commandcode/skills/git0-relay/SKILL.md
```

Edit the skill: replace `shop_demo` with your tenant name, update the `ls` path in Step 2 to your `GIT0_SESSIONS_DIR`.

**4. Merge hook registration into `settings.json`:**

If `.commandcode/settings.json` doesn't exist yet:
```bash
cat > .commandcode/settings.json << 'EOF'
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "write|edit|shell|read",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .commandcode/hooks/git0-relay-inject.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
EOF
```

If it already exists, merge the `PreToolUse` entry under the existing `hooks` key — don't overwrite other hooks.

**5. Add git0-mcp as a named MCP server** (optional but recommended — lets the agent call tools natively without HTTP):

For cmdc / Claude Code (`settings.json` or `.mcp.json`):
```json
{
  "mcpServers": {
    "git0": {
      "url": "http://127.0.0.1:8002/mcp",
      "transport": "streamable-http"
    }
  }
}
```

For stdio transport (no HTTP server needed):
```json
{
  "mcpServers": {
    "git0": {
      "command": "uv",
      "args": ["run", "python", "-m", "git0.mcp.server"],
      "cwd": "/path/to/git0"
    }
  }
}
```

**6. Create the shared relay dir:**
```bash
mkdir -p /path/to/shared/.relay-sessions
```

**7. Start an agent session** and run `/git0-relay <your task description>`.

### Minimum viable checklist

- [ ] FalkorDB container running on port 6380
- [ ] git0-mcp running on port 8002 (`--http` mode with CORS)
- [ ] Hook file at `.commandcode/hooks/git0-relay-inject.py`
- [ ] Skill file at `.commandcode/skills/git0-relay/SKILL.md`
- [ ] Hook registered in `.commandcode/settings.json`
- [ ] Shared `.relay-sessions/` dir exists (same path in both agent hooks)
- [ ] Tenant name uses underscores only (`a-z`, `0-9`, `_`)

### Adapting for other IDE/harness types

| Harness | Hook mechanism | Where to register |
|---|---|---|
| cmdc / Claude Code | `PreToolUse` in `settings.json` | `.commandcode/settings.json` |
| Cursor | MCP stdio server | `.cursor/mcp.json` |
| VS Code Copilot | MCP stdio server | `.vscode/mcp.json` |
| Custom agent loop | Before each tool call | inject `systemMessage` from hook stdout |
| CI pipeline | No hook needed | Call `log()` + `commit_facts()` directly |

For harnesses that don't support `PreToolUse` hooks: call the hook script manually before each tool invocation, or poll git0-mcp directly in your agent loop using `watch_branch(since_commit_id=<last_seen>)`.

---

## Troubleshooting

**Hook times out / no peer context injected**
- Check git0-mcp is running: `curl http://127.0.0.1:8002/mcp` should return `405 Method Not Allowed` (correct — needs POST)
- Check SESSIONS_DIR path is the same in both hooks
- Check `.branch` files exist: `ls /path/to/.relay-sessions/`

**`duplicate (s, p) in facts` error**
- Two facts in the same `commit_facts` call share the same `s` and `p`. Give each file its own `s` subject (e.g. `auth_py`, `api_py`).

**`merge_resolve` fails with unknown choices key**
- `choices` keys must come from `merge_preview`'s `conflicts[].key` array. If `conflicts` is empty, use `choices={}`.

**Conflict tool never auto-detects divergence**
- The tool detects conflict only when BOTH agents have merged into `main` since their common ancestor. Agent 2 must run `merge_preview` AFTER Agent 1 has merged. If timing is off, agents surface semantic conflicts manually (⚠️ block) — this is the correct fallback.

**MCP session expires mid-session**
- State file at `/tmp/git0-relay-<session_id>.json` is deleted on reboot. The hook creates a new session automatically on next firing.

**Browser DAG viewer shows no data**
- Verify CORS is active: the server must have been started with `--http`, not `--sse`
- Run `python3 -m http.server 8080` from the `harness/` directory
- Open `http://127.0.0.1:8080/dag-viewer.html`
