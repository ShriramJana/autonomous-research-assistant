"""drain_tasks — wait for in-flight research runs on shutdown."""

from __future__ import annotations

import asyncio

import pytest

from ara.config import Settings
from ara.shutdown import drain_tasks


async def test_no_tasks_returns_zero() -> None:
    assert await drain_tasks(set(), timeout=1.0) == (0, 0)


async def test_waits_for_tasks_that_finish_in_time() -> None:
    task = asyncio.create_task(asyncio.sleep(0.05))
    assert await drain_tasks({task}, timeout=2.0) == (1, 0)
    assert task.done() and not task.cancelled()


async def test_cancels_tasks_that_exceed_the_timeout() -> None:
    slow = asyncio.create_task(asyncio.sleep(10))
    quick = asyncio.create_task(asyncio.sleep(0.01))
    assert await drain_tasks({slow, quick}, timeout=0.2) == (1, 1)
    assert slow.cancelled()


async def test_zero_timeout_abandons_everything_pending() -> None:
    slow = asyncio.create_task(asyncio.sleep(10))
    assert await drain_tasks({slow}, timeout=0) == (0, 1)
    assert slow.cancelled()


async def test_live_set_mutation_during_drain_is_safe() -> None:
    """app.state.tasks discards finished tasks via a done-callback."""
    tasks: set[asyncio.Task[None]] = set()
    task = asyncio.create_task(asyncio.sleep(0.05))
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    assert await drain_tasks(tasks, timeout=2.0) == (1, 0)


def test_drain_setting_default_and_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARA_SHUTDOWN_DRAIN_SECONDS", raising=False)
    assert Settings().ara_shutdown_drain_seconds == 100.0
    monkeypatch.setenv("ARA_SHUTDOWN_DRAIN_SECONDS", "7.5")
    assert Settings().ara_shutdown_drain_seconds == 7.5
