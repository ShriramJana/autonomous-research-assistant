"""Encrypted per-user provider credentials + Tavily usage accounting.

Thin domain layer over `ReportsRepo`: business rules live here (e.g. you
cannot activate a provider that isn't configured); SQL lives in `ara.db`.
Ciphertext only — decryption happens in the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from ara.config import Settings
from ara.db import ReportsRepo, month_start


class CredentialError(Exception):
    """Domain error — e.g. activating a provider that isn't configured."""


@dataclass(frozen=True)
class CredentialRecord:
    active_provider: str
    anthropic_key_ciphertext: str | None
    openai_key_ciphertext: str | None
    openai_base_url: str | None
    openai_model: str | None
    tavily_key_ciphertext: str | None


@dataclass(frozen=True)
class TavilyCapStatus:
    used: int
    cap: int

    @property
    def reached(self) -> bool:
        return self.used >= self.cap


async def get_credentials(user_id: UUID, repo: ReportsRepo) -> CredentialRecord | None:
    row = await repo.get_credentials(user_id)
    if row is None:
        return None
    return CredentialRecord(
        active_provider=row.active_provider,
        anthropic_key_ciphertext=row.anthropic_key_ciphertext,
        openai_key_ciphertext=row.openai_key_ciphertext,
        openai_base_url=row.openai_base_url,
        openai_model=row.openai_model,
        tavily_key_ciphertext=row.tavily_key_ciphertext,
    )


async def upsert_anthropic(user_id: UUID, repo: ReportsRepo, *, ciphertext: str) -> None:
    await repo.upsert_anthropic(user_id, ciphertext=ciphertext)


async def upsert_openai(
    user_id: UUID, repo: ReportsRepo, *, ciphertext: str, base_url: str, model: str
) -> None:
    await repo.upsert_openai(user_id, ciphertext=ciphertext, base_url=base_url, model=model)


async def upsert_tavily(user_id: UUID, repo: ReportsRepo, *, ciphertext: str) -> None:
    await repo.upsert_tavily(user_id, ciphertext=ciphertext)


async def clear_anthropic(user_id: UUID, repo: ReportsRepo) -> None:
    await repo.clear_provider(user_id, "anthropic")


async def clear_openai(user_id: UUID, repo: ReportsRepo) -> None:
    await repo.clear_provider(user_id, "openai")


async def clear_tavily(user_id: UUID, repo: ReportsRepo) -> None:
    await repo.clear_provider(user_id, "tavily")


async def set_active(user_id: UUID, repo: ReportsRepo, *, provider: str) -> None:
    if provider == "free":
        await repo.set_active(user_id, "free")
        return
    rec = await get_credentials(user_id, repo)
    configured = rec is not None and (
        (provider == "anthropic" and rec.anthropic_key_ciphertext is not None)
        or (provider == "openai" and rec.openai_key_ciphertext is not None)
    )
    if not configured:
        raise CredentialError(f"{provider} is not configured")
    await repo.set_active(user_id, provider)


async def check_tavily_cap(repo: ReportsRepo, settings: Settings) -> TavilyCapStatus:
    used = await repo.sum_tavily(since=month_start())
    return TavilyCapStatus(used=used, cap=settings.tavily_global_monthly_cap)
