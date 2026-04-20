"""Unit tests for the researcher agent.

Mocks `LLMClient.complete_with_tools` with canned content-block lists that
simulate server-side web_search + client-side submit_finding responses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ara.agents import ResearcherError
from ara.agents.researcher import SUBMIT_FINDING_TOOL_NAME, research_sub_query
from ara.models.events import ResearcherProgress, ResearcherStarted, ResearchEvent
from ara.models.research import Priority, SubQuery, SubQueryFinding
from tests.conftest import make_usage


def _server_tool_use(name: str, tool_input: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "server_tool_use"
    b.name = name
    b.input = tool_input
    return b


def _tool_use(name: str, tool_input: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.name = name
    b.input = tool_input
    return b


def _make_response(
    content: list[Any],
    *,
    stop_reason: str = "tool_use",
    in_tokens: int = 100,
    out_tokens: int = 50,
) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.stop_reason = stop_reason
    response.usage = make_usage(in_tokens, out_tokens)
    return response


def _make_emit() -> tuple[Callable[[ResearchEvent], Awaitable[None]], list[ResearchEvent]]:
    events: list[ResearchEvent] = []

    async def emit(event: ResearchEvent) -> None:
        events.append(event)

    return emit, events


async def test_researcher_happy_path() -> None:
    sq = SubQuery(question="What is RAG?", rationale="Foundations.", priority=Priority.HIGH)
    response = _make_response(
        [
            _server_tool_use("web_search", {"query": "RAG retrieval augmented generation"}),
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "RAG augments LLMs with retrieved context.",
                    "key_facts": [
                        {
                            "statement": "RAG retrieves before generating.",
                            "source_urls": ["https://example.com/rag"],
                        }
                    ],
                    "sources": [{"url": "https://example.com/rag", "title": "RAG intro"}],
                },
            ),
        ]
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, events = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    assert isinstance(finding, SubQueryFinding)
    assert finding.sub_query_id == sq.id
    assert finding.summary == "RAG augments LLMs with retrieved context."
    assert len(finding.sources) == 1
    assert finding.key_facts[0].citation_ids == [finding.sources[0].id]

    assert any(isinstance(e, ResearcherStarted) for e in events)
    assert any(isinstance(e, ResearcherProgress) for e in events)


async def test_researcher_emits_progress_per_search() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [
            _server_tool_use("web_search", {"query": "q1"}),
            _server_tool_use("web_search", {"query": "q2"}),
            _server_tool_use("web_search", {"query": "q3"}),
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            ),
        ]
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, events = _make_emit()

    await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    progress_events = [e for e in events if isinstance(e, ResearcherProgress)]
    assert len(progress_events) == 3
    assert "q1" in progress_events[0].tool_call
    assert "q3" in progress_events[2].tool_call


async def test_researcher_raises_when_submit_finding_missing() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [_server_tool_use("web_search", {"query": "q"})],
        stop_reason="end_turn",
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, _ = _make_emit()

    with pytest.raises(ResearcherError, match="did not call"):
        await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)


async def test_researcher_raises_on_token_budget_exceeded() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            ),
        ],
        in_tokens=200_000,
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, _ = _make_emit()

    with pytest.raises(ResearcherError, match="budget exceeded"):
        await research_sub_query(
            sub_query=sq,
            llm=llm,
            model="m",
            emit=emit,
            input_token_budget=100_000,
        )


async def test_researcher_raises_on_malformed_submit_finding() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {"summary": "s", "sources": [{"url": "not-a-url", "title": "x"}]},
            ),
        ]
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, _ = _make_emit()

    with pytest.raises(ResearcherError, match="validation"):
        await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)


async def test_researcher_maps_multi_source_citations_to_uuids() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "multi-source fact",
                    "key_facts": [
                        {
                            "statement": "claim supported by two sources.",
                            "source_urls": ["https://a.com", "https://b.com"],
                        },
                    ],
                    "sources": [
                        {"url": "https://a.com", "title": "A"},
                        {"url": "https://b.com", "title": "B"},
                        {"url": "https://c.com", "title": "C (unused)"},
                    ],
                },
            ),
        ]
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, _ = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    by_url = {str(s.url).rstrip("/"): s.id for s in finding.sources}
    expected = [by_url["https://a.com"], by_url["https://b.com"]]
    assert finding.key_facts[0].citation_ids == expected


async def test_researcher_skips_unknown_cited_urls() -> None:
    """A key_fact citing a URL missing from sources gets empty citations."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    response = _make_response(
        [
            _tool_use(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [
                        {"statement": "real claim.", "source_urls": ["https://a.com"]},
                        {"statement": "orphan claim.", "source_urls": ["https://ghost.com"]},
                    ],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            ),
        ]
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)
    emit, _ = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    assert len(finding.key_facts[0].citation_ids) == 1
    assert finding.key_facts[1].citation_ids == []
