"""Unit tests for the synthesizer agent.

Uses a small `FakeLLM` whose `stream_completion` yields a canned token
sequence. Verifies source dedup, citation-marker resolution, section
parsing, SynthesisToken emission, and graceful handling of degraded
findings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast
from uuid import uuid4

import pytest

from ara.agents import SynthesizerError
from ara.agents.synthesizer import synthesize_report
from ara.llm.client import LLMClient
from ara.models.events import ResearchEvent, SynthesisToken
from ara.models.research import KeyFact, Priority, Source, SubQuery, SubQueryFinding


class FakeLLM:
    """Minimal stand-in; synthesizer only calls `stream_completion`."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self.calls: list[dict[str, Any]] = []

    async def stream_completion(self, **kwargs: Any) -> AsyncIterator[str]:
        self.calls.append(kwargs)
        for t in self._tokens:
            yield t


def _make_emit() -> tuple[Callable[[ResearchEvent], Awaitable[None]], list[ResearchEvent]]:
    events: list[ResearchEvent] = []

    async def emit(event: ResearchEvent) -> None:
        events.append(event)

    return emit, events


def _source(url: str, title: str) -> Source:
    return Source.model_validate({"url": url, "title": title})


def _finding(sub_query: SubQuery, summary: str, sources: list[Source]) -> SubQueryFinding:
    facts = [
        KeyFact(statement=f"fact about {sub_query.question}", citation_ids=[s.id for s in sources])
    ]
    return SubQueryFinding(
        sub_query_id=sub_query.id,
        summary=summary,
        key_facts=facts,
        sources=sources,
    )


async def test_synthesizer_happy_path() -> None:
    sq1 = SubQuery(question="q1", rationale="r1", priority=Priority.HIGH)
    sq2 = SubQuery(question="q2", rationale="r2", priority=Priority.MEDIUM)
    src_a = _source("https://a.com", "A")
    src_b = _source("https://b.com", "B")
    findings = [
        _finding(sq1, "first finding", [src_a]),
        _finding(sq2, "second finding", [src_b]),
    ]

    tokens = [
        "# Executive Summary\n\n",
        "Big picture answer referencing [1] and [2].\n\n",
        "# Background\n\n",
        "Details [1].\n\n",
        "# Analysis\n\n",
        "More details [2].\n",
    ]
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, events = _make_emit()

    report = await synthesize_report(
        report_id=uuid4(),
        original_question="top",
        findings=findings,
        llm=llm,
        model="m",
        emit=emit,
    )

    assert report.executive_summary.startswith("Big picture")
    assert [s.heading for s in report.sections] == ["Background", "Analysis"]
    assert len(report.citations) == 2
    assert report.sections[0].citation_ids == [src_a.id]
    assert report.sections[1].citation_ids == [src_b.id]

    token_events = [e for e in events if isinstance(e, SynthesisToken)]
    assert len(token_events) == len(tokens)
    assert token_events[0].token == tokens[0]


async def test_synthesizer_dedupes_sources_across_findings() -> None:
    sq1 = SubQuery(question="q1", rationale="r", priority=Priority.HIGH)
    sq2 = SubQuery(question="q2", rationale="r", priority=Priority.HIGH)
    shared = _source("https://shared.com", "Shared")
    unique_b = _source("https://b.com", "B")
    # Finding 2 re-includes shared URL (different Source id!) — must dedup by URL.
    findings = [
        _finding(sq1, "first", [shared, unique_b]),
        _finding(sq2, "second", [_source("https://shared.com", "Shared")]),
    ]

    tokens = ["# Executive Summary\n\nSummary [1].\n\n# S1\n\nContent [2].\n"]
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, _ = _make_emit()

    report = await synthesize_report(
        report_id=uuid4(),
        original_question="top",
        findings=findings,
        llm=llm,
        model="m",
        emit=emit,
    )

    # Master list has exactly 2 sources: shared (first seen) and unique_b
    assert [str(c.url).rstrip("/") for c in report.citations] == [
        "https://shared.com",
        "https://b.com",
    ]
    assert report.citations[0].id == shared.id


async def test_synthesizer_handles_degraded_finding() -> None:
    """A failed finding (empty facts/sources) still goes into synthesis."""
    sq_ok = SubQuery(question="q1", rationale="r", priority=Priority.HIGH)
    sq_fail = SubQuery(question="q2", rationale="r", priority=Priority.HIGH)
    src = _source("https://ok.com", "OK")
    findings = [
        _finding(sq_ok, "ok summary", [src]),
        SubQueryFinding(
            sub_query_id=sq_fail.id,
            summary="Research failed: timeout",
            key_facts=[],
            sources=[],
        ),
    ]

    tokens = ["# Executive Summary\n\nOverview [1].\n\n# S1\n\nBody [1].\n"]
    llm = FakeLLM(tokens)
    emit, _ = _make_emit()

    report = await synthesize_report(
        report_id=uuid4(),
        original_question="top",
        findings=findings,
        llm=cast(LLMClient, llm),
        model="m",
        emit=emit,
    )

    # Prompt must mention the coverage gap for the synthesizer to respond to it.
    assert len(llm.calls) == 1
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "COVERAGE GAP" in prompt
    assert report.executive_summary == "Overview [1]."
    # Only one unique citation was available
    assert len(report.citations) == 1


