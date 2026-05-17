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
from ara.options import Depth, depth_presets, options_for_depth
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides
from ara.storage.base import ReportStore

router = APIRouter(prefix="/api")


class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Depth = "standard"
    browse_web: bool = True


class CreateResearchResponse(BaseModel):
    report_id: UUID


class ModelsConfig(BaseModel):
    planner: str
    researcher: str
    synthesizer: str


class DepthPresetConfig(BaseModel):
    max_sub_queries: int
    max_iterations: int


class ConfigResponse(BaseModel):
    """Sanitized view of runtime config. Excludes secrets and infra."""

    models: ModelsConfig
    depth_presets: dict[str, DepthPresetConfig]


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    settings = get_settings()
    return ConfigResponse(
        models=ModelsConfig(
            planner=settings.claude_planner_model,
            researcher=settings.claude_researcher_model,
            synthesizer=settings.claude_synthesizer_model,
        ),
        depth_presets={
            d: DepthPresetConfig(
                max_sub_queries=p["max_sub_queries"],
                max_iterations=p["max_iterations"],
            )
            for d, p in depth_presets().items()
        },
    )


@router.post("/research", response_model=CreateResearchResponse)
async def create_research(req: CreateResearchRequest, request: Request) -> CreateResearchResponse:
    """Start a new research run and return its id.

    Owner_id is a placeholder until Task 8 wires real auth.
    """
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks
    settings = get_settings()
    options = options_for_depth(req.depth, web_search_enabled=req.browse_web)

    overrides = RuntimeOverrides(
        api_key=settings.anthropic_api_key,
        planner_model=settings.claude_planner_model,
        researcher_model=settings.claude_researcher_model,
        synthesizer_model=settings.claude_synthesizer_model,
        options=options,
    )

    report_id = uuid4()

    task = asyncio.create_task(
        run_report(
            report_id=report_id,
            question=req.question,
            store=store,
            settings=settings,
            overrides=overrides,
            owner_id=uuid4(),  # placeholder until Task 8 wires real auth
        )
    )
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
