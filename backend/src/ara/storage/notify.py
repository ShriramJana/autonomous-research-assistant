"""Cross-process "doorbell" for live report events (Postgres LISTEN/NOTIFY).

A NOTIFY on ``ara_events`` carries only the report id. Subscribers react by
re-reading ``report_events`` from the database, which stays the single source
of truth. The payload is deliberately tiny: Postgres caps NOTIFY payloads at
8000 bytes and a ``report_complete`` event carries the whole report.

One dedicated connection per process listens; it is not taken from the pool
because a pooled connection would be returned (and its LISTEN lost). If the
connection drops, the doorbell reconnects with exponential backoff and wakes
every waiter so they re-read anything missed. Subscribers also poll on a
timeout, so a dead listener degrades latency, never correctness.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)

CHANNEL = "ara_events"

Connector = Callable[[], Awaitable[Any]]


class EventDoorbell:
    def __init__(
        self,
        connect: Connector,
        *,
        initial_backoff: float = 1.0,
        max_backoff: float = 30.0,
    ) -> None:
        self._connect = connect
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff
        self._waiters: dict[UUID, set[asyncio.Event]] = {}
        self._task: asyncio.Task[None] | None = None
        self._conn: Any = None
        self.connected = asyncio.Event()

    # ---- waiter registry -------------------------------------------------

    def register(self, report_id: UUID) -> asyncio.Event:
        event = asyncio.Event()
        self._waiters.setdefault(report_id, set()).add(event)
        return event

    def unregister(self, report_id: UUID, event: asyncio.Event) -> None:
        waiters = self._waiters.get(report_id)
        if waiters is None:
            return
        waiters.discard(event)
        if not waiters:
            del self._waiters[report_id]

    def dispatch(self, payload: str) -> None:
        try:
            report_id = UUID(payload)
        except ValueError:
            return
        for event in self._waiters.get(report_id, ()):
            event.set()

    def wake_all(self) -> None:
        for waiters in self._waiters.values():
            for event in waiters:
                event.set()

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        conn, self._conn = self._conn, None
        if conn is not None:
            await conn.close()
        self.connected.clear()

    def _on_notify(self, _conn: Any, _pid: int, _channel: str, payload: str) -> None:
        self.dispatch(payload)

    async def _run(self) -> None:
        backoff = self._initial_backoff
        while True:
            conn: Any = None
            lost = asyncio.Event()
            try:
                conn = await self._connect()
                conn.add_termination_listener(lambda _c, e=lost: e.set())
                await conn.add_listener(CHANNEL, self._on_notify)
            except Exception:
                logger.warning(
                    "event doorbell: connect failed; retrying in %.1fs",
                    backoff,
                    exc_info=True,
                )
                if conn is not None:
                    with contextlib.suppress(Exception):
                        await conn.close()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self._max_backoff)
                continue

            self._conn = conn
            backoff = self._initial_backoff
            self.connected.set()
            self.wake_all()
            logger.info("event doorbell: listening on %s", CHANNEL)

            await lost.wait()

            self._conn = None
            self.connected.clear()
            logger.warning("event doorbell: connection lost; reconnecting")
            self.wake_all()
            await asyncio.sleep(backoff)
