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
from ara.storage.notify import EventDoorbell
from ara.storage.supabase import SupabaseReportStore
from tests.conftest import requires_db


def _plan(question: str = "q") -> ResearchPlan:
    sub_queries = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
    ]
    return ResearchPlan(original_question=question, sub_queries=sub_queries)


@pytest.fixture
async def db_pool() -> AsyncIterator[asyncpg.Pool]:
    pool = await asyncpg.create_pool(os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def doorbell() -> AsyncIterator[EventDoorbell]:
    url = os.environ["SUPABASE_DB_URL"]
    bell = EventDoorbell(lambda: asyncpg.connect(url))
    await bell.start()
    await asyncio.wait_for(bell.connected.wait(), timeout=15)
    try:
        yield bell
    finally:
        await bell.stop()


@pytest.fixture
async def store(db_pool: asyncpg.Pool, doorbell: EventDoorbell) -> SupabaseReportStore:
    return SupabaseReportStore(pool=db_pool, doorbell=doorbell)


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
async def test_create_persists_metadata(store: SupabaseReportStore, fake_owner: UUID) -> None:
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
async def test_subscribe_replays_then_lives(store: SupabaseReportStore, fake_owner: UUID) -> None:
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


@requires_db
@pytest.mark.asyncio
async def test_subscribe_no_duplicate_on_concurrent_put(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    """Regression: a put_event that interleaves with subscribe's replay
    SELECT must be delivered exactly once, not once from replay + once
    from the live queue."""
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
    # Pre-existing event so replay returns >=1 row.
    await store.put_event(rid, PlanReady(plan=plan))

    received: list[object] = []

    async def consume() -> None:
        async for ev in store.subscribe(rid):
            received.append(ev)
            if len(received) == 3:
                return

    # Subscribe and race a put_event into the same event-loop tick. The
    # subscribe() coroutine yields at its first `await` inside _replay_tail
    # (the SELECT); the put_event below runs in that window so both the
    # replay AND the live queue see it.
    task = asyncio.create_task(consume())
    await asyncio.sleep(0)  # let subscribe register its queue
    await store.put_event(
        rid,
        ResearcherStarted(
            sub_query_id=plan.sub_queries[0].id,
            question=plan.sub_queries[0].question,
        ),
    )
    # Drive a third event so the consumer's `len == 3` exit condition is
    # only reachable if the racing event was NOT double-delivered.
    await store.put_event(
        rid,
        ResearcherStarted(
            sub_query_id=plan.sub_queries[1].id,
            question=plan.sub_queries[1].question,
        ),
    )
    await asyncio.wait_for(task, timeout=2.0)
    await store.close(rid, status="completed", cost_usd=0.0)

    assert len(received) == 3
    assert isinstance(received[0], PlanReady)
    started = [ev for ev in received if isinstance(ev, ResearcherStarted)]
    # Two distinct ResearcherStarted events, each delivered exactly once.
    assert len(started) == 2
    assert {ev.sub_query_id for ev in started} == {
        plan.sub_queries[0].id,
        plan.sub_queries[1].id,
    }


async def _new_report(store: SupabaseReportStore, owner: UUID) -> UUID:
    rid = uuid4()
    await store.create(rid, "q", owner_id=owner, depth="quick", browse_web=False, used_byok=False)
    return rid


async def _collect(store: SupabaseReportStore, rid: UUID) -> list[object]:
    return [ev async for ev in store.subscribe(rid)]


@requires_db
@pytest.mark.asyncio
async def test_cross_store_delivery_in_order_then_terminates(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    """Pod B streams what pod A writes. B's poll interval is huge, so only
    the NOTIFY doorbell can deliver within the timeout."""
    url = os.environ["SUPABASE_DB_URL"]
    pool_b = await asyncpg.create_pool(url, min_size=1, max_size=2)
    bell_b = EventDoorbell(lambda: asyncpg.connect(url))
    await bell_b.start()
    await asyncio.wait_for(bell_b.connected.wait(), timeout=15)
    store_b = SupabaseReportStore(pool=pool_b, doorbell=bell_b, poll_interval=60)
    try:
        rid = await _new_report(store, fake_owner)
        plan = _plan()
        task = asyncio.create_task(_collect(store_b, rid))
        await asyncio.sleep(0.3)  # let B replay (empty) and park on the doorbell
        await store.put_event(rid, PlanReady(plan=plan))
        for sq in plan.sub_queries:
            await store.put_event(rid, ResearcherStarted(sub_query_id=sq.id, question=sq.question))
        await store.close(rid, status="completed", cost_usd=0.0)
        received = await asyncio.wait_for(task, timeout=15)
    finally:
        await bell_b.stop()
        await pool_b.close()

    assert isinstance(received[0], PlanReady)
    started = received[1:]
    assert all(isinstance(ev, ResearcherStarted) for ev in started)
    assert [ev.sub_query_id for ev in started] == [  # type: ignore[attr-defined]
        sq.id for sq in plan.sub_queries
    ]


@requires_db
@pytest.mark.asyncio
async def test_concurrent_puts_all_delivered_once(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    """Parallel researchers write to one report at once. Without the
    per-report write lock a later id can commit first and an earlier one
    gets skipped by the `id > last_id` cursor."""
    rid = await _new_report(store, fake_owner)
    task = asyncio.create_task(_collect(store, rid))
    await asyncio.sleep(0.3)
    events = [ResearcherStarted(sub_query_id=uuid4(), question=f"q{i}") for i in range(20)]
    await asyncio.gather(*(store.put_event(rid, ev) for ev in events))
    await store.close(rid, status="completed", cost_usd=0.0)
    received = await asyncio.wait_for(task, timeout=15)

    ids = [ev.sub_query_id for ev in received]  # type: ignore[attr-defined]
    assert len(ids) == 20
    assert set(ids) == {ev.sub_query_id for ev in events}


@requires_db
@pytest.mark.asyncio
async def test_poll_fallback_without_doorbell(
    db_pool: asyncpg.Pool, store: SupabaseReportStore, fake_owner: UUID
) -> None:
    """A subscriber whose doorbell never connects still gets everything."""

    async def never_connects() -> object:
        raise OSError("listener unavailable")

    dead_bell = EventDoorbell(never_connects)  # never started
    polling = SupabaseReportStore(pool=db_pool, doorbell=dead_bell, poll_interval=0.1)
    rid = await _new_report(store, fake_owner)
    task = asyncio.create_task(_collect(polling, rid))
    await asyncio.sleep(0.2)
    await store.put_event(rid, PlanReady(plan=_plan()))
    await store.close(rid, status="completed", cost_usd=0.0)
    received = await asyncio.wait_for(task, timeout=5)
    assert len(received) == 1
    assert isinstance(received[0], PlanReady)


@requires_db
@pytest.mark.asyncio
async def test_subscribe_after_close_replays_and_ends(
    store: SupabaseReportStore, fake_owner: UUID
) -> None:
    rid = await _new_report(store, fake_owner)
    await store.put_event(rid, PlanReady(plan=_plan()))
    await store.close(rid, status="completed", cost_usd=0.0)
    received = await asyncio.wait_for(_collect(store, rid), timeout=5)
    assert len(received) == 1


@requires_db
@pytest.mark.asyncio
async def test_subscribe_unknown_report_ends_immediately(
    store: SupabaseReportStore,
) -> None:
    received = await asyncio.wait_for(_collect(store, uuid4()), timeout=5)
    assert received == []
