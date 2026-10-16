# Person B: Agents + LLM, Roshan T (@Git-Roshan09)

**You own:** `src/membranch/llm/`, `src/membranch/agents/`, `src/membranch/mcp/`, `tests/llm/`, `tests/agents/`. **Buddy reviewer:** A.
**Rule M2:** an agent may only learn things through `repo.checkout(branch)` (and `log` for handoff). No module-level state, no passing text between agents. If FalkorDB is down, agents know nothing.

## Read first
- `docs/research/02-llm.md`: Groq strict schema works only on `openai/gpt-oss-20b|120b`, with no streaming/tools alongside it. Gemini fallback. Cache design
- `docs/research/05-agents-mcp-bench.md`: agent loop pseudo-code, MCP mounting
- ADR 0002 (no LiteLLM), ADR 0003 (no LangGraph)

## Phase 0
- [ ] Groq + Gemini API keys for every teammate (`.env`, never committed). Read the real limits at console.groq.com/settings/limits and record them in `docs/research/02-llm.md`
- [ ] Confirm the current Gemini Flash model id in AI Studio and update `.env.example`

## Phase 1 (→ Oct 17 10:00)
- [ ] `llm/client.py complete_json()`: Groq `response_format={"type":"json_schema","json_schema":{"name":..,"schema":Model.model_json_schema(),"strict":True}}` → Pydantic `model_validate_json` → on API error/timeout fall back to Gemini → on total failure raise `LLMError`. **Never** return a made-up default (M12)
- [ ] Disk cache: key `sha256(model|system|prompt|schema_json)`, file `LLM_CACHE_DIR/<key>.json` storing output + usage. `MEMBRANCH_LLM_OFFLINE=1` → cache only (bench + CI)
- [ ] `Extraction` schema: `facts: list[NewFact]`, `procedures: list[NewProcedure]` (learned workflows, steps JSON-encoded), `removed_keys: list[str]`, `derived: list[{child_key, parent_key}]`, `reply: str`. Prompt injects the current entity list from checkout ("reuse an id from this list") (M16)
- [ ] `agents/base.step()` for Planner end to end: checkout → extract → commit (with Episode) → reply with cited fact ids
- [ ] Tests: cached fixtures in `tests/llm/fixtures/`. One live test marked `@pytest.mark.llm`, skipped without `GROQ_API_KEY`

## Phase 2 (→ Oct 17 22:00)
- [ ] Agent replies stream over SSE. Emit a `: ping` heartbeat every 15 s while the LLM is thinking (CloudFront limit, ADR 0006)
- [ ] Scheduler + Notes agents on their own branches. Scheduler derives tasks from facts ("book venue Fri" `DERIVED_FROM` "launch=Fri")
- [ ] Arbiter: takes A's `MergeResult`, writes a plain-language explanation per conflict ("Planner and Scheduler disagree…"). Once the human picks, it re-invokes **only** the owners of invalidated derived facts. Count the tokens saved vs re-planning everything (for C)
- [ ] Handoff: `kill(agent)` → new agent instance checks out the same branch, reads `log`, says what it inherited
- [ ] "Not in memory": if `repo.lookup()` is empty, the agent answers exactly "not in team memory (no path from main HEAD)"

## Phase 3 (→ Oct 18 12:00)
- [ ] Per-tenant token bucket (protect the Groq quota during judging). A rate-limit error goes to the UI as a red banner
- [ ] MCP server (should-have): tools `checkout`, `commit_facts`, `log`, `merge`, `why` with `mcp` 2.3 `streamable_http_app`, mounted in the FastAPI lifespan. README snippet for Claude Code
- [ ] Prompt polish with the cached judge script, then re-record the cache for the bench

## Explain-it test (M14)
Why strict JSON + fixed predicates? Where exactly does an agent read memory? Why can't the LLM decide merges? What does the cache key include, and why?
