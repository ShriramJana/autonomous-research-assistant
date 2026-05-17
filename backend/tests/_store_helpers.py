"""Test-only convenience for constructing reports with sensible defaults.

Keeps every test from spelling out the same owner_id/depth/browse_web kwargs.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from ara.options import Depth
from ara.storage.base import ReportStore


async def create_test_report(
    store: ReportStore,
    report_id: UUID,
    question: str,
    *,
    owner_id: UUID | None = None,
    depth: Depth = "standard",
    browse_web: bool = True,
    used_byok: bool = True,
) -> UUID:
    """Create a report with test-default metadata. Returns the owner_id used."""
    owner = owner_id or uuid4()
    await store.create(
        report_id,
        question,
        owner_id=owner,
        depth=depth,
        browse_web=browse_web,
        used_byok=used_byok,
    )
    return owner
