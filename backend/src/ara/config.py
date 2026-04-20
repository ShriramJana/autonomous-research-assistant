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

    # Anthropic
    anthropic_api_key: str = Field(default="")
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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ara_cors_origins.split(",") if o.strip()]


def get_settings() -> Settings:
    return Settings()
