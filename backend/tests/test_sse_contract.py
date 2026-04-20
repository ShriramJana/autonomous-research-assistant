"""SSE contract invariants — the event stream's ordering guarantees.

The frontend depends on these orderings. Breaking one of them silently
would be very hard to catch in a UI test, so we encode them explicitly.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from ara.config import Settings
from ara.models.events import (
    CostUpdate,
    ErrorEvent,
    PlanReady,
    ReportComplete,
    ResearcherComplete,
    ResearcherProgress,
    ResearcherStarted,
    ResearchEventAdapter,
    SynthesisToken,
)
from ara.models.research import (
    FinalReport,
    KeyFact,
    Priority,
    ReportSection,
    ResearchPlan,
    Source,
    SubQuery,
    SubQueryFinding,
)
from ara.runtime.orchestrator import run_report
from ara.storage.memory import InMemoryReportStore


def _settings() -> Settings:
    return Settings(anthropic_api_key="test-key")  # type: ignore[call-arg]


def _src(url: str) -> Source:
    return Source.model_validate({"url": url, "title": "T"})


async def _run_canned_pipeline() -> list[Any]:
    store = InMemoryReportStore()
    report_id = uuid4()
    plan = ResearchPlan(
        original_question="top",
        sub_queries=[
            SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
        ],
    )

    async def fake_plan(**kwargs: Any) -> ResearchPlan:
        return plan

    async def fake_research(*, sub_query: SubQuery, emit: Any, **kwargs: Any) -> SubQueryFinding:
        await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))
        await emit(ResearcherProgress(sub_query_id=sub_query.id, tool_call="web_search('x')"))
        src = _src(f"https://{sub_query.question}.com")
        return SubQueryFinding(
            sub_query_id=sub_query.id,
            summary="s",
            key_facts=[KeyFact(statement="f", citation_ids=[src.id])],
            sources=[src],
        )

    async def fake_synth(*, emit: Any, **kwargs: Any) -> FinalReport:
        for tok in ["# Executive Summary\n\n", "Body.\n"]:
            await emit(SynthesisToken(token=tok))
        src = _src("https://example.com")
        return FinalReport(
            report_id=kwargs["report_id"],
            original_question=kwargs["original_question"],
            executive_summary="Exec.",
            sections=[ReportSection(heading="H", content="C [1].", citation_ids=[src.id])],
            citations=[src],
        )

    with (
        patch("ara.graph.dag.plan_research", fake_plan),
        patch("ara.graph.dag.research_sub_query", fake_research),
        patch("ara.graph.dag.synthesize_report", fake_synth),
    ):
        await run_report(
            report_id=report_id,
            question="top",
            store=store,
            settings=_settings(),
        )

    return [e async for e in store.subscribe(report_id)]


async def test_every_event_validates_under_discriminated_union() -> None:
    events = await _run_canned_pipeline()
    for ev in events:
        dumped = ev.model_dump(mode="json")
        reparsed = ResearchEventAdapter.validate_python(dumped)
        assert type(reparsed) is type(ev)


async def test_plan_ready_precedes_every_researcher_started() -> None:
    events = await _run_canned_pipeline()
    plan_idx = next(i for i, e in enumerate(events) if isinstance(e, PlanReady))
    started_indices = [i for i, e in enumerate(events) if isinstance(e, ResearcherStarted)]
    assert started_indices, "expected at least one ResearcherStarted"
    assert all(i > plan_idx for i in started_indices)


async def test_every_researcher_started_has_matching_complete() -> None:
    events = await _run_canned_pipeline()
    started_ids = {e.sub_query_id for e in events if isinstance(e, ResearcherStarted)}
    complete_ids = {e.sub_query_id for e in events if isinstance(e, ResearcherComplete)}
    assert started_ids == complete_ids


async def test_researcher_progress_falls_between_started_and_complete() -> None:
    events = await _run_canned_pipeline()
    for ev in events:
        if not isinstance(ev, ResearcherProgress):
            continue
        sqid = ev.sub_query_id
        progress_idx = events.index(ev)
        started_idx = next(
            i for i, e in enumerate(events)
            if isinstance(e, ResearcherStarted) and e.sub_query_id == sqid
        )
        complete_idx = next(
            i for i, e in enumerate(events)
            if isinstance(e, ResearcherComplete) and e.sub_query_id == sqid
        )
        assert started_idx < progress_idx < complete_idx


async def test_synthesis_tokens_after_all_researcher_completes() -> None:
    events = await _run_canned_pipeline()
    last_complete = max(i for i, e in enumerate(events) if isinstance(e, ResearcherComplete))
    token_indices = [i for i, e in enumerate(events) if isinstance(e, SynthesisToken)]
    if token_indices:
        assert min(token_indices) > last_complete


async def test_report_complete_is_terminal() -> None:
    events = await _run_canned_pipeline()
    report_idx = next(
        (i for i, e in enumerate(events) if isinstance(e, ReportComplete)), None
    )
    assert report_idx is not None
    # Only CostUpdate / buffered non-terminal events may appear after
    # ReportComplete in the current design — but NOT another ReportComplete
    # or any SynthesisToken.
    tail = events[report_idx + 1 :]
    assert not any(isinstance(e, ReportComplete) for e in tail)
    assert not any(isinstance(e, SynthesisToken) for e in tail)


async def test_no_error_events_on_happy_path() -> None:
    events = await _run_canned_pipeline()
    assert not any(isinstance(e, ErrorEvent) for e in events)


async def test_cost_update_events_fire_with_monotonic_cumulative() -> None:
    events = await _run_canned_pipeline()
    # The canned fakes don't call the LLM, so cost_updates are expected to
    # be 0 — but if/when LLM is real, monotonicity must hold. Verify with
    # whatever updates arrive that cumulative only grows.
    cumulative = [e.cumulative_usd for e in events if isinstance(e, CostUpdate)]
    for prev, curr in pairwise(cumulative):
        assert curr >= prev
