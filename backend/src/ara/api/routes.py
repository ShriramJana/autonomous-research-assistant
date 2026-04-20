"""HTTP routes: POST /api/research, GET /api/research/{report_id}/stream."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ara.config import get_settings
from ara.runtime.orchestrator import run_report
from ara.storage.base import ReportStore

router = APIRouter(prefix="/api")


class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class CreateResearchResponse(BaseModel):
    report_id: UUID


@router.post("/research", response_model=CreateResearchResponse)
async def create_research(req: CreateResearchRequest, request: Request) -> CreateResearchResponse:
    """Start a new research run and return its id.

    The report is registered synchronously before we return so any client
    that immediately opens the SSE stream sees either events or the
    buffered tail rather than a 'report not found' empty stream.
    """
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks
    settings = get_settings()

    report_id = uuid4()
    await store.create(report_id, req.question)

    task = asyncio.create_task(
        run_report(
            report_id=report_id,
            question=req.question,
            store=store,
            settings=settings,
        )
    )
    # Hold a reference so the task isn't GC'd before completion, then
    # clean up once it finishes (success or failure).
    tasks.add(task)
    task.add_done_callback(tasks.discard)

    return CreateResearchResponse(report_id=report_id)


@router.get("/research/{report_id}/stream")
async def stream_research(report_id: UUID, request: Request) -> EventSourceResponse:
    store: ReportStore = request.app.state.store

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        # Emit only `data:` (no `event:` field) so the frontend can use a
        # single EventSource.onmessage handler and discriminate on the
        # parsed `type` field. Keeps the consumer ~15 lines smaller.
        async for event in store.subscribe(report_id):
            yield {"data": event.model_dump_json()}

    return EventSourceResponse(event_source())
