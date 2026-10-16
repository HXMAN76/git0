# Plan: Person B agents + LLM, Phase 1 + 2 (issues #7 #8 #13)

Spec: `docs/ARCHITECTURE.md` (§4 agent turn flow, §6 contracts + REST table), `docs/team/person-b-agents-llm.md`, `docs/adr/0002-llm-direct-sdks.md`, `docs/adr/0003-plain-agent-loop.md`, `CLAUDE.md`, `docs/research/02-llm.md` (Recommendation section has a client sketch).

Branch: `b/p1-p2-agents-llm` (worktree `.worktrees/b-agents-llm`). One PR, reviewed by Roshan (@Git-Roshan09, owner of B). Closes #7 #8, and the B part of #13 (UI wiring of #13 stays with Sai). #2 (keys + rate limits) needs account consoles and stays open.

## Global Constraints
- Agents learn ONLY through `MemoryRepo.checkout(branch)`, `MemoryRepo.procedures(branch)`, `MemoryRepo.log(branch)` and `MemoryRepo.lookup(branch, key)` (M2). No module-level caches of graph data, no agent-to-agent messages.
- The LLM never decides merges (M4). It extracts facts, writes replies and explanations only.
- Fail loudly (M12): on total LLM failure raise `LLMError` with the provider errors; never return a default/fabricated extraction or reply.
- No LiteLLM, no LangGraph (ADR 0002/0003). Use the installed `groq` (1.7, `groq.AsyncGroq`) and `google-genai` (2.31, `google.genai.Client(api_key).aio.models.generate_content(model=..., contents=..., config=types.GenerateContentConfig(system_instruction=..., response_mime_type="application/json", response_json_schema=...))`) SDKs.
- Groq strict structured outputs: `response_format={"type": "json_schema", "json_schema": {"name": ..., "schema": ..., "strict": True}}` on `openai/gpt-oss-20b`. Strict mode requires every object schema to have `"additionalProperties": false` and every property listed in `"required"`; inline `$ref`/`$defs`; no `default` keys. Always re-validate output with Pydantic `model_validate_json`.
- Tests: pytest. Graph tests use the real FalkorDB `repo` fixture (`tests/conftest.py`). LLM calls in tests use injected fake providers / fake `llm` callables, never the network. One optional live test marked `@pytest.mark.llm`, skipped unless `GROQ_API_KEY` is set. Run `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .` before each commit (line length 110).
- Shared contracts: changes to `src/git0/core/models.py` must be additive; B-owned schemas (Extraction etc.) live in `src/git0/agents/` or `src/git0/llm/`. `AgentSpec`/`AgentReply` in `agents/base.py` may gain fields (additive).
- New Cypher only in `cypher/<name>.cypher` with `// name:` header + why-comment; load via `git0.core.queries.Q`; run `uv run python scripts/gen_cypher_docs.py` and commit `docs/CYPHER.md`.
- Fixed predicates: `deadline, owner, status, location, budget, decision, preference, depends_on, contact` (`git0.core.models.Predicate`). Fact keys are `subject|predicate`.
- Commit messages: Conventional Commits (scopes `llm`, `agents`, `api`, `docs`), body says why, trailer `Assisted-by: Claude Code`.
- Comment density like existing code: short docstrings saying why.

## Task 1: LLM client with fallback, cache, limiter (#7)

Files: `src/git0/llm/client.py` (+ optional `src/git0/llm/schema.py`), `src/git0/config.py`, `tests/llm/test_client.py`.

1. Keep `LLMError` and `Usage`; `Usage` gains `provider: str = ""` (additive). 
2. `strict_schema(model: type[BaseModel]) -> dict`: Pydantic `model_json_schema()` converted to Groq-strict form (inline refs, `additionalProperties: false` on every object, all properties required, drop `default`/`title` keys). Unit-test on a nested model.
3. Provider protocol: `async def __call__(system: str, prompt: str, name: str, schema: dict) -> tuple[str, Usage]` returning raw JSON text. Implement `GroqProvider(api_key, model)` (AsyncGroq, strict json_schema, temperature 0) and `GeminiProvider(api_key, model)` (response_json_schema, temperature 0). Read token usage from the responses (`usage.prompt_tokens`/`completion_tokens` for Groq, `usage_metadata.prompt_token_count`/`candidates_token_count` for Gemini; 0 if absent).
4. `class LLMClient(providers, cache_dir, offline=False, limiter=None)` with `async complete_json(prompt, schema, *, system, tenant) -> tuple[BaseModel, Usage]`:
   - limiter check first: `TenantLimiter(per_minute)` sliding 60 s window per tenant; over the limit raise `LLMError(f"rate limit: tenant {tenant} exceeded {n}/min")`.
   - cache key = sha256 of JSON `{system, prompt, schema: strict_schema(schema), models: [provider model ids]}`; file `<cache_dir>/<key>.json` holding `{"output": <raw json text>, "usage": {...}}`. Hit: validate and return with `cached=True` (no provider call, limiter not charged).
   - offline mode and miss: raise `LLMError("offline: no cached extraction for key …")`.
   - try providers in order; each failure (exception or Pydantic validation error) is recorded; first valid result is cached and returned.
   - all failed: `LLMError` listing each provider and its error.
