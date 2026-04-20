"""Integration tests for the orchestrator / DAG.

Monkeypatches the three agent functions at their DAG import sites, which
lets us assert the orchestrator's end-to-end wiring (emits, error
handling, degraded findings, report closure) without touching Anthropic.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from ara.agents import PlannerError, ResearcherError
from ara.config import Settings
from ara.models.events import (
    ErrorEvent,
    PlanReady,
    ReportComplete,
    ResearcherComplete,
    ResearcherProgress,
    ResearcherStarted,
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


def _plan_with_n(n: int, question: str = "top") -> ResearchPlan:
    sub_queries = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(n)
    ]
    return ResearchPlan(original_question=question, sub_queries=sub_queries)


def _source(url: str = "https://example.com", title: str = "Example") -> Source:
    return Source.model_validate({"url": url, "title": title})


def _fake_final_report(report_id: Any, question: str) -> FinalReport:
    src = _source()
    return FinalReport(
        report_id=report_id,
        original_question=question,
        executive_summary="Exec.",
        sections=[ReportSection(heading="S", content="Body [1].", citation_ids=[src.id])],
        citations=[src],
    )


def _settings() -> Settings:
    # Real settings don't need a real key — we monkeypatch every LLM call.
    return Settings(anthropic_api_key="test-key")  # type: ignore[call-arg]


async def test_pipeline_happy_path_emits_events_in_order() -> None:
    store = InMemoryReportStore()
    report_id = uuid4()
    plan = _plan_with_n(3)

    async def fake_plan(**kwargs: Any) -> ResearchPlan:
        return plan

    async def fake_research(*, sub_query: SubQuery, emit: Any, **kwargs: Any) -> SubQueryFinding:
        await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))
        await emit(ResearcherProgress(sub_query_id=sub_query.id, tool_call="web_search('x')"))
        src = _source(f"https://{sub_query.question}.com", sub_query.question)
        return SubQueryFinding(
            sub_query_id=sub_query.id,
            summary=f"Found about {sub_query.question}",
            key_facts=[KeyFact(statement="Fact", citation_ids=[src.id])],
            sources=[src],
        )

    async def fake_synth(*, emit: Any, **kwargs: Any) -> FinalReport:
        await emit(SynthesisToken(token="# Executive Summary\n\n"))
        await emit(SynthesisToken(token="Exec.\n\n"))
        return _fake_final_report(kwargs["report_id"], kwargs["original_question"])

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

    events = [e async for e in store.subscribe(report_id)]

    # Type counts
    assert sum(isinstance(e, PlanReady) for e in events) == 1
    assert sum(isinstance(e, ResearcherStarted) for e in events) == 3
    assert sum(isinstance(e, ResearcherComplete) for e in events) == 3
    assert sum(isinstance(e, ReportComplete) for e in events) == 1

    # Orderings
    plan_idx = next(i for i, e in enumerate(events) if isinstance(e, PlanReady))
    first_started = next(i for i, e in enumerate(events) if isinstance(e, ResearcherStarted))
    first_complete = next(i for i, e in enumerate(events) if isinstance(e, ResearcherComplete))
    last_complete = max(i for i, e in enumerate(events) if isinstance(e, ResearcherComplete))
    first_token = next(
        (i for i, e in enumerate(events) if isinstance(e, SynthesisToken)), len(events)
    )
    report_idx = next(i for i, e in enumerate(events) if isinstance(e, ReportComplete))

    assert plan_idx < first_started
    assert first_started < first_complete
    assert last_complete < first_token
    assert first_token < report_idx


async def test_pipeline_partial_researcher_failure_degrades_gracefully() -> None:
    """One researcher raises; orchestrator emits ErrorEvent + degraded finding."""
    store = InMemoryReportStore()
    report_id = uuid4()
    plan = _plan_with_n(3)

    async def fake_plan(**kwargs: Any) -> ResearchPlan:
        return plan

    fail_target = plan.sub_queries[1].id

    async def fake_research(*, sub_query: SubQuery, emit: Any, **kwargs: Any) -> SubQueryFinding:
        if sub_query.id == fail_target:
            raise ResearcherError("simulated network failure")
        await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))
        src = _source(f"https://{sub_query.question}.com", sub_query.question)
        return SubQueryFinding(
            sub_query_id=sub_query.id,
            summary=f"Found about {sub_query.question}",
            key_facts=[],
            sources=[src],
        )

    captured_findings: list[list[SubQueryFinding]] = []

    async def fake_synth(
        *, emit: Any, findings: list[SubQueryFinding], **kwargs: Any
    ) -> FinalReport:
        captured_findings.append(findings)
        return _fake_final_report(kwargs["report_id"], kwargs["original_question"])

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

    events = [e async for e in store.subscribe(report_id)]

    # ErrorEvent scoped to the failed sub_query
    error_events = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(error_events) == 1
    assert error_events[0].stage == "research"
    assert error_events[0].sub_query_id == fail_target

    # Synthesizer saw all 3 findings (one degraded with "Research failed: ...")
    assert len(captured_findings) == 1
    assert len(captured_findings[0]) == 3
    degraded = next(f for f in captured_findings[0] if f.sub_query_id == fail_target)
    assert degraded.summary.startswith("Research failed:")
    assert degraded.key_facts == []
    assert degraded.sources == []

    # Pipeline still completed
    assert any(isinstance(e, ReportComplete) for e in events)


async def test_pipeline_terminal_planner_failure_emits_error_and_stops() -> None:
    store = InMemoryReportStore()
    report_id = uuid4()

    async def fake_plan(**kwargs: Any) -> ResearchPlan:
        raise PlannerError("fatal planner failure")

    async def fake_research(**kwargs: Any) -> SubQueryFinding:
        pytest.fail("research should not run if plan failed")

    async def fake_synth(**kwargs: Any) -> FinalReport:
        pytest.fail("synthesis should not run if plan failed")

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

    events = [e async for e in store.subscribe(report_id)]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].stage == "plan"
    assert "fatal planner failure" in errors[0].message
    assert not any(isinstance(e, ReportComplete) for e in events)