async def test_synthesizer_raises_on_empty_output() -> None:
    tokens: list[str] = []
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, _ = _make_emit()

    with pytest.raises(SynthesizerError, match="no text"):
        await synthesize_report(
            report_id=uuid4(),
            original_question="q",
            findings=[],
            llm=llm,
            model="m",
            emit=emit,
        )


async def test_synthesizer_raises_when_no_level1_headings() -> None:
    tokens = ["Just some text, no headings at all.\n"]
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, _ = _make_emit()

    with pytest.raises(SynthesizerError, match="no level-1"):
        await synthesize_report(
            report_id=uuid4(),
            original_question="q",
            findings=[],
            llm=llm,
            model="m",
            emit=emit,
        )


async def test_synthesizer_ignores_out_of_range_citation_numbers() -> None:
    """Model hallucinates `[99]`; we silently drop it rather than crashing."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    src = _source("https://a.com", "A")
    findings = [_finding(sq, "s", [src])]

    tokens = ["# Executive Summary\n\nExec.\n\n# S1\n\nBody [1] and [99].\n"]
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, _ = _make_emit()

    report = await synthesize_report(
        report_id=uuid4(),
        original_question="q",
        findings=findings,
        llm=llm,
        model="m",
        emit=emit,
    )
    # Only [1] resolves; [99] is dropped
    assert report.sections[0].citation_ids == [src.id]


async def test_synthesizer_falls_back_when_exec_heading_missing() -> None:
    """If the model forgets '# Executive Summary', first block becomes the exec."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    src = _source("https://a.com", "A")
    findings = [_finding(sq, "s", [src])]

    tokens = ["# Overview\n\nOverview text.\n\n# Details\n\nDetails [1].\n"]
    llm = cast(LLMClient, FakeLLM(tokens))
    emit, _ = _make_emit()

    report = await synthesize_report(
        report_id=uuid4(),
        original_question="q",
        findings=findings,
        llm=llm,
        model="m",
        emit=emit,
    )
    assert report.executive_summary == "Overview text."
    assert [s.heading for s in report.sections] == ["Overview", "Details"]


async def test_synthesizer_formats_scholarly_citation_rows() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    paper = Source.model_validate(
        {
            "url": "https://doi.org/10.5555/3295222.3295349",
            "title": "Attention Is All You Need",
            "kind": "scholarly",
            "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"],
            "year": 2017,
            "venue": "NeurIPS",
            "doi": "10.5555/3295222.3295349",
            "citation_count": 90000,
        }
    )
    web = _source("https://a.com", "A")
    llm = FakeLLM(["# Executive Summary\n\nX [1] [2].\n\n# S\n\nY [1].\n"])
    emit, _ = _make_emit()
    await synthesize_report(
        report_id=uuid4(),
        original_question="top",
        findings=[_finding(sq, "f", [paper, web])],
        llm=cast(LLMClient, llm),
        model="m",
        emit=emit,
    )
    prompt = llm.calls[0]["messages"][0]["content"]
    assert (
        "1. Ashish Vaswani, Noam Shazeer, Niki Parmar et al. (2017). "
        "Attention Is All You Need. NeurIPS — https://doi.org/10.5555/3295222.3295349"
    ) in prompt
    assert "2. A — https://a.com/" in prompt


def test_citation_row_omits_missing_scholarly_parts() -> None:
    from ara.agents.synthesizer import _citation_row

    bare = Source.model_validate(
        {"url": "https://arxiv.org/abs/1", "title": "Preprint", "kind": "scholarly"}
    )
    assert _citation_row(3, bare) == "3. Preprint. — https://arxiv.org/abs/1"


def test_dedupe_prefers_later_scholarly_copy_of_a_web_source() -> None:
    from ara.agents.synthesizer import _dedupe_sources

    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    first = _source("https://a.com", "A")
    web_copy = _source("https://doi.org/10.1/x", "Plain")
    other = _source("https://b.com", "B")
    scholarly = Source.model_validate(
        {"url": "https://doi.org/10.1/x", "title": "Paper", "kind": "scholarly", "year": 2020}
    )
    later_web = _source("https://doi.org/10.1/x", "Plain again")
    findings = [
        _finding(sq, "one", [first, web_copy, other]),
        _finding(sq, "two", [scholarly]),
        _finding(sq, "three", [later_web]),
    ]
    deduped = _dedupe_sources(findings)
    assert [s.id for s in deduped] == [first.id, scholarly.id, other.id]  # position kept