5. Module-level `complete_json(prompt, schema, *, system, tenant)` uses a lazily built default client from settings: providers = Groq if `groq_api_key` set, then Gemini if `gemini_api_key` set; no providers and no offline cache hit gives `LLMError("no LLM provider configured")`. Settings (additive): `llm_offline: bool = False` (env `LLM_OFFLINE`), `llm_tenant_rpm: int = 20`.
6. Tests with fake providers: fallback to second provider when the first raises; fallback when the first returns invalid JSON; all fail gives LLMError naming both; cache hit skips providers and returns `cached=True`; offline miss raises; limiter blocks the 3rd call when per_minute=2; strict_schema shape. Live smoke test `@pytest.mark.llm` (skipped without GROQ_API_KEY).

## Task 2: Extraction schema + commit mapping (#8, M16)

Files: new `src/git0/agents/extract.py`, `tests/agents/test_extract.py`.

1. Schemas (LLM output, no ids): `ExtractedFact(s: str, p: Predicate, o: str)`, `ExtractedLink(child_key: str, parent_key: str)`, `ExtractedProcedure(trigger: str, steps: list[str])`, `Extraction(reply: str, facts: list[ExtractedFact], removed_keys: list[str], derived: list[ExtractedLink], procedures: list[ExtractedProcedure], cited_keys: list[str])`.
2. `normalise_entity(s) -> str`: lowercase, strip, inner whitespace and hyphens to `_`.
3. `build_prompt(view: list[Fact], procedures: list[Procedure], user_msg: str) -> str`: lists known entities ("reuse one of these ids when the message refers to them"), current facts as `s|p = o`, active procedures, the fixed predicate list, and the user message. Deterministic order.
4. `to_commit_request(extraction, view, *, branch, agent_id, msg, episode) -> tuple[CommitRequest, dict[str, str]]` returning the request and a `key -> fact id` map for cited keys:
   - normalise subjects; drop duplicate `(s, p)` keeping the last; new fact ids via `new_id()`.
   - `removed_keys`: ids of currently visible facts with that key, except keys that a new fact sets (commit_cas replaces those automatically).
   - `derived`: child must be a new fact in this extraction; parent resolves to a new fact id first, else the visible fact id for that key; unresolvable links are dropped.
   - procedures become `NewProcedure(id=new_id(), trigger, steps=json.dumps(steps))`.
   - cited key map: new fact id if the key is set in this commit, else the visible fact id; keys with neither are left out.
5. Tests: pure tests for normalisation, dedupe, removed_keys, derived resolution (new parent, visible parent, unknown dropped), procedures JSON, prompt contains entities/facts/predicates; plus one repo test committing the request and checking checkout + DERIVED_FROM.

## Task 3: Agent step + specs (#8, M2, M10)

Files: `src/git0/agents/base.py`, new `src/git0/agents/specs.py`, `tests/agents/test_step.py`.

1. `specs.py`: `PLANNER` (branch `planner`), `SCHEDULER` (branch `scheduler`; prompt: turn plans into concrete tasks and ALWAYS add `derived` links from each task to the facts it depends on), `NOTES` (branch `notes`; records decisions/contacts), `ARBITER` (branch `main`; explains merges, re-derives invalidated tasks). `AGENTS: dict[str, AgentSpec]`. Prompts are short, plain, and say: only use facts in the context, cite the keys you used in `cited_keys`, never invent facts.
2. `AgentReply` gains `missing_keys: list[str] = []`, `usage: Usage | None = None`, `branch: str = ""` (additive).
3. `async def step(agent, repo, user_msg, session_id, *, tenant, llm=None, branch=None) -> AgentReply` (`llm` defaults to `git0.llm.client.complete_json`; `branch` overrides `agent.branch`, used by the Arbiter):
   - `view = await repo.checkout(b)`, `procs = await repo.procedures(b)`; prompt via `build_prompt`; `extraction, usage = await llm(prompt, Extraction, system=agent.prompt, tenant=tenant)`.
   - always commit (persistent history): `to_commit_request(..., msg=f"{agent.id}: {user_msg[:60]}", episode=Episode(id=new_id(), text=user_msg, session_id=session_id))`, `kind="commit"`.
   - `missing_keys` = cited keys with no visible fact after the commit (check with `repo.lookup(b, key)`); if any, append to the reply text exactly: `\n\nNot in team memory (no path from {b} HEAD): {keys}` (M10).
   - return `AgentReply(agent_id, text, commit_id, cited_fact_ids, missing_keys, usage, branch=b)`.
