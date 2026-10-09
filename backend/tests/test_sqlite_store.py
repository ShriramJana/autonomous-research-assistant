"""SqliteReportStore — persists events, fans out live events in-process."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ara.db.sqlite import SqliteReportsRepo
from ara.models.events import PlanReady, ResearcherStarted
from ara.models.research import Priority, ResearchPlan, SubQuery
from ara.storage.base import ReportStore
from ara.storage.sqlite import SqliteReportStore

OWNER = UUID("00000000-0000-4000-8000-000000000001")


def _plan() -> ResearchPlan:
    return ResearchPlan(
        original_question="q",
        sub_queries=[
            SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
        ],
    )


@pytest.fixture
async def repo(tmp_path: Path) -> AsyncIterator[SqliteReportsRepo]:
    r = await SqliteReportsRepo.open(str(tmp_path / "ara.db"))
    try:
        yield r
    finally:
        await r.close()


async def _create(store: SqliteReportStore) -> UUID:
    rid = uuid4()
    await store.create(rid, "q", owner_id=OWNER, depth="quick", browse_web=False, used_byok=False)
    return rid


async def test_satisfies_report_store_protocol(repo: SqliteReportsRepo) -> None:
    store: ReportStore = SqliteReportStore(repo)
    assert store is not None


async def test_replays_then_streams_live_then_terminates(repo: SqliteReportsRepo) -> None:
    store = SqliteReportStore(repo)
    rid = await _create(store)
    plan = _plan()
    await store.put_event(rid, PlanReady(plan=plan))
    received: list[object] = []

    async def consume() -> None:
        async for ev in store.subscribe(rid):
            received.append(ev)

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    started = ResearcherStarted(sub_query_id=plan.sub_queries[0].id, question="q0")
    await store.put_event(rid, started)
    await store.close(rid, status="completed", cost_usd=0.0)
    await asyncio.wait_for(task, timeout=2)
    assert [type(e).__name__ for e in received] == ["PlanReady", "ResearcherStarted"]


async def test_events_and_status_survive_reopen(tmp_path: Path) -> None:
    path = str(tmp_path / "ara.db")
    repo = await SqliteReportsRepo.open(path)
    store = SqliteReportStore(repo)
    rid = await _create(store)
    await store.put_event(rid, PlanReady(plan=_plan()))
    await store.close(rid, status="completed", cost_usd=0.1)
    await repo.close()

    repo2 = await SqliteReportsRepo.open(path)
    try:
        store2 = SqliteReportStore(repo2)
        events = [e async for e in store2.subscribe(rid)]
        assert len(events) == 1 and isinstance(events[0], PlanReady)
        row = await repo2.get_report(rid)
        assert row is not None and row.status == "completed"
        assert await store2.get_question(rid) == "q"
    finally:
        await repo2.close()


async def test_subscribe_unknown_report_yields_nothing(repo: SqliteReportsRepo) -> None:
    store = SqliteReportStore(repo)
    assert [e async for e in store.subscribe(uuid4())] == []


async def test_put_after_close_is_ignored(repo: SqliteReportsRepo) -> None:
    store = SqliteReportStore(repo)
    rid = await _create(store)
    await store.close(rid, status="error", error_message="x")
    await store.put_event(rid, PlanReady(plan=_plan()))
    assert await repo.replay_events(rid) == []


async def test_live_state_exists_before_row_is_written(
    repo: SqliteReportsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream request that sees the row must also find the live state."""
    store = SqliteReportStore(repo)
    rid = uuid4()
    seen: list[bool] = []
    original = repo.create_report

    async def spy(report_id: UUID, **kwargs: object) -> None:
        seen.append(store._live.get_state(report_id) is not None)
        await original(report_id, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(repo, "create_report", spy)
    await store.create(rid, "q", owner_id=OWNER, depth="quick", browse_web=False, used_byok=False)
    assert seen == [True]


INTERRUPTED = "Interrupted: the server stopped while this report was running"


async def test_startup_sweep_fails_orphaned_running_reports(tmp_path: Path) -> None:
    path = str(tmp_path / "ara.db")
    repo = await SqliteReportsRepo.open(path)
    store = SqliteReportStore(repo)
    orphan = await _create(store)
    await store.put_event(orphan, PlanReady(plan=_plan()))
    done = await _create(store)
    await store.close(done, status="completed", cost_usd=0.1)
    done_before = await repo.get_report(done)
    await repo.close()  # "crash": the orphan is never closed

    repo2 = await SqliteReportsRepo.open(path)
    try:
        assert await repo2.fail_running_reports(INTERRUPTED) == 1
        row = await repo2.get_report(orphan)
        assert row is not None
        assert row.status == "error"
        assert row.error_message == INTERRUPTED
        assert row.completed_at is not None
        assert await repo2.get_report(done) == done_before

        store2 = SqliteReportStore(repo2)

        async def drain() -> list[object]:
            return [e async for e in store2.subscribe(orphan)]

        events = await asyncio.wait_for(drain(), timeout=2)
        assert len(events) == 1 and isinstance(events[0], PlanReady)
        assert await repo2.fail_running_reports(INTERRUPTED) == 0
    finally:
        await repo2.close()


async def test_open_creates_owner_only_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "fresh"
    r = await SqliteReportsRepo.open(str(data_dir / "ara.db"))
    await r.close()
    assert data_dir.stat().st_mode & 0o777 == 0o700
