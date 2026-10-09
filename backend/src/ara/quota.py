"""Free-tier quota — per-user monthly count + global monthly spend cap.

Both numbers are derived from `reports` rows on each check (via
`ReportsRepo`). No counter table to drift. The month window comes from
`month_start()` so every backend agrees on the boundary. If this ever
becomes a hotspot, add an in-process 30s TTL cache around the two repo
calls — but ship without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from ara.config import Settings
from ara.db import ReportsRepo, month_start


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


async def check_free_tier(user_id: UUID, repo: ReportsRepo, settings: Settings) -> QuotaStatus:
    since = month_start()
    used = await repo.count_free_runs(user_id, since=since)
    spend = await repo.sum_free_spend(since=since)
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
