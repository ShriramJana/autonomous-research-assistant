"""Runtime config — populated from the root `.env` (single source of truth)."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
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

    # Deployment mode. "local" = no auth, SQLite in ara_data_dir, loopback only.
    ara_mode: Literal["hosted", "local"] = "hosted"
    ara_data_dir: str = "~/.ara"
    ollama_base_url: str = "http://localhost:11434"

    @property
    def is_local(self) -> bool:
        return self.ara_mode == "local"

    @model_validator(mode="after")
    def _apply_local_mode(self) -> Settings:
        self.ara_data_dir = os.path.expanduser(self.ara_data_dir)
        if self.ara_mode == "local":
            # An unauthenticated app must never listen on a LAN address.
            self.ara_host = "127.0.0.1"
        return self

    # Researcher guardrails
    ara_researcher_max_iterations: int = 5
    ara_researcher_input_token_budget: int = 100_000

    # Per-report SSE ring buffer (reconnect continuity)
    ara_event_buffer_size: int = 50

    # Graceful shutdown: how long lifespan waits for in-flight research runs.
    # Keep below (k8s terminationGracePeriodSeconds - preStop sleep).
    ara_shutdown_drain_seconds: float = 100.0

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
