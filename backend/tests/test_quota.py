"""Free-tier quota — per-user count + global spend caps.

Runs against every `ReportsRepo` backend via `any_repo`: SQLite always,
Postgres when SUPABASE_DB_URL is set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ara.config import Settings
from ara.db import ReportsRepo
from ara.quota import QuotaDenial, QuotaOk, check_free_tier
from tests.conftest import drop_repo_user, new_repo_user


def _settings(per_user: int = 3, global_cap: float = 20.0) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.free_tier_per_user_monthly = per_user
    s.free_tier_global_cap_usd = global_cap
    return s


async def _free_run(repo: ReportsRepo, owner_id: UUID, cost_usd: float) -> None:
    rid = uuid4()
    await repo.create_report(
        rid, owner_id=owner_id, question="q", depth="quick", browse_web=False, used_byok=False
    )
    await repo.close_report(
        rid, status="completed", cost_usd=cost_usd, report_payload_json=None,
        error_message=None, tavily_searches=0,
    )


@pytest.fixture
async def users(any_repo: ReportsRepo) -> AsyncIterator[tuple[UUID, UUID]]:
    u1 = await new_repo_user(any_repo)
    u2 = await new_repo_user(any_repo)
    try:
        yield u1, u2
    finally:
        for u in (u1, u2):
            await drop_repo_user(any_repo, u)


async def test_quota_ok_when_fresh(any_repo: ReportsRepo, users: tuple[UUID, UUID]) -> None:
    uid, _ = users
    # Generous global cap: a shared Postgres DB may already hold free spend.
    status = await check_free_tier(uid, any_repo, _settings(global_cap=1e9))
    assert isinstance(status, QuotaOk)
    assert status.used == 0
    assert status.limit == 3


async def test_quota_denied_per_user(any_repo: ReportsRepo, users: tuple[UUID, UUID]) -> None:
    uid, _ = users
    for _ in range(3):
        await _free_run(any_repo, uid, cost_usd=0.05)
    status = await check_free_tier(uid, any_repo, _settings(global_cap=1e9))
    assert isinstance(status, QuotaDenial)
    assert status.reason == "free_tier_exhausted"
    assert status.used == 3


async def test_quota_denied_global_cap(any_repo: ReportsRepo, users: tuple[UUID, UUID]) -> None:
    u1, u2 = users
    for _ in range(5):
        await _free_run(any_repo, u1, cost_usd=5.0)
    status = await check_free_tier(u2, any_repo, _settings(global_cap=10.0))
    assert isinstance(status, QuotaDenial)
    assert status.reason == "free_tier_global_cap_reached"
    assert status.used == 0


async def test_byok_runs_do_not_count(any_repo: ReportsRepo, users: tuple[UUID, UUID]) -> None:
    uid, _ = users
    for _ in range(3):
        await any_repo.create_report(
            uuid4(), owner_id=uid, question="q", depth="quick", browse_web=False, used_byok=True
        )
    status = await check_free_tier(uid, any_repo, _settings(global_cap=1e9))
    assert isinstance(status, QuotaOk)
    assert status.used == 0


async def test_quota_window_comes_from_month_start(
    any_repo: ReportsRepo, users: tuple[UUID, UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    uid, _ = users
    for _ in range(3):
        await _free_run(any_repo, uid, cost_usd=5.0)
    future = datetime.now(UTC) + timedelta(days=1)
    monkeypatch.setattr("ara.quota.month_start", lambda: future)
    status = await check_free_tier(uid, any_repo, _settings(global_cap=10.0))
    assert isinstance(status, QuotaOk)
    assert status.used == 0 and status.global_spend_usd == 0.0
