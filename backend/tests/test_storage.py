"""Unit tests for `InMemoryReportStore`.

Covers: create/get, buffered replay on subscribe, live event fan-out,
ring-buffer eviction, close() terminates subscribers, concurrent
subscribers, post-close subscription replays tail only.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from ara.models.events import PlanReady, SynthesisToken
from ara.models.research import Priority, ResearchPlan, SubQuery
from ara.storage.memory import InMemoryReportStore
from tests._store_helpers import create_test_report


def _plan(question: str = "q") -> PlanReady:
    sub_queries = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
    ]
    return PlanReady(plan=ResearchPlan(original_question=question, sub_queries=sub_queries))


def _token(s: str) -> SynthesisToken:
    return SynthesisToken(token=s)


async def test_create_and_get_question() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "the question")
    assert await store.get_question(rid) == "the question"


async def test_get_question_missing_report() -> None:
    store = InMemoryReportStore()
    assert await store.get_question(uuid4()) is None


async def test_subscribe_to_unknown_report_yields_nothing() -> None:
    store = InMemoryReportStore()
    events = [e async for e in store.subscribe(uuid4())]
    assert events == []


async def test_buffered_events_replay_on_subscribe() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")
    await store.put_event(rid, _token("a"))
    await store.put_event(rid, _token("b"))
    await store.put_event(rid, _token("c"))
    await store.close(rid, status="completed")

    events = [e async for e in store.subscribe(rid)]
    tokens = [e.token for e in events if isinstance(e, SynthesisToken)]
    assert tokens == ["a", "b", "c"]


async def test_live_events_stream_to_subscriber() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")

    received: list[str] = []

    async def consumer() -> None:
        async for event in store.subscribe(rid):
            if isinstance(event, SynthesisToken):
                received.append(event.token)
                if event.token == "done":
                    return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)  # let consumer subscribe
    await store.put_event(rid, _token("hello"))
    await store.put_event(rid, _token("world"))
    await store.put_event(rid, _token("done"))
    await asyncio.wait_for(task, timeout=1.0)
    assert received == ["hello", "world", "done"]


async def test_ring_buffer_evicts_oldest() -> None:
    store = InMemoryReportStore(buffer_size=3)
    rid = uuid4()
    await create_test_report(store, rid, "q")
    for s in ["a", "b", "c", "d", "e"]:
        await store.put_event(rid, _token(s))
    await store.close(rid, status="completed")

    events = [e async for e in store.subscribe(rid)]
    tokens = [e.token for e in events if isinstance(e, SynthesisToken)]
    assert tokens == ["c", "d", "e"]


async def test_close_terminates_live_subscriber() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")

    async def consumer() -> list[str]:
        out: list[str] = []
        async for event in store.subscribe(rid):
            if isinstance(event, SynthesisToken):
                out.append(event.token)
        return out

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0)
    await store.put_event(rid, _token("x"))
    await store.close(rid, status="completed")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == ["x"]


async def test_concurrent_subscribers_both_see_all_events() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")

    async def consumer() -> list[str]:
        out: list[str] = []
        async for event in store.subscribe(rid):
            if isinstance(event, SynthesisToken):
                out.append(event.token)
        return out

    t1 = asyncio.create_task(consumer())
    t2 = asyncio.create_task(consumer())
    await asyncio.sleep(0)

    for s in ["a", "b", "c"]:
        await store.put_event(rid, _token(s))
    await store.close(rid, status="completed")

    r1, r2 = await asyncio.wait_for(asyncio.gather(t1, t2), timeout=1.0)
    assert r1 == ["a", "b", "c"]
    assert r2 == ["a", "b", "c"]


async def test_reconnect_midstream_replays_buffer_then_lives() -> None:
    store = InMemoryReportStore(buffer_size=50)
    rid = uuid4()
    await create_test_report(store, rid, "q")

    # First client gets a few events then drops
    await store.put_event(rid, _token("1"))
    await store.put_event(rid, _token("2"))

    # Reconnecting client subscribes mid-stream
    async def reconnect_consumer() -> list[str]:
        out: list[str] = []
        async for event in store.subscribe(rid):
            if isinstance(event, SynthesisToken):
                out.append(event.token)
        return out

    task = asyncio.create_task(reconnect_consumer())
    await asyncio.sleep(0)
    await store.put_event(rid, _token("3"))
    await store.close(rid, status="completed")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == ["1", "2", "3"]


async def test_put_after_close_is_silently_dropped() -> None:
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")
    await store.close(rid, status="completed")
    await store.put_event(rid, _token("late"))  # must not raise
    events = [e async for e in store.subscribe(rid)]
    assert events == []


async def test_plan_ready_event_roundtrips() -> None:
    """Buffer holds the discriminated-union event intact."""
    store = InMemoryReportStore()
    rid = uuid4()
    await create_test_report(store, rid, "q")
    await store.put_event(rid, _plan("q"))
    await store.close(rid, status="completed")

    events = [e async for e in store.subscribe(rid)]
    assert len(events) == 1
    assert isinstance(events[0], PlanReady)
    assert events[0].plan.original_question == "q"
