"""Unit tests for the research-domain and SSE-event Pydantic models.

One test per model, plus discriminated-union round-trip coverage.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ara.models.events import (
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
from ara.options import options_for_depth

# ---------- research models ----------


def test_priority_values() -> None:
    assert Priority.LOW == 1
    assert Priority.HIGH == 3


def test_subquery_defaults_and_validation() -> None:
    sq = SubQuery(question="What is RAG?", rationale="Foundation context.", priority=Priority.HIGH)
    assert isinstance(sq.id, UUID)
    assert sq.priority == Priority.HIGH

    with pytest.raises(ValidationError):
        SubQuery(question="", rationale="x", priority=Priority.LOW)


def test_research_plan_bounds() -> None:
    base = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
    ]
    plan = ResearchPlan(original_question="top", sub_queries=base)
    assert len(plan.sub_queries) == 3

    with pytest.raises(ValidationError):
        ResearchPlan(original_question="top", sub_queries=base[:2])

    too_many = [
        SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(8)
    ]
    with pytest.raises(ValidationError):
        ResearchPlan(original_question="top", sub_queries=too_many)


def test_source_has_stable_uuid() -> None:
    s = Source(url="https://example.com/a", title="A")  # type: ignore[arg-type]
    assert isinstance(s.id, UUID)

    explicit = uuid4()
    s2 = Source(id=explicit, url="https://example.com/b", title="B")  # type: ignore[arg-type]
    assert s2.id == explicit


def test_keyfact_references_uuids_not_indices() -> None:
    source_id = uuid4()
    kf = KeyFact(statement="sky is blue", citation_ids=[source_id])
    assert kf.citation_ids == [source_id]


def test_subquery_finding_round_trip() -> None:
    src = Source(url="https://example.com", title="Ex")  # type: ignore[arg-type]
    finding = SubQueryFinding(
        sub_query_id=uuid4(),
        summary="A summary.",
        key_facts=[KeyFact(statement="fact", citation_ids=[src.id])],
        sources=[src],
    )
    data = finding.model_dump_json()
    reparsed = SubQueryFinding.model_validate_json(data)
    assert reparsed == finding


def test_report_section_allows_empty_citations() -> None:
    sec = ReportSection(heading="Intro", content="Body.")
    assert sec.citation_ids == []


def test_final_report_requires_sections() -> None:
    src = Source(url="https://example.com", title="Ex")  # type: ignore[arg-type]
    report = FinalReport(
        report_id=uuid4(),
        original_question="q",
        executive_summary="exec",
        sections=[ReportSection(heading="h", content="c", citation_ids=[src.id])],
        citations=[src],
    )
    assert len(report.sections) == 1

    with pytest.raises(ValidationError):
        FinalReport(
            report_id=uuid4(),
            original_question="q",
            executive_summary="exec",
            sections=[],
            citations=[],
        )


def test_degraded_finding_is_valid() -> None:
    """A researcher failure produces summary-only finding — must validate."""
    finding = SubQueryFinding(
        sub_query_id=uuid4(),
        summary="Research failed: timeout",
        key_facts=[],
        sources=[],
    )
    assert finding.key_facts == []
    assert finding.sources == []


# ---------- event models ----------


def test_plan_ready_event() -> None:
    plan = ResearchPlan(
        original_question="q",
        sub_queries=[
            SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(3)
        ],
    )
    ev = PlanReady(plan=plan)
    assert ev.type == "plan_ready"


def test_researcher_started_event() -> None:
    ev = ResearcherStarted(sub_query_id=uuid4(), question="q")
    assert ev.type == "researcher_started"


def test_researcher_progress_event() -> None:
    ev = ResearcherProgress(sub_query_id=uuid4(), tool_call="web_search(...)")
    assert ev.type == "researcher_progress"


def test_researcher_complete_event() -> None:
    sqid = uuid4()
    finding = SubQueryFinding(sub_query_id=sqid, summary="ok")
    ev = ResearcherComplete(sub_query_id=sqid, finding=finding)
    assert ev.type == "researcher_complete"


def test_synthesis_token_event() -> None:
    ev = SynthesisToken(token="hello")
    assert ev.type == "synthesis_token"


def test_report_complete_event() -> None:
    src = Source(url="https://example.com", title="Ex")  # type: ignore[arg-type]
    report = FinalReport(
        report_id=uuid4(),
        original_question="q",
        executive_summary="exec",
        sections=[ReportSection(heading="h", content="c", citation_ids=[src.id])],
        citations=[src],
    )
    ev = ReportComplete(report=report)
    assert ev.type == "report_complete"


def test_error_event_defaults() -> None:
    ev = ErrorEvent(stage="research", message="boom")
    assert ev.type == "error"
    assert ev.sub_query_id is None


def test_error_event_with_sub_query() -> None:
    sqid = uuid4()
    ev = ErrorEvent(stage="research", message="boom", sub_query_id=sqid)
    assert ev.sub_query_id == sqid


# ---------- discriminated union ----------


def test_discriminated_union_round_trip() -> None:
    token_ev = SynthesisToken(token="x")
    raw = token_ev.model_dump()
    parsed = ResearchEventAdapter.validate_python(raw)
    assert isinstance(parsed, SynthesisToken)
    assert parsed.token == "x"


def test_discriminated_union_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ResearchEventAdapter.validate_python({"type": "nope", "foo": 1})


def test_source_defaults_to_web_kind_and_round_trips_scholarly_metadata() -> None:
    web = Source.model_validate({"url": "https://a.com", "title": "A"})
    assert web.kind == "web"
    assert web.authors == [] and web.year is None and web.citation_count is None

    paper = Source.model_validate(
        {
            "url": "https://doi.org/10.1/x",
            "title": "P",
            "kind": "scholarly",
            "authors": ["A", "B"],
            "year": 2024,
            "venue": "V",
            "doi": "10.1/x",
            "citation_count": 12,
        }
    )
    assert paper.kind == "scholarly" and paper.year == 2024 and paper.doi == "10.1/x"
    assert Source.model_validate_json(paper.model_dump_json()) == paper


def test_source_rejects_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        Source.model_validate({"url": "https://a.com", "title": "A", "kind": "blog"})


def test_sub_query_search_terms_default_empty_and_capped_at_four() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.LOW)
    assert sq.search_terms == []
    ok = SubQuery(question="q", rationale="r", priority=Priority.LOW, search_terms=["a", "b"])
    assert ok.search_terms == ["a", "b"]
    with pytest.raises(ValidationError):
        SubQuery(question="q", rationale="r", priority=Priority.LOW, search_terms=["a"] * 5)


def test_plan_and_report_scholarly_flags_default_false() -> None:
    plan = ResearchPlan(
        original_question="q",
        sub_queries=[
            SubQuery(question=f"q{i}", rationale="r", priority=Priority.LOW) for i in range(3)
        ],
    )
    assert plan.scholarly_enabled is False
    report = FinalReport(
        report_id=uuid4(),
        original_question="q",
        executive_summary="e",
        sections=[ReportSection(heading="h", content="c")],
    )
    assert report.scholarly_enabled is False


def test_options_for_depth_carries_scholarly_flag() -> None:
    assert options_for_depth("quick").scholarly_enabled is False
    opts = options_for_depth("deep", web_search_enabled=False, scholarly_enabled=True)
    assert (opts.max_sub_queries, opts.web_search_enabled, opts.scholarly_enabled) == (
        7,
        False,
        True,
    )
