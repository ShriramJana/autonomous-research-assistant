"""Free-tier quota — per-user monthly count + global monthly spend cap.

Both numbers are derived from `reports` rows on each check. No counter
table to drift. If this ever becomes a hotspot, add an in-process 30s
TTL cache around `_count_user_runs` and `_sum_global_spend` — but ship
without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg

from ara.config import Settings


@dataclass(frozen=True)
class QuotaOk:
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float


@dataclass(frozen=True)
class QuotaDenial:
    reason: Literal["free_tier_exhausted", "free_tier_global_cap_reached"]
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float


QuotaStatus = QuotaOk | QuotaDenial


async def check_free_tier(
    user_id: UUID, pool: asyncpg.Pool, settings: Settings
) -> QuotaStatus:
    used = await _count_user_runs(user_id, pool)
    spend = await _sum_global_spend(pool)
    limit = settings.free_tier_per_user_monthly
    cap = settings.free_tier_global_cap_usd

    if used >= limit:
        return QuotaDenial(
            reason="free_tier_exhausted",
            used=used, limit=limit,
            global_spend_usd=spend, global_cap_usd=cap,
        )
    if spend >= cap:
        return QuotaDenial(
            reason="free_tier_global_cap_reached",
            used=used, limit=limit,
            global_spend_usd=spend, global_cap_usd=cap,
        )
    return QuotaOk(used=used, limit=limit, global_spend_usd=spend, global_cap_usd=cap)


async def _count_user_runs(user_id: UUID, pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select count(*)::int as n from reports
            where owner_id = $1
              and used_byok = false
              and created_at >= date_trunc('month', now())
            """,
            user_id,
        )
    return row["n"] if row else 0


async def _sum_global_spend(pool: asyncpg.Pool) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select coalesce(sum(cost_usd), 0)::float as s from reports
            where used_byok = false
              and created_at >= date_trunc('month', now())
            """,
        )
    return float(row["s"]) if row else 0.0
