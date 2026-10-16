# 02 - LLM layer research

Date: 2026-10-16. Scope: Python 3.12 FastAPI backend; agents extract facts as JSON triples with fixed predicates.

Confidence legend: **[verified]** = read from the official page or PyPI/GitHub source during this session. **[3rd-party]** = aggregator blog, treat as unreliable. **[recall]** = from memory, not re-checked today.

---

## 1. Groq structured outputs

Source: https://console.groq.com/docs/structured-outputs (raw markdown) [verified]

Models listed for `strict: true` (constrained decoding):

| Model ID | strict: true | strict: false |
|---|---|---|
| `openai/gpt-oss-20b` | yes | yes |
| `openai/gpt-oss-120b` | yes | yes |
| `qwen/qwen3.8-27b` | yes (per model table) | yes |
| `meta-models/muse-spark-open` | yes (per model table) | yes |
| `openai/gpt-oss-safeguard-20b` | no | yes |

Caveat: the same page's "Choosing Between Strict and Best-effort" table says strict is "Limited (GPT-OSS 20B, 120B)". Only gpt-oss-20b and gpt-oss-120b are confirmed by both tables. Test Qwen/Muse before relying on them.

Limitations (verbatim intent of the page):
- **Streaming and tool use are not supported with Structured Outputs.** So no tool calling in the same request.
- Strict mode: every property must be in `required`, every object needs `additionalProperties: false`. Optional fields must be nullable union types, not defaults. Schema reuse via `$defs`/`$ref`, recursion via `#` is shown.
- Strict mode "never errors or produces invalid JSON", but 400s can still happen for unsupported schema shapes (page asks for repros on the forum).
- Page does not give a full keyword whitelist. Types shown: string, number, boolean, integer, object, array, enum, `anyOf` for unions. Examples use `minimum`, `maximum`, `description`.

JSON Object Mode (`response_format={"type": "json_object"}`): all models, valid JSON syntax only, **no schema enforcement**, must say "respond in JSON" in the prompt, can occasionally error.

Request shape used in the docs:
```json
{"type": "json_schema", "json_schema": {"name": "...", "strict": true, "schema": {...}}}
```

Pydantic: the docs use `Model.model_json_schema()` plus `model_validate(json.loads(content))`. Note the Pydantic default-valued fields break strict mode, so use `ConfigDict(extra="forbid")` and no defaults.

---

## 2. Groq rate limits

Page: https://console.groq.com/docs/rate-limits [verified]

- The page's table is explicitly labelled "the base limits for the **Developer plan**". It does **not** publish free-tier numbers. Free-tier values are on the account page https://console.groq.com/settings/limits (not reachable from here).
- Official table (Developer plan base):

| Model | RPM | RPD | TPM | TPD |
|---|---|---|---|---|
| openai/gpt-oss-120b | 30 | 1K | 8K | 200K |
| openai/gpt-oss-20b | 30 | 1K | 8K | 200K |
| qwen/qwen3.8-27b | 30 | 1K | 8K | 200K |

