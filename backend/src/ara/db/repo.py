"""`ReportsRepo` — every SQL query the API needs, behind one interface.

Two implementations: `ara.db.postgres` (hosted, asyncpg) and `ara.db.sqlite`
(local mode, aiosqlite). Routes, credentials and quota code talk only to
this Protocol, so neither backend leaks into HTTP handlers.

Time: month windows are computed here (`month_start`) and passed in as a
parameter, so both backends agree on the boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from uuid import UUID

Provider = Literal["anthropic", "openai", "tavily"]
ReportStatus = Literal["running", "completed", "error"]
Depth = Literal["quick", "standard", "deep"]


@dataclass(frozen=True)
class ReportRow:
    id: UUID
    owner_id: UUID
    question: str
    status: ReportStatus
    depth: Depth
    browse_web: bool
    used_byok: bool
    is_sample: bool
    share_token: UUID | None
    cost_usd: float | None
    report_payload: dict[str, Any] | None
    error_message: str | None
    tavily_searches: int
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True)
class CredentialRow:
    active_provider: str
    anthropic_key_ciphertext: str | None
    openai_key_ciphertext: str | None
    openai_base_url: str | None
    openai_model: str | None
    tavily_key_ciphertext: str | None


def month_start(now: datetime | None = None) -> datetime:
    current = now if now is not None else datetime.now(UTC)
    return current.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class ReportsRepo(Protocol):
    # ---- reports ----
    async def create_report(
        self,
        report_id: UUID,
        *,
        owner_id: UUID,
        question: str,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None: ...

    async def append_event(self, report_id: UUID, event_json: str) -> int: ...

    async def close_report(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None,
        report_payload_json: str | None,
        error_message: str | None,
        tavily_searches: int,
    ) -> None: ...

    async def get_report(self, report_id: UUID) -> ReportRow | None: ...
    async def list_reports(self, owner_id: UUID) -> list[ReportRow]: ...
    async def list_samples(self) -> list[ReportRow]: ...
    async def delete_report(self, report_id: UUID, owner_id: UUID) -> bool: ...
    async def ensure_share_token(
        self, report_id: UUID, owner_id: UUID, token: UUID
    ) -> UUID | None: ...
    async def revoke_share_token(self, report_id: UUID, owner_id: UUID) -> bool: ...
    async def set_sample(self, report_id: UUID, flag: bool) -> bool: ...
    async def replay_events(self, report_id: UUID) -> list[str]: ...
    async def events_since(
        self, report_id: UUID, after_id: int, limit: int | None = None
    ) -> list[tuple[int, str]]: ...

    # ---- credentials ----
    async def get_credentials(self, user_id: UUID) -> CredentialRow | None: ...
    async def upsert_anthropic(self, user_id: UUID, *, ciphertext: str) -> None: ...
    async def upsert_openai(
        self, user_id: UUID, *, ciphertext: str, base_url: str, model: str
    ) -> None: ...
    async def upsert_tavily(self, user_id: UUID, *, ciphertext: str) -> None: ...
    async def clear_provider(self, user_id: UUID, provider: Provider) -> None: ...
    async def set_active(self, user_id: UUID, provider: str) -> None: ...

    # ---- quotas ----
    async def count_free_runs(self, owner_id: UUID, *, since: datetime) -> int: ...
    async def sum_free_spend(self, *, since: datetime) -> float: ...
    async def sum_tavily(self, *, since: datetime) -> int: ...

    async def close(self) -> None: ...
