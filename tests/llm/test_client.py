"""LLM client tests: fake providers only, no network (live smoke test is marked `llm`)."""

import json
import os
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from git0.llm.client import LLMClient, LLMError, TenantLimiter, Usage, complete_json, strict_schema


class Inner(BaseModel):
    kind: Literal["a", "b"]
    note: str | None = None


class Outer(BaseModel):
    title: str = Field(default="t", description="keeps description")
    items: list[Inner]
    one: Inner


class Fake:
    """Provider stub: returns canned raw JSON text or raises."""

    def __init__(self, model: str, out: str | Exception):
        self.model, self.out, self.calls = model, out, 0

    async def __call__(self, system, prompt, name, schema):
        self.calls += 1
        if isinstance(self.out, Exception):
            raise self.out
        return self.out, Usage(model=self.model, provider=self.model, prompt_tokens=3, completion_tokens=2)


GOOD = json.dumps({"title": "x", "items": [{"kind": "a", "note": None}], "one": {"kind": "b", "note": "n"}})


def client(tmp_path, *providers, **kw):
    return LLMClient(list(providers), tmp_path, **kw)


async def call(c, tenant="t1", prompt="p"):
    return await c.complete_json(prompt, Outer, system="s", tenant=tenant)


def test_strict_schema_shape():
    s = strict_schema(Outer)
    assert "$defs" not in s and "$ref" not in json.dumps(s)
    assert '"default"' not in json.dumps(s)
    assert "title" not in s and "title" not in s["properties"]["one"]  # schema-level title dropped
    assert s["additionalProperties"] is False
    assert set(s["required"]) == {"title", "items", "one"}
    inner = s["properties"]["one"]
    assert inner["additionalProperties"] is False and set(inner["required"]) == {"kind", "note"}
    assert s["properties"]["items"]["items"]["additionalProperties"] is False
    assert inner["properties"]["kind"]["enum"] == ["a", "b"]
    assert s["properties"]["title"]["description"] == "keeps description"


def test_strict_schema_keeps_fields_named_title_and_default():
    class Odd(BaseModel):
        title: str
        default: int

    s = strict_schema(Odd)
    assert set(s["properties"]) == {"title", "default"} and set(s["required"]) == {"title", "default"}


async def test_fallback_when_first_raises(tmp_path):
    a, b = Fake("a", RuntimeError("boom")), Fake("b", GOOD)
    out, usage = await call(client(tmp_path, a, b))
    assert isinstance(out, Outer) and out.one.kind == "b"
    assert (a.calls, b.calls) == (1, 1) and usage.provider == "b" and not usage.cached


async def test_fallback_when_first_returns_invalid_json(tmp_path):
    a, b = Fake("a", '{"title": 1}'), Fake("b", GOOD)
    out, _ = await call(client(tmp_path, a, b))
    assert out.title == "x" and b.calls == 1


async def test_all_fail_names_every_provider(tmp_path):
    with pytest.raises(LLMError) as e:
        await call(client(tmp_path, Fake("a", RuntimeError("boomA")), Fake("b", "not json")))
    msg = str(e.value)
    assert "a:" in msg and "boomA" in msg and "b:" in msg


async def test_cache_hit_skips_providers(tmp_path):
    a = Fake("a", GOOD)
    c = client(tmp_path, a)
    await call(c)
    out, usage = await call(c)
    assert a.calls == 1 and usage.cached and out.one.note == "n"
    assert usage.prompt_tokens == 3  # original usage preserved
    # a fresh client on the same dir also hits (disk, not memory)
    out2, usage2 = await call(client(tmp_path, Fake("a", RuntimeError("never"))))
    assert usage2.cached and out2 == out


async def test_cache_key_depends_on_prompt(tmp_path):
    a = Fake("a", GOOD)
    c = client(tmp_path, a)
    await call(c, prompt="one")
    await call(c, prompt="two")
    assert a.calls == 2


async def test_offline_miss_raises_and_hit_works(tmp_path):
    with pytest.raises(LLMError, match="offline: no cached extraction for key"):
        await call(client(tmp_path, Fake("a", GOOD), offline=True))
    await call(client(tmp_path, Fake("a", GOOD)))
    _, usage = await call(client(tmp_path, Fake("a", GOOD), offline=True))
    assert usage.cached


async def test_limiter_blocks_third_call_per_tenant(tmp_path):
    c = client(tmp_path, Fake("a", GOOD), limiter=TenantLimiter(2))
    await call(c, prompt="1")
    await call(c, prompt="2")
    with pytest.raises(LLMError, match="rate limit: tenant t1 exceeded 2/min"):
        await call(c, prompt="3")
    await call(c, tenant="t2", prompt="3")  # other tenant unaffected


async def test_cache_hit_does_not_charge_limiter(tmp_path):
    c = client(tmp_path, Fake("a", GOOD), limiter=TenantLimiter(1))
    for _ in range(3):
        await call(c)


async def test_module_level_no_provider(tmp_path, monkeypatch):
    from git0.config import Settings
    from git0.llm import client as mod

    monkeypatch.setattr(mod, "_default", None)
    monkeypatch.setattr(
        mod,
        "get_settings",
        lambda: Settings(groq_api_key=None, gemini_api_key=None, llm_cache_dir=str(tmp_path)),
    )
    with pytest.raises(LLMError, match="no LLM provider configured"):
        await complete_json("p", Outer, system="s", tenant="t")


async def test_groq_provider_reads_real_sdk_response_types():
    from groq.types import CompletionUsage
    from groq.types.chat import ChatCompletion

    from git0.llm.client import GroqProvider

    resp = ChatCompletion.model_validate(
        {
            "id": "x", "created": 0, "model": "m", "object": "chat.completion",
            "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": GOOD}}],
            "usage": CompletionUsage(prompt_tokens=7, completion_tokens=5, total_tokens=12).model_dump(),
        }
    )  # fmt: skip

    class FakeCreate:
        async def create(self, **kw):
            assert kw["temperature"] == 0 and kw["response_format"]["json_schema"]["strict"] is True
            return resp

    p = GroqProvider("k", "m")
    p._client = type("C", (), {"chat": type("Ch", (), {"completions": FakeCreate()})()})()
    raw, usage = await p("s", "p", "Outer", strict_schema(Outer))
    assert raw == GOOD and (usage.prompt_tokens, usage.completion_tokens, usage.provider) == (7, 5, "groq")


async def test_gemini_provider_reads_real_sdk_response_types():
    from google.genai import types

    from git0.llm.client import GeminiProvider

    resp = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[types.Part(text=GOOD)]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=9, candidates_token_count=4
        ),
    )

    class FakeModels:
        async def generate_content(self, *, model, contents, config):
            assert (
                config.response_json_schema and config.system_instruction == "s" and config.temperature == 0
            )
            return resp

    p = GeminiProvider("k", "m")
    p._client = type("C", (), {"aio": type("A", (), {"models": FakeModels()})()})()
    raw, usage = await p("s", "p", "Outer", strict_schema(Outer))
    assert raw == GOOD and (usage.prompt_tokens, usage.completion_tokens, usage.provider) == (9, 4, "gemini")


@pytest.mark.llm
@pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"), reason="needs GROQ_API_KEY")
async def test_live_groq_smoke(tmp_path):
    from git0.config import get_settings
    from git0.llm.client import GroqProvider

    s = get_settings()
    c = client(tmp_path, GroqProvider(s.groq_api_key, s.groq_model))
    out, usage = await c.complete_json(
        "Alice owns the budget of 5k.", Inner, system="Extract.", tenant="live"
    )
    assert isinstance(out, Inner) and usage.prompt_tokens > 0