4. Tests with a fake `llm` (records the prompt, returns a fixed Extraction): commit lands with Episode under Session (`HAS_TURN`); facts visible; cited ids resolve; second turn's prompt contains first turn's fact (persistence); prompt for agent on branch `b` does not contain a fact that exists only on `main`-after-branching (M2); missing cited key gives the exact not-in-memory text; LLMError from llm propagates and nothing is committed.

## Task 4: Handoff (#13, Track 02 shared state)

Files: new `src/git0/agents/handoff.py`, `src/git0/api/app.py`, `tests/agents/test_handoff.py`, `tests/api/test_agents_api.py`.

1. `async def handoff(repo, agent_id: str, *, session_id: str) -> HandoffResult` (model in handoff.py: `successor: str, branch: str, inherited: list[Fact], commits: int, commit_id: str, summary: str`): looks up the spec in `AGENTS` (KeyError if unknown); successor id = `f"{agent_id}-2"` if the log has no handoff yet, else increment the numeric suffix seen in the latest handoff commit's agent_id; reads `repo.log(branch)` and `repo.checkout(branch)`; summary is deterministic (no LLM): "`{successor}` took over `{branch}` from `{agent_id}`: inherited N facts from M commits." plus up to 10 `s|p = o` lines; commits on the branch with `kind="handoff"`, `agent_id=successor`, Episode text = summary.
2. `POST /api/{tenant}/agents/{agent_id}/kill` returns `HandoffResult` (404 for an unknown agent id).
3. Tests: after two Planner commits, handoff returns the inherited facts and a `kind == "handoff"` commit authored by the successor; a second handoff increments the suffix; scorecard `handoffs == 1` after one handoff; API route works on a seeded tenant (delete the test graph afterwards).

## Task 5: Arbiter: explain + targeted re-derive (#13, M1)

Files: new `src/git0/agents/arbiter.py`, new `cypher/facts_by_ids.cypher`, `src/git0/core/repo.py` (read method), `src/git0/api/app.py`, `tests/agents/test_arbiter.py`, `tests/api/test_agents_api.py`.

1. `async def explain(plan: MergeResult, *, tenant, llm=None) -> list[ConflictExplanation]` (`ConflictExplanation(key: str, text: str)`): no conflicts gives `[]` with no LLM call; otherwise ONE LLM call with a compact description of each conflict (key, base/ours/theirs values and authors, reason, dependents on each side, precedent string) asking for one plain-language sentence pair per conflict without git jargon ("Planner and Scheduler disagree…"); output keys must match the plan's conflict keys (raise LLMError if a key is missing).
2. `facts_by_ids.cypher` + `MemoryRepo.facts_by_ids(ids) -> list[Fact]`.
3. `async def rederive(repo, invalidated: list[Fact], *, target: str, tenant, session_id, llm=None) -> RederiveResult` (`replies: list[AgentReply]`, `tokens: int`, `owners: list[str]`): group invalidated facts by `agent_id`; for each owner with a spec in `AGENTS` (strip a `-N` handoff suffix to find it), call `step(owner_spec, repo, message, session_id, tenant=tenant, llm=llm, branch=target)` once with a message listing the invalidated facts (`s|p = o`) and asking to re-plan them against the current facts. Owners not in `AGENTS` are skipped and reported. `tokens` = sum of usage tokens.
4. Routes: `POST /api/{tenant}/merge/explain` body `{source, target}` returns `list[ConflictExplanation]` (plans server-side); `POST /api/{tenant}/arbiter/rederive` body `{target, fact_ids: list[str], session_id: str = "arbiter"}` returns `RederiveResult`. App-wide handler: `LLMError` gives HTTP 502 with `{"detail": str(exc)}` (M12 red banner).
5. Tests with fake llm: explain skips the LLM when there are no conflicts; explain maps texts to keys and raises on a missing key; rederive calls step once per owner only for invalidated facts (scheduler's 3 seed tasks after the dependency-conflict story) and commits re-planned facts on the target; API routes on a seeded tenant with a fake llm injected via a FastAPI dependency override or module attribute (choose one, keep it simple, document it); LLMError gives 502.
