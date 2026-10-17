from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    falkordb_url: str = "redis://localhost:6379"
    tenant_graph_prefix: str = "team_"
    tenant_ttl_seconds: int = 7200

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.8-flash"
    llm_cache_dir: str = ".cache/llm"
    llm_offline: bool = False  # LLM_OFFLINE=1: serve cached extractions only (demo safety net)
    llm_tenant_rpm: int = 20  # per-tenant LLM calls/min so one judge cannot burn the shared quota
    llm_timeout_s: float = 20  # per-provider call timeout so a stalled Groq falls back to Gemini fast

    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
