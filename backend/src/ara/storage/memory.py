"""In-memory `ReportStore` — dict of per-report state, per-report ring buffer.

Thread safety: asyncio single-threaded loop guarantees no interleaving
between non-awaiting statements, so we don't need locks. The critical
section in `subscribe` (register live queue + snapshot ring buffer) is
fully synchronous — a new `put_event` cannot interleave between the two
statements, so there's no duplicate-yield window.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import Depth

_DEFAULT_BUFFER_SIZE = 50


@dataclass
class _ReportState:
    question: str
    owner_id: UUID
    depth: Depth
    browse_web: bool
    used_byok: bool
    buffer: deque[ResearchEvent]
    live_queues: list[asyncio.Queue[ResearchEvent | None]] = field(default_factory=list)
    closed: bool = False
    status: Literal["running", "completed", "error"] = "running"
    cost_usd: float | None = None
    report_payload: ReportEnvelope | None = None
    error_message: str | None = None


class InMemoryReportStore:
    """v1 implementation of `ReportStore`. Not durable across restarts."""

    def __init__(self, *, buffer_size: int = _DEFAULT_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._reports: dict[UUID, _ReportState] = {}

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
        if report_id in self._reports:
            return
        self._reports[report_id] = _ReportState(
            question=question,
            owner_id=owner_id,
            depth=depth,
            browse_web=browse_web,
            used_byok=used_byok,
            buffer=deque(maxlen=self._buffer_size),
        )

    async def get_question(self, report_id: UUID) -> str | None:
        state = self._reports.get(report_id)
        return state.question if state is not None else None

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        state = self._reports.get(report_id)
        if state is None or state.closed:
            return
        state.buffer.append(event)
        for q in list(state.live_queues):
            await q.put(event)

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        state = self._reports.get(report_id)
        if state is None or state.closed:
            return
        state.closed = True
        state.status = status
        state.cost_usd = cost_usd
        state.report_payload = report_payload
        state.error_message = error_message
        for q in list(state.live_queues):
            await q.put(None)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        state = self._reports.get(report_id)
        if state is None:
            return

        if state.closed:
            for event in list(state.buffer):
                yield event
            return

        queue: asyncio.Queue[ResearchEvent | None] = asyncio.Queue()
        state.live_queues.append(queue)
        buffered_snapshot = list(state.buffer)

        try:
            for event in buffered_snapshot:
                yield event
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            if queue in state.live_queues:
                state.live_queues.remove(queue)

    # ---- Helpers used by tests (not part of the Protocol) ----

    def get_state(self, report_id: UUID) -> _ReportState | None:
        """Inspection hook for tests — not part of `ReportStore`."""
        return self._reports.get(report_id)
