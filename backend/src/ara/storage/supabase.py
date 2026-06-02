"""Postgres-backed ReportStore using asyncpg.

Persistence per Protocol method:
- create:    INSERT into reports
- put_event: INSERT into report_events  +  fan-out to in-process live queues
- subscribe: replay last N events from report_events, then yield live events
- close:     UPDATE reports (status, cost_usd, report_payload, completed_at)

In-process pubsub stays (single-process for v1). When ARA goes
multi-instance we add a LISTEN/NOTIFY variant; Protocol unchanged.

Duplicate-delivery guard (subscribe vs concurrent put_event):
the live queue carries ``(event_id, event)`` tuples. ``subscribe``
records the max ``report_events.id`` it saw during replay and drops any
live-queue item whose id is already ``<=`` that high-water mark. This
keeps replay + live merging exactly-once even if a put_event interleaves
between queue registration and the replay SELECT.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

import asyncpg

from ara.models.events import ResearchEvent, ResearchEventAdapter
from ara.models.research import ReportEnvelope
from ara.options import Depth

_REPLAY_TAIL = 50  # how many trailing events to replay to a fresh subscriber

# Sentinel "no event" id used so the queue can also carry the close signal.
# `report_events.id` is bigserial (>=1), so 0 is a safe "below everything" id.
_NO_ID = 0


@dataclass
class _Subscribers:
    queues: list[asyncio.Queue[tuple[int, ResearchEvent] | None]] = field(
        default_factory=list
    )
    closed: bool = False


class SupabaseReportStore:
    """asyncpg-backed implementation of `ReportStore`.

    Live pubsub is in-memory — fine while single-process. The DB is the
    source of truth for replay; in-flight subscribers are also fanned to
    directly for low latency.
    """

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._subs: dict[UUID, _Subscribers] = {}

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
            row = await conn.fetchrow(
                "select question from reports where id = $1", report_id
            )
        if row is None:
            return None
        question: str = row["question"]
        return question

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        payload_json = event.model_dump_json()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                insert into report_events (report_id, event)
                values ($1, $2::jsonb)
                returning id
                """,
                report_id,
                payload_json,
            )
        event_id: int = row["id"]
        subs = self._subs.get(report_id)
        if subs is None or subs.closed:
            return
        for q in list(subs.queues):
            await q.put((event_id, event))

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        payload_json = report_payload.model_dump_json() if report_payload else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update reports
                set status = $2, cost_usd = $3, report_payload = $4::jsonb,
                    error_message = $5, completed_at = now()
                where id = $1
                """,
                report_id,
                status,
                cost_usd,
                payload_json,
                error_message,
            )
        subs = self._subs.get(report_id)
        if subs is None or subs.closed:
            return
        subs.closed = True
        for q in list(subs.queues):
            await q.put(None)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        subs = self._subs.setdefault(report_id, _Subscribers())
        queue: asyncio.Queue[tuple[int, ResearchEvent] | None] = asyncio.Queue()
        if subs.closed:
            # Report finished before this subscriber arrived. Just replay tail.
            async for _id, ev in self._replay_tail(report_id):
                yield ev
            return
        # Register the live queue BEFORE running the replay SELECT so that
        # any put_event landing concurrently with replay is captured on the
        # queue. We then dedupe against the replay's max id below.
        subs.queues.append(queue)

        try:
            high_water = _NO_ID
            async for event_id, ev in self._replay_tail(report_id):
                high_water = max(high_water, event_id)
                yield ev
            while True:
                item = await queue.get()
                if item is None:
                    return
                event_id, ev = item
                # Drop anything already covered by the replay snapshot — that
                # event was both persisted (so replay returned it) AND fanned
                # out to this queue by the concurrent put_event.
                if event_id <= high_water:
                    continue
                yield ev
        finally:
            if queue in subs.queues:
                subs.queues.remove(queue)

    async def _replay_tail(
        self, report_id: UUID
    ) -> AsyncIterator[tuple[int, ResearchEvent]]:
        """Yield the last `_REPLAY_TAIL` ``(id, event)`` pairs, oldest first."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select id, event from (
                  select id, event from report_events
                  where report_id = $1
                  order by id desc
                  limit $2
                ) sub
                order by id asc
                """,
                report_id,
                _REPLAY_TAIL,
            )
        for row in rows:
            # asyncpg returns jsonb as a raw JSON string unless a codec is set;
            # use validate_json so we don't need a per-connection codec hook.
            yield row["id"], ResearchEventAdapter.validate_json(row["event"])
