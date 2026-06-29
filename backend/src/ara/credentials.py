"""Encrypted per-user provider credentials + Tavily usage accounting.

asyncpg-backed (style of `quota.py`). The store returns ciphertext +
non-secret metadata; decryption happens in the resolver, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from ara.config import Settings


class CredentialError(Exception):
    """Domain error — e.g. activating a provider that isn't configured."""


@dataclass(frozen=True)
class CredentialRecord:
    active_provider: str
    anthropic_key_ciphertext: str | None
    openai_key_ciphertext: str | None
    openai_base_url: str | None
    openai_model: str | None


@dataclass(frozen=True)
class TavilyCapStatus:
    used: int
    cap: int

    @property
    def reached(self) -> bool:
        return self.used >= self.cap


async def get_credentials(user_id: UUID, pool: asyncpg.Pool) -> CredentialRecord | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select * from user_credentials where user_id = $1", user_id
        )
    if row is None:
        return None
    return CredentialRecord(
        active_provider=row["active_provider"],
        anthropic_key_ciphertext=row["anthropic_key_ciphertext"],
        openai_key_ciphertext=row["openai_key_ciphertext"],
        openai_base_url=row["openai_base_url"],
        openai_model=row["openai_model"],
    )


async def upsert_anthropic(user_id: UUID, pool: asyncpg.Pool, *, ciphertext: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials (user_id, anthropic_key_ciphertext, updated_at)
            values ($1, $2, now())
            on conflict (user_id) do update
              set anthropic_key_ciphertext = excluded.anthropic_key_ciphertext,
                  updated_at = now()
            """,
            user_id, ciphertext,
        )


async def upsert_openai(
    user_id: UUID, pool: asyncpg.Pool, *, ciphertext: str, base_url: str, model: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials
              (user_id, openai_key_ciphertext, openai_base_url, openai_model, updated_at)
            values ($1, $2, $3, $4, now())
            on conflict (user_id) do update
              set openai_key_ciphertext = excluded.openai_key_ciphertext,
                  openai_base_url = excluded.openai_base_url,
                  openai_model = excluded.openai_model,
                  updated_at = now()
            """,
            user_id, ciphertext, base_url, model,
        )


async def clear_anthropic(user_id: UUID, pool: asyncpg.Pool) -> None:
    await _clear(user_id, pool, columns=["anthropic_key_ciphertext"], provider="anthropic")


async def clear_openai(user_id: UUID, pool: asyncpg.Pool) -> None:
    await _clear(
        user_id, pool,
        columns=["openai_key_ciphertext", "openai_base_url", "openai_model"],
        provider="openai",
    )


async def _clear(
    user_id: UUID, pool: asyncpg.Pool, *, columns: list[str], provider: str
) -> None:
    sets = ", ".join(f"{c} = null" for c in columns)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            update user_credentials
            set {sets},
                active_provider = case when active_provider = $2 then 'free'
                                       else active_provider end,
                updated_at = now()
            where user_id = $1
            """,
            user_id, provider,
        )


async def set_active(user_id: UUID, pool: asyncpg.Pool, *, provider: str) -> None:
    if provider == "free":
        await _force_active(user_id, pool, provider="free")
        return
    rec = await get_credentials(user_id, pool)
    configured = rec is not None and (
        (provider == "anthropic" and rec.anthropic_key_ciphertext is not None)
        or (provider == "openai" and rec.openai_key_ciphertext is not None)
    )
    if not configured:
        raise CredentialError(f"{provider} is not configured")
    await _force_active(user_id, pool, provider=provider)


async def _force_active(user_id: UUID, pool: asyncpg.Pool, *, provider: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials (user_id, active_provider, updated_at)
            values ($1, $2, now())
            on conflict (user_id) do update
              set active_provider = excluded.active_provider, updated_at = now()
            """,
            user_id, provider,
        )


async def check_tavily_cap(pool: asyncpg.Pool, settings: Settings) -> TavilyCapStatus:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select coalesce(sum(tavily_searches), 0)::int as n from reports
            where created_at >= date_trunc('month', now())
            """,
        )
    used = row["n"] if row else 0
    return TavilyCapStatus(used=used, cap=settings.tavily_global_monthly_cap)
