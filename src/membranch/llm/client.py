"""Structured-output LLM client (Person B, Phase 1).

Contract:
    class LLMError(RuntimeError)            # raised on total failure; UI shows a red banner (M12)
    async def complete_json(prompt: str, schema: type[BaseModel], *, system: str,
                            tenant: str) -> tuple[BaseModel, Usage]
        - primary: Groq `openai/gpt-oss-20b`, response_format json_schema strict=True
        - fallback: Gemini Flash with response schema
        - always re-validate with Pydantic; never return fabricated output
        - disk cache keyed by sha256(model + system + prompt + schema json) under settings.llm_cache_dir
        - per-tenant token bucket so one judge cannot burn the shared Groq quota
See docs/research/02-llm.md (Recommendation) for a ready sketch.
"""

from pydantic import BaseModel


class LLMError(RuntimeError):
    pass


class Usage(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False


async def complete_json(prompt: str, schema: type[BaseModel], *, system: str, tenant: str):
    raise NotImplementedError("Phase 1 / Person B: see docs/team/person-b-agents-llm.md")
