# ADR 0002: Call Groq and Gemini SDKs directly (no LiteLLM)

**Status:** accepted 2026-10-16 · **Owner:** Person B

## Context
The winplan assumed LiteLLM (Groq primary, Gemini fallback). Research (docs/research/02-llm.md): LiteLLM 1.82.7/1.82.8 shipped a credential stealer (2026-03-24). Groq strict `json_schema` works only on `openai/gpt-oss-20b/120b`, with no streaming or tools alongside it.

## Decision
`llm/client.py` wraps the `groq` and `google-genai` SDKs (~60 lines): strict schema on Groq, response schema on Gemini, Pydantic re-validation, sha256 disk cache, per-tenant token bucket, `LLMError` on total failure (UI red banner, M12).

## Consequences
Fewer dependencies and a smaller supply-chain surface. Two providers to maintain by hand, which is acceptable. Check the Groq free-tier limits on console.groq.com/settings/limits and the Gemini model name in AI Studio on day 1.
