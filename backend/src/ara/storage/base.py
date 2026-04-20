"""`ReportStore` Protocol — the single swap-point for persistence.

Swapping the v1 in-memory impl for Supabase (or anything else) means
adding a new file that implements this Protocol. No other module should
reach into a concrete store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol
from uuid import UUID

from ara.models.events import ResearchEvent


class ReportStore(Protocol):
    """Lifecycle + event-stream interface for a report.

    The stream is a per-report pub/sub with a bounded ring buffer so a
    client that disconnects and reconnects within a few seconds sees
    continuity instead of starting from empty.
    """

    async def create(self, report_id: UUID, question: str) -> None:
        """Register a new report. Idempotent is NOT required — callers should ensure uniqueness."""
        ...

    async def get_question(self, report_id: UUID) -> str | None:
        """Return the original question, or `None` if the report doesn't exist."""
        ...

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        """Append an event to the ring buffer and fan out to live subscribers."""
        ...

    async def close(self, report_id: UUID) -> None:
        """Mark a report as complete. Subscribers still draining get the buffered tail and exit."""
        ...

    def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        """Yield buffered events, then live events, then exit when the report closes.

        Subscribing on an unknown report yields nothing. Subscribing on a
        closed report replays the buffer and returns without blocking.
        """
        ...
