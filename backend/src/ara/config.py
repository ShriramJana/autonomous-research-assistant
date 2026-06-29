"""Runtime config — populated from the root `.env` (single source of truth)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Anthropic — `anthropic_api_key` is the server-side free-tier key.
    anthropic_api_key: str = Field(default="")

    # Tavily (server-provided client-side search for non-Anthropic providers)
    tavily_api_key: str = Field(default="")
    tavily_global_monthly_cap: int = 1000
    claude_planner_model: str = "claude-sonnet-4-5"
    claude_researcher_model: str = "claude-sonnet-4-5"
    claude_synthesizer_model: str = "claude-opus-4-5"

    # Server
    ara_host: str = "0.0.0.0"
    ara_port: int = 8000
    ara_cors_origins: str = "http://localhost:3000"

    # Researcher guardrails
    ara_researcher_max_iterations: int = 5
    ara_researcher_input_token_budget: int = 100_000

    # Per-report SSE ring buffer (reconnect continuity)
    ara_event_buffer_size: int = 50

    # Supabase (auth + persistence)
    supabase_url: str = Field(default="")
    supabase_db_url: str = Field(default="")
    admin_user_id: str | None = Field(default=None)

    # Free tier
    free_tier_per_user_monthly: int = 3
    free_tier_global_cap_usd: float = 20.0

    # Credential storage (Fernet key for encrypting saved provider keys)
    ara_encryption_key: str = Field(default="")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ara_cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