- `llama-3.3-70b-versatile` is in the production model list (https://console.groq.com/docs/models [verified]) but **absent** from the rate-limit table.
- Third-party only [3rd-party]: free-tier llama-3.3-70b-versatile about 30 RPM / 1K RPD / 100K TPD (one table says 12K TPM). Sources disagree; see https://eesel.ai/blog/groq-pricing and https://openrouter.ai/blog/tutorials/free-llm-apis-compared/.
- Limits are organization-wide, not per key. Cached tokens do not count. 429 returns `retry-after` only when hit. Response headers `x-ratelimit-*` refer to RPD (requests) and TPM (tokens).
- Practical: with 1K RPD and 200K TPD on gpt-oss-20b, the **daily token cap binds first** for extraction workloads. The on-disk cache (section 6) is the main lever.

Small fast models on the production list: `llama-3.1-8b-instant` (smallest, ~560 tok/s) and `openai/gpt-oss-20b` (~1000 tok/s, fastest listed). No newer small Groq model appears on the page. Source: https://console.groq.com/docs/models [verified].

---

## 3. LiteLLM

### 3a. Latest version and security
- Latest stable on PyPI: **1.105.1** (uploaded 2026-10-14). Pre-releases 1.106.0rcN and 1.107.0.devN exist. Source: https://pypi.org/pypi/litellm/json [verified]. Note: 1.105.1 is only 2 days old, so do not pin it blindly.
- **Supply-chain incident, 2026-03-24:** PyPI releases `litellm==1.82.7` and `1.82.8` were backdoored and quarantined about 40 minutes later. Attributed to TeamPCP, which got in via the Trivy dependency in LiteLLM's CI. 1.82.7 injected a base64 payload into `proxy/proxy_server.py`. 1.82.8 added `litellm_init.pth`, which runs on every Python start. The payload was a credential stealer (env vars, SSH, AWS/GCP/Azure, k8s, DB passwords) sending data to `models.litellm.cloud`. Sources: https://docs.litellm.ai/blog/security-update-march-2026 [verified], https://www.bleepingcomputer.com/news/security/popular-litellm-pypi-package-compromised-in-teampcp-supply-chain-attack [verified].
- Official guidance from that post: 1.82.6 and earlier were audited (v1.78.0 to v1.82.6) against git. **v1.83.0** is described as clean, built by the new CI/CD v2 pipeline. Docker images from 1.83.0-nightly onward are cosign-signed.
- Safe pinning if you use it: `pip install --require-hashes` with an exact `litellm==<ver>` pin and wheel SHA256 from PyPI JSON; never unpinned; never 1.82.7 or 1.82.8; check `site-packages/litellm_init.pth` does not exist.

### 3b. Does `response_format` with json_schema / strict reach Groq?
Checked the source, not just docs. https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/llms/groq/chat/transformation.py [verified]:
- If `litellm.supports_response_schema(model, "groq")` is **true** (true for `groq/openai/gpt-oss-20b` and `gpt-oss-120b` in https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json [verified]), the code **does not touch** `response_format`. It goes through to Groq, so `json_schema.strict` is forwarded as written.
- If not native, LiteLLM rewrites the call into a forced `json_tool_call` tool. That is incompatible with user `tools` (raises `BadRequestError`), and sets `fake_stream`.
- LiteLLM Groq docs (https://docs.litellm.ai/docs/providers/groq) do not mention `response_format` or `strict` at all [verified].
- Pydantic class as `response_format`: LiteLLM converts it to a json_schema. Whether `strict: true` is added is not documented. Confirm by logging the outgoing payload.
- Model string: `groq/openai/gpt-oss-20b` (prefix `groq/`, slashes allowed) [verified].

### 3c. Fallbacks
- Router supports `num_retries`, `allowed_fails`, `cooldown_time`, per-deployment cooldowns, and `fallbacks` between model groups. Source: https://docs.litellm.ai/docs/routing [verified for retries/cooldowns]. The page did not show a Groq-to-Gemini example, so the `fallbacks=[{...}]` syntax is [recall].
- Gemini provider model string: `gemini/gemini-3.8-flash` (LiteLLM price map has it) [verified].

### 3d. Worth it vs direct SDKs?
**No, not for this project.** Reasons:
- Only two providers and one schema path; direct SDKs are about 20 lines.
- Supply-chain incident above; a fresh dependency with a credential-stealer history in its recent release line.
- Fallback, cache and tenant limit are all easy to write in our own code and are more transparent for benchmarking.
- LiteLLM's own disk cache key is not documented (https://docs.litellm.ai/docs/caching/all_caches [verified]), which matters for reproducible benchmarks.

Direct SDK versions (PyPI, 2026-10-16) [verified]: `groq` 1.7.0 (python >=3.10), `openai` 3.31.0, `google-genai` 2.31.0, `pydantic` 2.14.1, `diskcache` 5.6.3.

---

## 4. Gemini API free tier

Sources: https://ai.google.dev/gemini-api/docs/models, /pricing, /rate-limits, /structured-output [all verified, fetched today].

Current Flash-family model strings from the models page:
- `gemini-3.8-flash`: "most intelligent Flash model". Pricing page lists **Free of charge** on the Standard free tier through 2026-12-31.
- `gemini-3.6-flash`: previous generation Flash. Free of charge through 2026-12-31.
- `gemini-3.5-flash-lite`: cost-efficient, high-volume. Free of charge (Standard free tier).
- `gemini-3.1-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-flash-lite` also listed.
- `gemini-4-argon` ("Gemini 4 Argon") is out but **not on the Free tier**.

Recommended fallback: `gemini-3.8-flash`. Confidence: model string [verified], free-tier availability [verified from pricing page].

Rate limits:
- The rate-limit page does **not** publish free-tier RPM/RPD numbers. It says limits are per project, visible in AI Studio, and vary by model. Spend-based limit: Free = N/A. Read the actual numbers in AI Studio before the demo.
- Free-tier content may be used to improve Google products (pricing page; check the "Used to improve our products" row for the exact model) [verified-ish]. Do not send confidential customer data through the free tier.

Structured output:
- The docs now show Interactions API: `response_format={"type":"text","mime_type":"application/json","schema": ...}`. Python examples use `Model.model_json_schema()` and `model_validate_json`.
- Google GenAI SDK `generate_content` config: `response_mime_type="application/json"` plus `response_json_schema=<dict>` [recall; the search snippet supports this name but I did not confirm it on a fetched page]. The older `response_schema` (Pydantic class or uppercase-typed dict) is the pre-2025 route. Check your SDK version.
- Supported schema subset [verified]: types string/number/integer/boolean/object/array/null; `title`, `description`; `properties`, `required`, `additionalProperties`; string `enum` and `format`; number `enum`, `minimum`, `maximum`; array `items`, `prefixItems`, `minItems`, `maxItems`; recursion via `$ref: "#"`. "Not all JSON Schema features are supported." Very large or deep schemas may be rejected.
- Output is syntactically valid JSON but still validate it in Python.

---

## 5. Instructor

- PyPI: `instructor` **1.17.0**, uploaded 2026-09-09, requires Python `>=3.9,<4` [verified].
- Groq is supported via `instructor.from_provider("groq/<model>")` with `pip install "instructor[groq]"` [verified: https://python.useinstructor.com/integrations/groq/]. The docs example uses `groq/llama-3.3-70b-versatile`; I did not confirm which mode (TOOLS vs JSON) it uses for Groq, so it may not use the strict json_schema path.
- `max_retries=N` retries **validation failures only** (re-asks the model with the Pydantic error). It does **not** retry API errors (429, 5xx); those raise `InstructorRetryException` or propagate [verified: https://python.useinstructor.com/concepts/retrying/].
- Verdict: a 10-line hand-rolled retry is enough. Only add Instructor if you want its multi-provider mode switching. Do not combine Instructor with our cache without care, because the cache key must cover the schema and the retry prompts.

---

## 6. Caching for reproducible benchmarks

Simplest reliable approach: **sha256 of (model, prompt, schema JSON) -> one JSON file per key** under `cache/llm/`. Zero dependencies, easy to diff and commit, survives restarts.
- Write to `<key>.tmp` then `os.replace` for atomicity.
- Store `{served_by, tokens, data}` so a replay is byte-identical and "tokens saved" is computable.
- Key on the **primary** model id, so a benchmark run's cache is stable even if the fallback fired. Record `served_by` so you know which provider produced a cached answer.
- Alternative: `diskcache` 5.6.3 (SQLite-backed dict-like). Fine, but adds a dependency for no gain here.
- LiteLLM disk cache: `litellm.cache = Cache(type="disk")` plus `caching=True` per call, needs `litellm[caching]`. Key derivation not documented; hits are logged as `kwarg["cache_hit"]` in a custom logger [verified: https://docs.litellm.ai/docs/caching/all_caches]. Skip it (see 3d).

Temperature 0 does not guarantee identical output on hosted models. The cache is what makes benchmarks reproducible.

---

## 7. Token counting and usage reporting

- Groq: OpenAI-compatible `response.usage` with `prompt_tokens`, `completion_tokens`, `total_tokens` [recall; Groq's text-chat page did not show the fields today]. gpt-oss is a reasoning model, so reasoning tokens are billed/counted as output. Check whether `completion_tokens_details` is present on your build.
- Gemini: `response.usage_metadata` with `prompt_token_count`, `candidates_token_count`, `total_token_count`, and `thoughts_token_count` for thinking [recall].
- Pre-flight counting: Gemini has a count-tokens endpoint; Groq has no equivalent in these docs. Use `tiktoken` only as an estimate for gpt-oss (its tokenizer is not identical to OpenAI's public encodings, so label estimates as such).
- Report "tokens saved" = sum of `tokens` on cache hits (tokens that would have been spent). Report "tokens used" = provider `total_tokens` on misses. Do not mix them.

Price reference, LiteLLM price map (list, paid) [verified]: groq gpt-oss-20b $0.075 in / $0.30 out per M; gpt-oss-120b $0.15 / $0.60; gemini-3.8-flash $0.75 / $3.75 (free-tier usage costs $0 until 2026-12-31 per pricing page).

---

## Recommendation

Use direct SDKs, no LiteLLM. Primary Groq `openai/gpt-oss-20b` with strict json_schema; Gemini `gemini-3.8-flash` fallback; Pydantic validation at both edges; sha256 disk cache; raise on total failure; per-tenant sliding-window limit.

Before coding, do three checks:
1. Read your actual free-tier limits at https://console.groq.com/settings/limits and in Google AI Studio.
2. Run one strict request against `openai/gpt-oss-20b` with a schema that has your predicate `Literal[...]` enum, to confirm the 400-free path.
3. Log one outgoing Gemini request and confirm `response_json_schema` is accepted by your installed `google-genai` version.

Sketch, `git0/llm/client.py` (not run; schema-compatibility and SDK field names need the checks above):

```python
import hashlib, json, os, threading, time
from collections import defaultdict, deque
from pathlib import Path
from pydantic import BaseModel
from groq import Groq
from google import genai
from google.genai import types

PRIMARY, FALLBACK = "openai/gpt-oss-20b", "gemini-3.8-flash"


class LLMError(RuntimeError):
    """Every provider failed. Never return fabricated output."""


class TenantRateLimiter:
    def __init__(self, rpm: int):
        self.rpm, self.hits, self.lock = rpm, defaultdict(deque), threading.Lock()

    def check(self, tenant: str) -> None:
        now = time.monotonic()
        with self.lock:
            q = self.hits[tenant]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.rpm:
                raise LLMError(f"tenant {tenant!r} over {self.rpm} req/min")
            q.append(now)


class LLM:
    def __init__(self, cache_dir: str = "cache/llm", rpm: int = 20):
        self.groq, self.gemini = Groq(), genai.Client()  # GROQ_API_KEY, GEMINI_API_KEY
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.limiter = TenantRateLimiter(rpm)
        self.stats = {"cache_hits": 0, "tokens_saved": 0, "tokens_used": 0}

    def _groq(self, prompt: str, schema: type[BaseModel]) -> tuple[str, int]:
        js = {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}
        r = self.groq.chat.completions.create(
            model=PRIMARY,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_schema", "json_schema": js},
        )
        return r.choices[0].message.content, r.usage.total_tokens

    def _gemini(self, prompt: str, schema: type[BaseModel]) -> tuple[str, int]:
        cfg = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
            temperature=0,
        )
        r = self.gemini.models.generate_content(model=FALLBACK, contents=prompt, config=cfg)
        return r.text, r.usage_metadata.total_token_count

    def extract(self, tenant: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self.limiter.check(tenant)
        key = hashlib.sha256(
            json.dumps([PRIMARY, prompt, schema.model_json_schema()], sort_keys=True).encode()
        ).hexdigest()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            rec = json.loads(path.read_text())
            self.stats["cache_hits"] += 1
            self.stats["tokens_saved"] += rec["tokens"]
            return schema.model_validate(rec["data"])
        errors = []
        for name, call in (("groq", self._groq), ("gemini", self._gemini)):
            try:
                raw, tokens = call(prompt, schema)
                data = schema.model_validate_json(raw)  # Pydantic gate
            except Exception as e:
                errors.append(f"{name}: {type(e).__name__}: {e}")
                continue
            self.stats["tokens_used"] += tokens
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"served_by": name, "tokens": tokens, "data": data.model_dump()}))
            os.replace(tmp, path)
            return data
        raise LLMError("all providers failed: " + " | ".join(errors))
```

Schema rules for the triple model (apply to every extraction schema):
- `model_config = ConfigDict(extra="forbid")`, no field defaults, optionals as `X | None` with no default (strict mode).
- Predicate as `Literal["...fixed set..."]`, which becomes a JSON-schema enum that both providers enforce.

---

## Sources
- https://console.groq.com/docs/structured-outputs
- https://console.groq.com/docs/rate-limits
- https://console.groq.com/docs/models
- https://console.groq.com/settings/limits (not reachable, referenced only)
- https://docs.litellm.ai/docs/providers/groq
- https://docs.litellm.ai/docs/completion/json_mode
- https://docs.litellm.ai/docs/routing
- https://docs.litellm.ai/docs/caching/all_caches
- https://docs.litellm.ai/blog/security-update-march-2026
- https://www.bleepingcomputer.com/news/security/popular-litellm-pypi-package-compromised-in-teampcp-supply-chain-attack
- https://raw.githubusercontent.com/BerriAI/litellm/main/litellm/llms/groq/chat/transformation.py
- https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json
- https://pypi.org/pypi/litellm/json, /instructor/json, /groq/json, /openai/json, /google-genai/json, /diskcache/json, /pydantic/json
- https://ai.google.dev/gemini-api/docs/models
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/structured-output
- https://python.useinstructor.com/integrations/groq/
- https://python.useinstructor.com/concepts/retrying/
- https://eesel.ai/blog/groq-pricing [3rd-party]
- https://openrouter.ai/blog/tutorials/free-llm-apis-compared/ [3rd-party]
