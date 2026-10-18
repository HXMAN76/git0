import os
import tempfile
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_template_dir() -> str:
    # config.py lives at <root>/src/git0/config.py, so parents[2] is the repo root (local dev) and
    # /app in the Docker image (the Dockerfile copies demo_project/ to /app/demo_project).
    local = Path(__file__).resolve().parents[2] / "demo_project"
    if local.is_dir():
        return str(local)
    return "/app/demo_project"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    falkordb_url: str = "redis://localhost:6379"
    tenant_graph_prefix: str = "team_"
    tenant_ttl_seconds: int = 7200  # rooms idle longer than this are deleted by the sweep (#30)
    max_rooms: int = 300  # ~1.7 MB per room: 300 rooms is ~0.6 GB of the t3.small's ~1 GB room budget
    pinned_tenants: list[str] = ["demo"]  # never swept: the shared link for judges and the video
    sweep_interval_s: int = 600

    groq_api_key: str | None = None
    groq_model: str = "openai/gpt-oss-20b"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.1-flash-lite"
    # Fallback chain tried in order when the primary gemini_model returns 503.
    # Each entry creates an independent GeminiProvider; first success wins.
    gemini_fallback_models: list[str] = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]
    llm_cache_dir: str = ".cache/llm"
    llm_offline: bool = False  # LLM_OFFLINE=1: serve cached extractions only (demo safety net)
    llm_tenant_rpm: int = 20  # per-tenant LLM calls/min so one judge cannot burn the shared quota
    llm_timeout_s: float = 20  # per-provider call timeout so a stalled Groq falls back to Gemini fast

    cors_origins: list[str] = ["http://localhost:5173"]

    # --- Relay IDE demo (git0/ide). Each visitor session gets its own graph ide_<sid> and workspaces. ---
    # Gemini free tier allows 15 requests/min PER MODEL, so each agent gets its own primary and the chain
    # spreads a busy turn over the pool. Agent A uses ide_model, agent B uses ide_model_b.
    ide_model: str = "gemini-3.1-flash-lite"
    ide_model_b: str = "gemini-3.5-flash-lite"
    ide_model_pool: list[str] = [
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
    ]
    ide_rate_limit_max_wait_s: float = 40  # longest pause for a 429 (the API's retryDelay is capped to this)
    ide_rate_limit_retries: int = 4  # retries after a 429 once every model in the chain is rate limited
    ide_max_sessions: int = 8  # live demo sessions; more gets 503 "Demo is busy"
    ide_session_ttl_s: int = 900  # idle sessions (no API calls) are ended after this
    ide_disconnect_grace_s: int = 120  # ended when no SSE subscriber has been attached for this long
    ide_max_turns_per_agent: int = 8  # user messages per agent per session
    ide_workspace_root: str = str(Path(tempfile.gettempdir()) / "git0-ide")
    ide_mcp_url: str | None = None  # None: http://127.0.0.1:{PORT}/mcp/ (the MCP app mounted in this process)
    ide_template_dir: str = _default_template_dir()

    @property
    def effective_ide_mcp_url(self) -> str:
        if self.ide_mcp_url:
            return self.ide_mcp_url
        return f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/mcp/"


@lru_cache
def get_settings() -> Settings:
    return Settings()
