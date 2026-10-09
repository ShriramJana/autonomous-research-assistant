"""`ReportStore` for local mode: SQLite persistence + in-process live fan-out.

Composition: an `InMemoryReportStore` handles live subscribers exactly as it
does today; this class adds durable rows (reports + report_events) through
the `SqliteReportsRepo`, so History and replay work after a restart. One
process, so no cross-process doorbell is needed.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal
from uuid import UUID

from ara.db.sqlite import SqliteReportsRepo
from ara.models.events import ResearchEvent, ResearchEventAdapter
from ara.models.research import ReportEnvelope
from ara.options import Depth
from ara.storage.memory import InMemoryReportStore

_REPLAY_TAIL = 50


class SqliteReportStore:
    def __init__(self, repo: SqliteReportsRepo, *, buffer_size: int = _REPLAY_TAIL) -> None:
        self._repo = repo
        self._live = InMemoryReportStore(buffer_size=buffer_size)

    async def create(
        self, report_id: UUID, question: str, *, owner_id: UUID, depth: Depth,
        browse_web: bool, used_byok: bool,
    ) -> None:
        await self._repo.create_report(
            report_id, owner_id=owner_id, question=question, depth=depth,
            browse_web=browse_web, used_byok=used_byok,
        )
        await self._live.create(
            report_id, question, owner_id=owner_id, depth=depth,
            browse_web=browse_web, used_byok=used_byok,
        )

    async def get_question(self, report_id: UUID) -> str | None:
        row = await self._repo.get_report(report_id)
        return row.question if row is not None else None

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        state = self._live.get_state(report_id)
        if state is None or state.closed:
            return
        await self._repo.append_event(report_id, event.model_dump_json())
        await self._live.put_event(report_id, event)

    async def close(
        self, report_id: UUID, *, status: Literal["completed", "error"],
        cost_usd: float | None = None, report_payload: ReportEnvelope | None = None,
        error_message: str | None = None, tavily_searches: int = 0,
    ) -> None:
        await self._repo.close_report(
            report_id, status=status, cost_usd=cost_usd,
            report_payload_json=report_payload.model_dump_json() if report_payload else None,
            error_message=error_message, tavily_searches=tavily_searches,
        )
        await self._live.close(
            report_id, status=status, cost_usd=cost_usd, report_payload=report_payload,
            error_message=error_message, tavily_searches=tavily_searches,
        )

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        state = self._live.get_state(report_id)
        if state is not None and not state.closed:
            # Running in this process: in-memory buffer + live queue is exact.
            async for event in self._live.subscribe(report_id):
                yield event
            return
        # Finished, or from a previous process: replay the persisted tail.
        rows = await self._repo.events_since(report_id, 0)
        for _id, event_json in rows[-_REPLAY_TAIL:]:
            yield ResearchEventAdapter.validate_json(event_json)
