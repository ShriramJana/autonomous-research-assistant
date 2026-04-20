"""SSE event envelopes — a discriminated union keyed on `type`.

These are the wire format between backend and frontend. Every event published
to the per-report ring buffer is one of these models; `ResearchEventAdapter`
validates/serializes the union.
"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from ara.models.research import FinalReport, ResearchPlan, SubQueryFinding

ErrorStage = Literal["plan", "research", "synthesis"]


class PlanReady(BaseModel):
    type: Literal["plan_ready"] = "plan_ready"
    plan: ResearchPlan


class ResearcherStarted(BaseModel):
    type: Literal["researcher_started"] = "researcher_started"
    sub_query_id: UUID
    question: str


class ResearcherProgress(BaseModel):
    type: Literal["researcher_progress"] = "researcher_progress"
    sub_query_id: UUID
    tool_call: str


class ResearcherComplete(BaseModel):
    type: Literal["researcher_complete"] = "researcher_complete"
    sub_query_id: UUID
    finding: SubQueryFinding


class SynthesisToken(BaseModel):
    type: Literal["synthesis_token"] = "synthesis_token"
    token: str


class ReportComplete(BaseModel):
    type: Literal["report_complete"] = "report_complete"
    report: FinalReport


class ErrorEvent(BaseModel):
    """An error surfaced from any stage.

    `sub_query_id` is set for researcher-scoped failures so the frontend can
    mark the right agent as degraded without killing the whole report.
    """

    type: Literal["error"] = "error"
    stage: ErrorStage
    message: str
    sub_query_id: UUID | None = None


class CostUpdate(BaseModel):
    """Running API cost snapshot; emitted after every Anthropic response."""

    type: Literal["cost_update"] = "cost_update"
    model: str
    input_tokens: int
    output_tokens: int
    cumulative_usd: float


ResearchEvent = Annotated[
    (
        PlanReady
        | ResearcherStarted
        | ResearcherProgress
        | ResearcherComplete
        | SynthesisToken
        | ReportComplete
        | ErrorEvent
        | CostUpdate
    ),
    Field(discriminator="type"),
]

ResearchEventAdapter: TypeAdapter[ResearchEvent] = TypeAdapter(ResearchEvent)
