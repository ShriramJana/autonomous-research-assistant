"""Postgres-backed ReportStore using asyncpg.

Persistence per Protocol method:
- create:    INSERT into reports
- put_event: INSERT into report_events + pg_notify('ara_events', report_id)
- subscribe: replay the last N events, then re-read rows newer than the
             last seen id whenever the doorbell rings (or every
             ``poll_interval`` seconds), until the report is closed
- close:     UPDATE reports (status, cost, payload, completed_at) + pg_notify

Why a doorbell and not in-process queues: any backend replica may serve a
report's SSE stream, but only the replica running the research writes its
events. NOTIFY reaches every replica; the payload is just the report id and
``report_events`` stays the source of truth (see ``ara.storage.notify``).

Ordering: researchers run in parallel, so two put_events for one report can
be in flight at once. Ids are assigned at INSERT but become visible at
COMMIT; if id 11 committed before id 10, a subscriber would advance past 10
and never see it. A per-report asyncio.Lock serializes insert+commit. All
of a run's writes come from the one process running it, so this makes
commit order equal id order per report, and ``id > last_id`` is
exactly-once.

Termination: rows and ``reports.status`` are read in one statement (one
snapshot). The subscriber exits only after a read that shows the report
closed, so every event committed before close has already been yielded.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID

import asyncpg

from ara.models.events import ResearchEvent, ResearchEventAdapter
from ara.models.research import ReportEnvelope
from ara.options import Depth
from ara.storage.notify import CHANNEL, EventDoorbell

_REPLAY_TAIL = 50  # how many trailing events to replay to a fresh subscriber
_POLL_INTERVAL_S = 2.0  # fallback re-read when no doorbell arrives
_NO_ID = 0  # report_events.id is bigserial (>= 1)

# status + the last $2 events, oldest first. One row with NULL id when the
# report has no events; zero rows when the report does not exist.
_TAIL_SQL = """
select r.status, e.id, e.event
from reports r
left join lateral (
  select id, event from report_events
  where report_id = r.id
  order by id desc
  limit $2
) e on true
where r.id = $1
order by e.id asc
"""

# status + every event newer than $2, oldest first.
_SINCE_SQL = """
select r.status, e.id, e.event
from reports r
left join lateral (
  select id, event from report_events
  where report_id = r.id and id > $2
) e on true
where r.id = $1
order by e.id asc
"""

_Fetched = tuple[str | None, list[tuple[int, ResearchEvent]]]


class SupabaseReportStore:
    """asyncpg-backed implementation of `ReportStore`."""

    def __init__(
        self,
        *,
        pool: asyncpg.Pool,
        doorbell: EventDoorbell,
        poll_interval: float = _POLL_INTERVAL_S,
    ) -> None:
        self._pool = pool
        self._doorbell = doorbell
        self._poll_interval = poll_interval
        self._write_locks: dict[UUID, asyncio.Lock] = {}

    def _write_lock(self, report_id: UUID) -> asyncio.Lock:
        return self._write_locks.setdefault(report_id, asyncio.Lock())

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into reports
                  (id, owner_id, question, status, depth, browse_web, used_byok)
                values ($1, $2, $3, 'running', $4, $5, $6)
                on conflict (id) do nothing
                """,
                report_id,
                owner_id,
                question,
                depth,
                browse_web,
                used_byok,
            )

    async def get_question(self, report_id: UUID) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("select question from reports where id = $1", report_id)
        if row is None:
            return None
        question: str = row["question"]
        return question

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        payload_json = event.model_dump_json()
        async with (
            self._write_lock(report_id),
            self._pool.acquire() as conn,
            conn.transaction(),
        ):
            await conn.execute(
                "insert into report_events (report_id, event) values ($1, $2::jsonb)",
                report_id,
                payload_json,
            )
            await conn.execute("select pg_notify($1, $2)", CHANNEL, str(report_id))

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
        tavily_searches: int = 0,
    ) -> None:
        payload_json = report_payload.model_dump_json() if report_payload else None
        async with (
            self._write_lock(report_id),
            self._pool.acquire() as conn,
            conn.transaction(),
        ):
            await conn.execute(
                """
                        update reports
                        set status = $2, cost_usd = $3, report_payload = $4::jsonb,
                            error_message = $5, tavily_searches = $6,
                            completed_at = now()
                        where id = $1
                        """,
                report_id,
                status,
                cost_usd,
                payload_json,
                error_message,
                tavily_searches,
            )
            await conn.execute("select pg_notify($1, $2)", CHANNEL, str(report_id))
        self._write_locks.pop(report_id, None)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        # Register BEFORE the first read so a NOTIFY landing between the
        # read and the wait is not lost (the event stays set).
        bell = self._doorbell.register(report_id)
        try:
            status, events = await self._fetch(_TAIL_SQL, report_id, _REPLAY_TAIL)
            last_id = _NO_ID
            for event_id, event in events:
                last_id = event_id
                yield event
            while status == "running":
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(bell.wait(), timeout=self._poll_interval)
                bell.clear()
                status, events = await self._fetch(_SINCE_SQL, report_id, last_id)
                for event_id, event in events:
                    last_id = event_id
                    yield event
        finally:
            self._doorbell.unregister(report_id, bell)

    async def _fetch(self, sql: str, report_id: UUID, arg: int) -> _Fetched:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, report_id, arg)
        if not rows:
            return None, []
        status: str = rows[0]["status"]
        events = [
            # asyncpg returns jsonb as a JSON string without a codec.
            (int(row["id"]), ResearchEventAdapter.validate_json(row["event"]))
            for row in rows
            if row["id"] is not None
        ]
        return status, events
