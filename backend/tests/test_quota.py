"""Free-tier quota — per-user count + global spend caps."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import asyncpg
import pytest

from ara.config import Settings
from ara.quota import QuotaDenial, QuotaOk, check_free_tier
from tests.conftest import requires_db


@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()


def _settings(per_user: int = 3, global_cap: float = 20.0) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.free_tier_per_user_monthly = per_user
    s.free_tier_global_cap_usd = global_cap
    return s


async def _insert_free_run(
    conn: asyncpg.Connection, owner_id: UUID, cost_usd: float, status: str = "completed"
) -> None:
    rid = uuid4()
    await conn.execute(
        """
        insert into reports
          (id, owner_id, question, status, depth, browse_web, used_byok, cost_usd)
        values ($1, $2, 'q', $3, 'quick', false, false, $4)
        """,
        rid, owner_id, status, cost_usd,
    )


async def _insert_user(conn: asyncpg.Connection) -> UUID:
    uid = uuid4()
    await conn.execute(
        """
        insert into auth.users (id, instance_id, aud, role, email,
            encrypted_password, email_confirmed_at, created_at, updated_at)
        values ($1, '00000000-0000-0000-0000-000000000000', 'authenticated',
            'authenticated', $2, '', now(), now(), now())
        """,
        uid, f"{uid}@test.local",
    )
    return uid


@requires_db
@pytest.mark.asyncio
async def test_quota_ok_when_fresh(db_pool) -> None:
    async with db_pool.acquire() as conn:
        uid = await _insert_user(conn)
        try:
            status = await check_free_tier(uid, db_pool, _settings())
            assert isinstance(status, QuotaOk)
            assert status.used == 0
            assert status.limit == 3
        finally:
            await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_quota_denied_per_user(db_pool) -> None:
    async with db_pool.acquire() as conn:
        uid = await _insert_user(conn)
        try:
            for _ in range(3):
                await _insert_free_run(conn, uid, cost_usd=0.05)
            status = await check_free_tier(uid, db_pool, _settings())
            assert isinstance(status, QuotaDenial)
            assert status.reason == "free_tier_exhausted"
        finally:
            await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_quota_denied_global_cap(db_pool) -> None:
    async with db_pool.acquire() as conn:
        u1 = await _insert_user(conn)
        u2 = await _insert_user(conn)
        try:
            for _ in range(5):
                await _insert_free_run(conn, u1, cost_usd=5.0)
            status = await check_free_tier(u2, db_pool, _settings(global_cap=10.0))
            assert isinstance(status, QuotaDenial)
            assert status.reason == "free_tier_global_cap_reached"
        finally:
            for u in (u1, u2):
                await conn.execute("delete from auth.users where id = $1", u)
