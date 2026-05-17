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
from ara.options import options_for_depth
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides
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


def _overrides(settings: Settings, depth: str = "standard") -> RuntimeOverrides:
    return RuntimeOverrides(
        api_key=settings.anthropic_api_key,
        planner_model=settings.claude_planner_model,
        researcher_model=settings.claude_researcher_model,
        synthesizer_model=settings.claude_synthesizer_model,
        options=options_for_depth(depth),  # type: ignore[arg-type]
    )


async def test_pipeline_happy_path_emits_events_in_order() -> None:
    store = InMemoryReportStore()
    report_id = uuid4()
    plan = _plan_with_n(3)
    settings = _settings()

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
            settings=settings,
            overrides=_overrides(settings),
            owner_id=uuid4(),
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
    settings = _settings()

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
            settings=settings,
            overrides=_overrides(settings),
            owner_id=uuid4(),
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
    settings = _settings()

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
            settings=settings,
            overrides=_overrides(settings),
            owner_id=uuid4(),
        )

    events = [e async for e in store.subscribe(report_id)]
    errors = [e for e in events if isinstance(e, ErrorEvent)]
    assert len(errors) == 1
    assert errors[0].stage == "plan"
    assert "fatal planner failure" in errors[0].message
    assert not any(isinstance(e, ReportComplete) for e in events)


class _RecordingLLM:
    """Captures every model string the orchestrator dispatches to.

    Raises on first call so we don't need a real Anthropic round-trip;
    we just need to confirm the model the orchestrator picked.
    """

    def __init__(self) -> None:
        self.models_seen: list[str] = []

    async def complete_with_tools(self, *, model: str, **_: object) -> object:
        self.models_seen.append(model)
        raise RuntimeError("recording llm — not meant to actually run")


@pytest.mark.asyncio
async def test_overrides_replace_settings_models() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.anthropic_api_key = "from-settings"
    settings.claude_planner_model = "from-settings-planner"
    settings.claude_researcher_model = "from-settings-researcher"
    settings.claude_synthesizer_model = "from-settings-synthesizer"

    overrides = RuntimeOverrides(
        api_key="from-overrides-key",
        planner_model="haiku-from-overrides",
        researcher_model="haiku-from-overrides",
        synthesizer_model="haiku-from-overrides",
        options=options_for_depth("quick", web_search_enabled=False),
    )

    store = InMemoryReportStore()
    rid = uuid4()
    owner = uuid4()

    llm = _RecordingLLM()
    await run_report(
        report_id=rid,
        question="anything",
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=owner,
        llm=llm,  # type: ignore[arg-type]
    )

    assert llm.models_seen, "graph should have at least attempted one call"
    assert all(
        m == "haiku-from-overrides" for m in llm.models_seen
    ), f"orchestrator must use overrides, not settings — saw {llm.models_seen}"


@pytest.mark.asyncio
async def test_orchestrator_persists_real_owner_depth_byok() -> None:
    """Verify Task 4's placeholder uuid4()/depth='standard' is fully replaced."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.anthropic_api_key = "server-free-tier-key"

    overrides = RuntimeOverrides(
        api_key="server-free-tier-key",  # same as settings → used_byok=False
        planner_model="x",
        researcher_model="x",
        synthesizer_model="x",
        options=options_for_depth("quick", web_search_enabled=False),
    )

    store = InMemoryReportStore()
    rid = uuid4()
    owner = uuid4()

    llm = _RecordingLLM()
    await run_report(
        report_id=rid,
        question="q",
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=owner,
        llm=llm,  # type: ignore[arg-type]
    )

    state = store.get_state(rid)
    assert state is not None
    assert state.owner_id == owner
    assert state.depth == "quick"
    assert state.browse_web is False
    assert state.used_byok is False


@pytest.mark.asyncio
async def test_orchestrator_marks_used_byok_when_key_differs() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.anthropic_api_key = "server-key"

    overrides = RuntimeOverrides(
        api_key="user-byok-key",
        planner_model="x",
        researcher_model="x",
        synthesizer_model="x",
        options=options_for_depth("deep", web_search_enabled=True),
    )

    store = InMemoryReportStore()
    rid = uuid4()
    llm = _RecordingLLM()
    await run_report(
        report_id=rid,
        question="q",
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=uuid4(),
        llm=llm,  # type: ignore[arg-type]
    )

    state = store.get_state(rid)
    assert state is not None
    assert state.used_byok is True
    assert state.depth == "deep"
    assert state.browse_web is True


@pytest.mark.asyncio
async def test_orchestrator_records_error_status_on_failure() -> None:
    """When the graph raises a terminal error, close() must record status='error'."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    overrides = RuntimeOverrides(
        api_key="k",
        planner_model="x",
        researcher_model="x",
        synthesizer_model="x",
        options=options_for_depth("quick", web_search_enabled=False),
    )
    store = InMemoryReportStore()
    rid = uuid4()
    llm = _RecordingLLM()  # will RuntimeError on first call
    await run_report(
        report_id=rid,
        question="q",
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=uuid4(),
        llm=llm,  # type: ignore[arg-type]
    )
    state = store.get_state(rid)
    assert state is not None
    assert state.status == "error"
    assert state.error_message is not None
