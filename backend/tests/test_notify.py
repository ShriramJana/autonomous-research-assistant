"""EventDoorbell — LISTEN dispatcher unit tests (no database)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

from ara.storage.notify import CHANNEL, EventDoorbell


class FakeConn:
    """Mimics the slice of asyncpg.Connection the doorbell uses."""

    def __init__(self) -> None:
        self.listeners: dict[str, Callable[..., None]] = {}
        self.termination: list[Callable[[Any], None]] = []
        self.closed = False

    async def add_listener(self, channel: str, cb: Callable[..., None]) -> None:
        self.listeners[channel] = cb

    def add_termination_listener(self, cb: Callable[[Any], None]) -> None:
        self.termination.append(cb)

    async def close(self) -> None:
        self.closed = True

    def terminate(self) -> None:
        """Simulate the server dropping the connection."""
        for cb in self.termination:
            cb(self)

    def notify(self, payload: str) -> None:
        self.listeners[CHANNEL](self, 1234, CHANNEL, payload)


def connector(conns: list[FakeConn]) -> Callable[[], Awaitable[FakeConn]]:
    it = iter(conns)

    async def connect() -> FakeConn:
        return next(it)

    return connect


async def _until(cond: Callable[[], bool], timeout: float = 1.0) -> None:
    for _ in range(int(timeout / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


async def test_dispatch_sets_registered_events_only() -> None:
    bell = EventDoorbell(connector([]))
    a, b = uuid4(), uuid4()
    ev_a = bell.register(a)
    ev_b = bell.register(b)
    bell.dispatch(str(a))
    assert ev_a.is_set()
    assert not ev_b.is_set()


async def test_dispatch_wakes_every_subscriber_of_a_report() -> None:
    bell = EventDoorbell(connector([]))
    rid = uuid4()
    first, second = bell.register(rid), bell.register(rid)
    bell.dispatch(str(rid))
    assert first.is_set() and second.is_set()


async def test_dispatch_ignores_unknown_and_malformed() -> None:
    bell = EventDoorbell(connector([]))
    ev = bell.register(uuid4())
    bell.dispatch(str(uuid4()))
    bell.dispatch("not-a-uuid")
    bell.dispatch("")
    assert not ev.is_set()


async def test_unregister_stops_delivery() -> None:
    bell = EventDoorbell(connector([]))
    rid = uuid4()
    ev = bell.register(rid)
    bell.unregister(rid, ev)
    bell.unregister(rid, ev)  # idempotent
    bell.dispatch(str(rid))
    assert not ev.is_set()


async def test_start_listens_and_routes_notifications() -> None:
    conn = FakeConn()
    bell = EventDoorbell(connector([conn]))
    await bell.start()
    await asyncio.wait_for(bell.connected.wait(), 1.0)
    rid = uuid4()
    ev = bell.register(rid)
    conn.notify(str(rid))
    assert ev.is_set()
    await bell.stop()
    assert conn.closed
    assert not bell.connected.is_set()


async def test_reconnects_after_connection_lost_and_wakes_all() -> None:
    c1, c2 = FakeConn(), FakeConn()
    bell = EventDoorbell(connector([c1, c2]), initial_backoff=0.01)
    await bell.start()
    await asyncio.wait_for(bell.connected.wait(), 1.0)
    ev = bell.register(uuid4())
    c1.terminate()
    await _until(lambda: CHANNEL in c2.listeners)
    await asyncio.wait_for(bell.connected.wait(), 1.0)
    # Waiters are woken so they re-read anything missed while disconnected.
    assert ev.is_set()
    await bell.stop()
    assert c2.closed


async def test_connect_failure_is_retried() -> None:
    calls = 0
    conn = FakeConn()

    async def flaky() -> FakeConn:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("connection refused")
        return conn

    bell = EventDoorbell(flaky, initial_backoff=0.01)
    await bell.start()
    await asyncio.wait_for(bell.connected.wait(), 1.0)
    assert calls == 2
    await bell.stop()


async def test_stop_closes_connection_mid_add_listener() -> None:
    """Regression: stop() must close conn even if add_listener is still awaiting."""
    block_event = asyncio.Event()

    class BlockingConn(FakeConn):
        async def add_listener(self, channel: str, cb: Callable[..., None]) -> None:
            # Block forever, simulating slow add_listener
            await block_event.wait()

    conn = BlockingConn()
    bell = EventDoorbell(connector([conn]))
    await bell.start()
    # Wait for connect() to return (but add_listener is still blocking)
    await _until(lambda: bell._conn is conn)
    # Now stop() should close the connection even though add_listener didn't complete
    await bell.stop()
    assert conn.closed
    assert not bell.connected.is_set()
