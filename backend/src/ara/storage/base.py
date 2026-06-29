"""`ReportStore` Protocol — the single swap-point for persistence.

Swapping the v1 in-memory impl for Supabase (or anything else) means
adding a new file that implements this Protocol. No other module should
reach into a concrete store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol
from uuid import UUID

from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import Depth  # re-exported below


class ReportStore(Protocol):
    """Lifecycle + event-stream interface for a report."""

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
        """Register a new report with its owner + chosen run parameters."""
        ...

    async def get_question(self, report_id: UUID) -> str | None:
        """Return the original question, or None if the report doesn't exist."""
        ...

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        """Append an event to the ring buffer and fan out to live subscribers."""
        ...

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
        """Finalize a report. Subscribers draining the tail still see buffered events."""
        ...

    def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        """Yield buffered events, then live events, then exit when the report closes."""
        ...
