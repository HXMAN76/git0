"""Structured-output LLM client (Person B, Phase 1).

`complete_json(prompt, schema, *, system, tenant)` is the one entry point agents use. Order of events:
disk cache -> offline check -> per-tenant limiter -> providers in order (Groq, then Gemini).
Every provider result is re-validated with Pydantic; total failure raises `LLMError` (fail loudly,
never fabricate output). See docs/research/02-llm.md.
"""

import hashlib
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from git0.config import get_settings


class LLMError(RuntimeError):
    pass


class Usage(BaseModel):
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached: bool = False
    provider: str = ""


# ---------------------------------------------------------------- schema


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema -> Groq strict form.

    Strict mode rejects $ref, defaults and optional properties, so: inline refs, force
    `additionalProperties: false`, list every property as required, drop `default`/`title`.
    Optional fields stay required but nullable (pydantic already emits `anyOf [..., null]`).
    """
    root = model.model_json_schema()
    defs = root.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:  # "#/$defs/Name"
            inlined = walk(defs[node["$ref"].rsplit("/", 1)[-1]])
            return {**inlined, **walk({k: v for k, v in node.items() if k != "$ref"})}
        out = {k: walk(v) for k, v in node.items() if k not in ("default", "title", "$defs")}
        if isinstance(node.get("properties"), dict):
            # `properties` is a name->schema map: a field called "title"/"default" must survive.
            out["properties"] = {k: walk(v) for k, v in node["properties"].items()}
            out["required"] = list(node["properties"])
            out["additionalProperties"] = False
        return out

    return walk(root)


# ---------------------------------------------------------------- providers


class Provider(Protocol):
    model: str

    async def __call__(self, system: str, prompt: str, name: str, schema: dict) -> tuple[str, Usage]: ...


class GroqProvider:
    """Primary: Groq `openai/gpt-oss-20b`, strict json_schema."""

    def __init__(self, api_key: str, model: str, timeout_s: float = 20):
        from groq import AsyncGroq

        # max_retries=0: LLMClient already falls back to Gemini, so SDK retries only delay that by minutes.
        self.model, self._client = model, AsyncGroq(api_key=api_key, timeout=timeout_s, max_retries=0)

    async def __call__(self, system, prompt, name, schema):
        r = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": name, "schema": schema, "strict": True},
            },
            temperature=0,
        )
        text = r.choices[0].message.content
        if not text:
            raise ValueError("empty response content")
        u = r.usage
        usage = Usage(
            model=self.model,
            provider="groq",
            prompt_tokens=(u.prompt_tokens or 0) if u else 0,
            completion_tokens=(u.completion_tokens or 0) if u else 0,
        )
        return text, usage


class GeminiProvider:
    """Fallback: Gemini Flash with a JSON response schema."""

    def __init__(self, api_key: str, model: str, timeout_s: float = 20):
        from google import genai
        from google.genai import types

        # google-genai has no default timeout; HttpOptions.timeout is in milliseconds.
        opts = types.HttpOptions(timeout=int(timeout_s * 1000))
        self.model, self._client = model, genai.Client(api_key=api_key, http_options=opts)

    async def __call__(self, system, prompt, name, schema):
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=schema,
            temperature=0,
        )
        r = await self._client.aio.models.generate_content(model=self.model, contents=prompt, config=cfg)
        if not r.text:
            raise ValueError("empty response text")
        m = r.usage_metadata
        usage = Usage(
            model=self.model,
            provider="gemini",
            prompt_tokens=(m.prompt_token_count or 0) if m else 0,
            completion_tokens=(m.candidates_token_count or 0) if m else 0,
        )
        return r.text, usage


# ---------------------------------------------------------------- limiter


class TenantLimiter:
    """Sliding 60 s window per tenant. No awaits inside, so it is safe on one event loop."""

    def __init__(self, per_minute: int):
        self.per_minute, self._hits = per_minute, defaultdict(deque)

    def charge(self, tenant: str) -> None:
        now, q = time.monotonic(), self._hits[tenant]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= self.per_minute:
            raise LLMError(f"rate limit: tenant {tenant} exceeded {self.per_minute}/min")
        q.append(now)


# ---------------------------------------------------------------- client


class LLMClient:
    def __init__(
        self,
        providers: list[Provider],
        cache_dir: str | Path,
        offline: bool = False,
        limiter: TenantLimiter | None = None,
        cache_models: list[str] | None = None,
    ):
        self.providers, self.cache_dir, self.offline = providers, Path(cache_dir), offline
        self.limiter = limiter
        # The cache key uses the *configured* model names, not whichever providers got built, so an
        # offline replay with no API keys hits entries recorded by a keyed run.
        self.cache_models = cache_models if cache_models is not None else [p.model for p in providers]

    def _key(self, system: str, prompt: str, schema: dict) -> str:
        blob = {
            "system": system,
            "prompt": prompt,
            "schema": schema,
            "models": self.cache_models,
        }
        return hashlib.sha256(json.dumps(blob, sort_keys=True).encode()).hexdigest()

    def _read_cache(self, path: Path, schema: type[BaseModel]) -> tuple[BaseModel, Usage] | None:
        try:
            rec = json.loads(path.read_text())
            usage = Usage(**{**rec["usage"], "cached": True})
            return schema.model_validate_json(rec["output"]), usage
        except FileNotFoundError:
            return None
        except Exception:  # cache is derived data: a corrupt/stale entry is a miss, not an error
            return None

    def _write_cache(self, path: Path, raw: str, usage: Usage) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps({"output": raw, "usage": usage.model_dump()}))
        os.replace(tmp, path)  # atomic: readers never see a half-written file

    async def complete_json(
        self, prompt: str, schema: type[BaseModel], *, system: str, tenant: str
    ) -> tuple[BaseModel, Usage]:
        strict = strict_schema(schema)
        key = self._key(system, prompt, strict)
        path = self.cache_dir / f"{key}.json"
        if (hit := self._read_cache(path, schema)) is not None:
            return hit  # free: no limiter charge, no provider call
        if self.offline:
            raise LLMError(f"offline: no cached extraction for key {key}")
        if not self.providers:
            raise LLMError("no LLM provider configured")
        if self.limiter:
            self.limiter.charge(tenant)

        errors: list[str] = []
        for p in self.providers:
            try:
                raw, usage = await p(system, prompt, schema.__name__, strict)
                parsed = schema.model_validate_json(raw)  # never trust the provider's schema enforcement
            except Exception as exc:
                errors.append(f"{p.model}: {type(exc).__name__}: {exc}")
                continue
            self._write_cache(path, raw, usage)
            return parsed, usage
        raise LLMError("all LLM providers failed: " + " | ".join(errors))


# ---------------------------------------------------------------- module-level entry point

_default: LLMClient | None = None


def _default_client() -> LLMClient:
    global _default
    if _default is None:
        s = get_settings()
        providers: list[Provider] = []
        if s.groq_api_key:
            providers.append(GroqProvider(s.groq_api_key, s.groq_model, s.llm_timeout_s))
        if s.gemini_api_key:
            providers.append(GeminiProvider(s.gemini_api_key, s.gemini_model, s.llm_timeout_s))
        _default = LLMClient(
            providers,
            s.llm_cache_dir,
            s.llm_offline,
            TenantLimiter(s.llm_tenant_rpm),
            cache_models=[s.groq_model, s.gemini_model],
        )
    return _default


async def complete_json(
    prompt: str, schema: type[BaseModel], *, system: str, tenant: str
) -> tuple[BaseModel, Usage]:
    return await _default_client().complete_json(prompt, schema, system=system, tenant=tenant)
