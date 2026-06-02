"""SupabaseReportStore — same Protocol contract as the in-memory store.

Requires a reachable Postgres with the 001_initial.sql migration applied.
Skip when SUPABASE_DB_URL is absent so local-without-DB still passes CI.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import asyncpg
import pytest

from ara.models.events import PlanReady, ResearcherStarted
from ara.models.research import Priority, ResearchPlan, SubQuery
from ara.storage.supabase import SupabaseReportStore
from tests.conftest import requires_db


def _plan(question: str = "q") -> ResearchPlan:
    sub_queries = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM)
        for i in range(3)
    ]
    return ResearchPlan(original_question=question, sub_queries=sub_queries)


@pytest.fixture
async def db_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(
        os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2
    )
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def store(db_pool: asyncpg.Pool) -> SupabaseReportStore:
    return SupabaseReportStore(pool=db_pool)


@pytest.fixture
async def fake_owner(db_pool: asyncpg.Pool) -> AsyncIterator[UUID]:
    """A throwaway auth.users row so reports.owner_id FK passes."""
    uid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            insert into auth.users (id, instance_id, aud, role, email,
                encrypted_password, email_confirmed_at, created_at, updated_at)
            values ($1, '00000000-0000-0000-0000-000000000000', 'authenticated',
                'authenticated', $2, '', now(), now(), now())
            """,
            uid,
            f"{uid}@test.local",
        )
    yield uid
    async with db_pool.acquire() as conn:
        await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_create_persists_metadata(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    rid = uuid4()
    await store.create(
        rid,
        "what is the airspeed of a swallow?",
        owner_id=fake_owner,
        depth="quick",
        browse_web=False,
        used_byok=False,
    )
    q = await store.get_question(rid)
    assert q == "what is the airspeed of a swallow?"


@requires_db
@pytest.mark.asyncio
async def test_subscribe_replays_then_lives(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    rid = uuid4()
    await store.create(
        rid,
        "q",
        owner_id=fake_owner,
        depth="quick",
        browse_web=False,
        used_byok=False,
    )

    plan = _plan()
    await store.put_event(rid, PlanReady(plan=plan))

    received: list[object] = []

    async def consume() -> None:
        async for ev in store.subscribe(rid):
            received.append(ev)
            if len(received) == 2:
                return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await store.put_event(
        rid,
        ResearcherStarted(
            sub_query_id=plan.sub_queries[0].id,
            question=plan.sub_queries[0].question,
        ),
    )
    await asyncio.wait_for(task, timeout=2.0)
    await store.close(rid, status="completed", cost_usd=0.0)

    assert len(received) == 2
    assert isinstance(received[0], PlanReady)
    assert isinstance(received[1], ResearcherStarted)
