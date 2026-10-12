"""Unit tests for the researcher agent.

Mocks `llm.complete_with_tools` with canned `CompletionResult` values that
simulate server-side web_search + client-side submit_finding responses.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ara.agents import ResearcherError
from ara.agents.researcher import (
    RESEARCHER_OFFLINE_SYSTEM_PROMPT,
    RESEARCHER_SYSTEM_PROMPT,
    RESEARCHER_TAVILY_SYSTEM_PROMPT,
    SCHOLARLY_ADDENDUM,
    SCHOLARLY_OFFLINE_ADDENDUM,
    SUBMIT_FINDING_TOOL_NAME,
    research_sub_query,
)
from ara.llm.client import WEB_SEARCH_TOOL_TYPE, CompletionResult, ToolUse
from ara.models.events import ResearcherProgress, ResearcherStarted, ResearchEvent
from ara.models.research import Priority, SubQuery, SubQueryFinding
from ara.scholarly.models import Paper, ScholarlyBundle


def _tu(name: str, payload: dict[str, Any]) -> ToolUse:
    return ToolUse(id=f"id-{name}", name=name, input=payload)


def _result(
    *,
    tool_uses: list[ToolUse] | None = None,
    server_tool_uses: list[ToolUse] | None = None,
    stop_reason: str = "tool_use",
    in_tokens: int = 100,
    out_tokens: int = 50,
) -> CompletionResult:
    return CompletionResult(
        text="",
        tool_uses=tool_uses or [],
        server_tool_uses=server_tool_uses or [],
        stop_reason=stop_reason,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )


def _make_emit() -> tuple[Callable[[ResearchEvent], Awaitable[None]], list[ResearchEvent]]:
    events: list[ResearchEvent] = []

    async def emit(event: ResearchEvent) -> None:
        events.append(event)

    return emit, events


async def test_researcher_happy_path() -> None:
    sq = SubQuery(question="What is RAG?", rationale="Foundations.", priority=Priority.HIGH)
    result = _result(
        server_tool_uses=[_tu("web_search", {"query": "RAG retrieval augmented generation"})],
        tool_uses=[
            _tu(
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
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, events = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)
    assert isinstance(finding, SubQueryFinding)
    assert finding.sub_query_id == sq.id
    assert len(finding.sources) == 1
    assert finding.summary == "RAG augments LLMs with retrieved context."
    assert finding.key_facts[0].citation_ids == [finding.sources[0].id]
    assert any(isinstance(e, ResearcherStarted) for e in events)
    assert any(isinstance(e, ResearcherProgress) for e in events)


async def test_researcher_emits_progress_per_search() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        server_tool_uses=[
            _tu("web_search", {"query": "q1"}),
            _tu("web_search", {"query": "q2"}),
            _tu("web_search", {"query": "q3"}),
        ],
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, events = _make_emit()

    await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    progress_events = [e for e in events if isinstance(e, ResearcherProgress)]
    assert len(progress_events) == 3
    assert "q1" in progress_events[0].tool_call
    assert "q3" in progress_events[2].tool_call


async def test_researcher_raises_when_submit_finding_missing() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        server_tool_uses=[_tu("web_search", {"query": "q"})],
        stop_reason="end_turn",
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    with pytest.raises(ResearcherError, match="did not call"):
        await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)


async def test_researcher_raises_on_token_budget_exceeded() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            )
        ],
        in_tokens=200_000,
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
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
    result = _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {"summary": "s", "sources": [{"url": "not-a-url", "title": "x"}]},
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    with pytest.raises(ResearcherError, match="validation"):
        await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)


async def test_researcher_maps_multi_source_citations_to_uuids() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        tool_uses=[
            _tu(
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
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    by_url = {str(s.url).rstrip("/"): s.id for s in finding.sources}
    expected = [by_url["https://a.com"], by_url["https://b.com"]]
    assert finding.key_facts[0].citation_ids == expected


async def test_researcher_includes_web_search_tool_by_default() -> None:
    """When web_search is enabled (default), the tools list carries web_search."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    kwargs = llm.complete_with_tools.await_args.kwargs
    tool_types = {t.get("type") for t in kwargs["tools"] if isinstance(t, dict)}
    tool_names = {t.get("name") for t in kwargs["tools"] if isinstance(t, dict)}
    assert WEB_SEARCH_TOOL_TYPE in tool_types
    assert SUBMIT_FINDING_TOOL_NAME in tool_names


async def test_researcher_omits_web_search_when_disabled() -> None:
    """With web_search disabled, the tool list is submit_finding only and the
    offline system prompt is used."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "offline answer.",
                    "key_facts": [{"statement": "claim.", "source_urls": ["https://arxiv.org"]}],
                    "sources": [{"url": "https://arxiv.org", "title": "arxiv"}],
                },
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit, web_search_enabled=False)

    kwargs = llm.complete_with_tools.await_args.kwargs
    tool_types = {t.get("type") for t in kwargs["tools"] if isinstance(t, dict)}
    assert WEB_SEARCH_TOOL_TYPE not in tool_types
    assert kwargs["system"] == RESEARCHER_OFFLINE_SYSTEM_PROMPT


async def test_researcher_skips_unknown_cited_urls() -> None:
    """A key_fact citing a URL missing from sources gets empty citations."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    result = _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [
                        {"statement": "real claim.", "source_urls": ["https://a.com"]},
                        {"statement": "orphan claim.", "source_urls": ["https://ghost.com"]},
                    ],
                    "sources": [{"url": "https://a.com", "title": "A"}],
                },
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, _ = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)

    assert len(finding.key_facts[0].citation_ids) == 1
    assert finding.key_facts[1].citation_ids == []


# ---------------------------------------------------------------------------
# Tavily loop tests (non-Anthropic / client-side search dispatch)
# ---------------------------------------------------------------------------


class _ScriptedLLM:
    """Fake LLMClient that returns a queued CompletionResult per call."""

    provider = "openai"
    supports_server_side_search = False

    def __init__(self, results: list[CompletionResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def complete_with_tools(self, **kwargs: Any) -> CompletionResult:
        self.calls.append(kwargs)
        return self._results.pop(0)


async def test_researcher_tavily_loop_searches_then_submits(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    searched: list[str] = []

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        searched.append(query)
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="What is RAG?", rationale="r", priority=Priority.HIGH)
    llm = _ScriptedLLM(
        [
            _result(tool_uses=[_tu("web_search", {"query": "rag basics"})], stop_reason="tool_use"),
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "RAG augments LLMs.",
                            "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            ),
        ]
    )
    emit, events = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="gpt-4o", emit=emit, tavily_api_key="k"
    )

    assert searched == ["rag basics"]
    assert finding.summary == "RAG augments LLMs."
    assert any(isinstance(e, ResearcherProgress) for e in events)
    # Second call must carry the assistant tool-call turn + tool result turn.
    second_msgs = llm.calls[1]["messages"]
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in second_msgs)
    assert any(m["role"] == "tool" for m in second_msgs)


async def test_researcher_tavily_loop_raises_when_never_submits(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM([_result(tool_uses=[_tu("web_search", {"query": "q"})]) for _ in range(10)])
    emit, _ = _make_emit()
    with pytest.raises(ResearcherError):
        await research_sub_query(
            sub_query=sq, llm=llm, model="gpt-4o", emit=emit, max_iterations=2, tavily_api_key="k"
        )


async def test_researcher_tavily_loop_raises_on_budget_exceeded(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM([_result(tool_uses=[_tu("web_search", {"query": "q"})], in_tokens=200_000)])
    emit, _ = _make_emit()
    with pytest.raises(ResearcherError, match="budget exceeded"):
        await research_sub_query(
            sub_query=sq,
            llm=llm,
            model="gpt-4o",
            emit=emit,
            input_token_budget=100_000,
            tavily_api_key="k",
        )


async def test_researcher_tavily_loop_raises_when_stuck(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM([_result(tool_uses=[], stop_reason="end_turn")])
    emit, _ = _make_emit()
    with pytest.raises(ResearcherError, match="called neither"):
        await research_sub_query(
            sub_query=sq, llm=llm, model="gpt-4o", emit=emit, tavily_api_key="k"
        )


async def test_tavily_loop_invokes_on_tavily_search(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    counter = {"n": 0}

    async def on_search() -> None:
        counter["n"] += 1

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM(
        [
            _result(
                tool_uses=[_tu("web_search", {"query": "a"}), _tu("web_search", {"query": "b"})]
            ),
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "s",
                            "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            ),
        ]
    )
    emit, _ = _make_emit()
    await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="gpt-4o",
        emit=emit,
        tavily_api_key="k",
        on_tavily_search=on_search,
    )
    assert counter["n"] == 2  # one per web_search call


async def test_researcher_offline_works_for_openai_client() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM(
        [
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "offline.",
                            "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            )
        ]
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="gpt-4o", emit=emit, web_search_enabled=False
    )
    assert finding.summary == "offline."


async def test_offline_path_drops_sources() -> None:
    """Small models invent sources when they can't browse; offline findings carry none."""
    finding_input = {
        "summary": "s",
        "key_facts": [{"statement": "f", "source_urls": ["https://example.com/"]}],
        "sources": [{"url": "https://example.com/", "title": "Made up"}],
    }
    llm = _ScriptedLLM([_result(tool_uses=[_tu(SUBMIT_FINDING_TOOL_NAME, finding_input)])])
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, web_search_enabled=False
    )
    assert finding.sources == []
    assert finding.key_facts
    assert all(f.citation_ids == [] for f in finding.key_facts)


# ---------------------------------------------------------------------------
# Scholarly pre-fetch injection
# ---------------------------------------------------------------------------

PAPER = Paper(
    catalog="openalex",
    title="Attention Is All You Need",
    url="https://doi.org/10.5555/3295222.3295349",
    authors=("Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit"),
    year=2017,
    venue="NeurIPS",
    doi="10.5555/3295222.3295349",
    arxiv_id="1706.03762",
    abstract="The dominant sequence transduction models are based on RNNs.",
    citation_count=90000,
)
BUNDLE = ScholarlyBundle(
    terms=("transformer", "attention"), papers=(PAPER,), counts={"openalex": 1}
)
EMPTY_BUNDLE = ScholarlyBundle(terms=("x",), papers=(), counts={"openalex": 0})


def _fetch(bundle: ScholarlyBundle) -> Any:
    async def fetch() -> ScholarlyBundle:
        return bundle

    return fetch


def _submit(sources: list[dict[str, str]], urls: list[str]) -> CompletionResult:
    return _result(
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "s",
                    "key_facts": [{"statement": "f", "source_urls": urls}],
                    "sources": sources,
                },
            )
        ]
    )


async def test_scholarly_fetch_emits_progress_after_started_and_injects_block() -> None:
    sq = SubQuery(question="How do transformers work?", rationale="r", priority=Priority.HIGH)
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": PAPER.url, "title": "whatever"}], [PAPER.url])
    )
    emit, events = _make_emit()

    await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(BUNDLE)
    )

    assert isinstance(events[0], ResearcherStarted)
    assert isinstance(events[1], ResearcherProgress)
    assert events[1].tool_call == "scholarly_search(['transformer', 'attention']) → 1 papers"
    kwargs = llm.complete_with_tools.await_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert content.startswith("How do transformers work?")
    assert "CANDIDATE SCHOLARLY SOURCES" in content
    assert "[S1] Attention Is All You Need" in content
    assert (
        "Ashish Vaswani, Noam Shazeer, Niki Parmar et al. (2017) · NeurIPS · 90000 citations"
        in content
    )
    assert f"URL: {PAPER.url}" in content
    assert "dominant sequence transduction" in content
    assert kwargs["system"] == RESEARCHER_SYSTEM_PROMPT + "\n" + SCHOLARLY_ADDENDUM


async def test_cited_scholarly_url_is_enriched_from_registry_not_model() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit(
            [
                {"url": PAPER.url, "title": "Model-made-up title"},
                {"url": "https://blog.example.com/p", "title": "Blog"},
            ],
            [PAPER.url, "https://blog.example.com/p"],
        )
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(BUNDLE)
    )

    paper_src, web_src = finding.sources
    assert paper_src.kind == "scholarly"
    assert paper_src.title == "Attention Is All You Need"  # registry wins
    assert paper_src.authors == list(PAPER.authors)
    assert (paper_src.year, paper_src.venue, paper_src.doi, paper_src.citation_count) == (
        2017,
        "NeurIPS",
        "10.5555/3295222.3295349",
        90000,
    )
    assert web_src.kind == "web" and web_src.authors == []
    assert finding.key_facts[0].citation_ids == [paper_src.id, web_src.id]


async def test_cited_scholarly_url_matches_after_normalization() -> None:
    """Trailing slash / different case still resolve to the candidate paper."""
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    cited = "https://DOI.org/10.5555/3295222.3295349/"
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": cited, "title": "t"}], [cited])
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(BUNDLE)
    )
    [src] = finding.sources
    assert src.kind == "scholarly"
    assert str(src.url) == PAPER.url  # canonicalised to the registry URL
    assert finding.key_facts[0].citation_ids == [src.id]


async def test_empty_bundle_emits_zero_papers_and_plain_message() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": "https://a.com", "title": "A"}], ["https://a.com"])
    )
    emit, events = _make_emit()
    await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(EMPTY_BUNDLE)
    )
    progress = [e for e in events if isinstance(e, ResearcherProgress)]
    assert progress[0].tool_call == "scholarly_search(['x']) → 0 papers"
    kwargs = llm.complete_with_tools.await_args.kwargs
    assert kwargs["messages"][0]["content"] == "q"
    assert kwargs["system"] == RESEARCHER_SYSTEM_PROMPT


async def test_no_fetch_keeps_legacy_behaviour() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": "https://a.com", "title": "A"}], ["https://a.com"])
    )
    emit, events = _make_emit()
    await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)
    assert not any(isinstance(e, ResearcherProgress) and "scholarly" in e.tool_call for e in events)
    assert llm.complete_with_tools.await_args.kwargs["messages"][0]["content"] == "q"


async def test_failing_fetch_degrades_to_no_papers() -> None:
    async def broken() -> ScholarlyBundle:
        raise RuntimeError("catalog down")

    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": "https://a.com", "title": "A"}], ["https://a.com"])
    )
    emit, events = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=broken
    )
    assert finding.summary == "s"
    progress = [e for e in events if isinstance(e, ResearcherProgress)]
    assert progress[0].tool_call == "scholarly_search([]) → 0 papers"


async def test_offline_keeps_only_bundle_backed_sources_and_prunes_citations() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = _ScriptedLLM(
        [
            _submit(
                [{"url": PAPER.url, "title": "t"}, {"url": "https://made.up/x", "title": "Fake"}],
                [PAPER.url, "https://made.up/x"],
            )
        ]
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(BUNDLE),
    )
    [src] = finding.sources
    assert src.kind == "scholarly" and str(src.url) == PAPER.url
    assert finding.key_facts[0].citation_ids == [src.id]
    assert (
        llm.calls[0]["system"]
        == RESEARCHER_OFFLINE_SYSTEM_PROMPT + "\n" + SCHOLARLY_OFFLINE_ADDENDUM
    )


async def test_tavily_loop_receives_scholarly_block(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = _ScriptedLLM(
        [
            _result(tool_uses=[_tu("web_search", {"query": "x"})]),
            _submit([{"url": PAPER.url, "title": "t"}], [PAPER.url]),
        ]
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="gpt-4o",
        emit=emit,
        tavily_api_key="k",
        scholarly_fetch=_fetch(BUNDLE),
    )
    first_user = llm.calls[0]["messages"][0]["content"]
    assert "CANDIDATE SCHOLARLY SOURCES" in first_user
    assert llm.calls[0]["system"] == RESEARCHER_TAVILY_SYSTEM_PROMPT + "\n" + SCHOLARLY_ADDENDUM
    assert finding.sources[0].kind == "scholarly"


SICI_URL = "https://doi.org/10.1002/(sici)1097-4636(199706)35:4<487::aid-jbm8>3.0.co;2-i"
SICI_PAPER = Paper(
    catalog="openalex",
    title="SICI paper",
    url=SICI_URL,
    authors=("A B",),
    year=1997,
    venue=None,
    doi=None,
    arxiv_id=None,
    abstract=None,
    citation_count=None,
)


async def test_offline_keeps_paper_whose_url_has_angle_brackets() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    llm = _ScriptedLLM([_submit([{"url": SICI_URL, "title": "t"}], [SICI_URL])])
    emit, _ = _make_emit()
    bundle = ScholarlyBundle(terms=("s",), papers=(SICI_PAPER,), counts={"openalex": 1})
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(bundle),
    )
    [src] = finding.sources
    assert src.kind == "scholarly"
    assert finding.key_facts[0].citation_ids == [src.id]


async def test_key_fact_citing_case_variant_resolves_to_canonical_source() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    variant = "https://DOI.org/10.5555/3295222.3295349/"
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_submit([{"url": PAPER.url, "title": "t"}], [variant])
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(BUNDLE)
    )
    [src] = finding.sources
    assert finding.key_facts[0].citation_ids == [src.id]


async def test_raw_and_canonical_variants_dedupe_to_one_source() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    variant = "https://DOI.org/10.5555/3295222.3295349/"
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(
        return_value=_result(
            tool_uses=[
                _tu(
                    SUBMIT_FINDING_TOOL_NAME,
                    {
                        "summary": "s",
                        "key_facts": [
                            {"statement": "f", "source_urls": [variant, PAPER.url]},
                        ],
                        "sources": [
                            {"url": variant, "title": "a"},
                            {"url": PAPER.url, "title": "b"},
                        ],
                    },
                )
            ]
        )
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="m", emit=emit, scholarly_fetch=_fetch(BUNDLE)
    )
    [src] = finding.sources
    assert src.kind == "scholarly"
    assert finding.key_facts[0].citation_ids == [src.id]


# ---------------------------------------------------------------------------
# Key facts citing candidate papers that the model left out of `sources`
# ---------------------------------------------------------------------------


def _submit_raw(payload: dict[str, Any]) -> CompletionResult:
    return _result(tool_uses=[_tu(SUBMIT_FINDING_TOOL_NAME, {"summary": "s", **payload})])


def _scholarly_llm(web: bool, result: CompletionResult) -> Any:
    if not web:
        return _ScriptedLLM([result])
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    return llm


@pytest.mark.parametrize("web", [False, True])
@pytest.mark.parametrize(
    "sources_field",
    [{}, {"sources": []}, {"sources": None}],
    ids=["no-sources-key", "empty-sources", "null-sources"],
)
async def test_key_fact_citing_registry_paper_creates_the_source(
    web: bool, sources_field: dict[str, Any]
) -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    payload = {"key_facts": [{"statement": "f", "source_urls": [PAPER.url]}], **sources_field}
    llm = _scholarly_llm(web, _submit_raw(payload))
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=web,
        scholarly_fetch=_fetch(BUNDLE),
    )
    [src] = finding.sources
    assert src.kind == "scholarly"
    assert str(src.url) == PAPER.url
    assert src.title == PAPER.title
    assert finding.key_facts[0].citation_ids == [src.id]


async def test_key_facts_citing_same_paper_twice_share_one_created_source() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    variant = "https://DOI.org/10.5555/3295222.3295349/"
    payload = {
        "key_facts": [
            {"statement": "a", "source_urls": [PAPER.url, variant]},
            {"statement": "b", "source_urls": [variant]},
        ]
    }
    llm = _ScriptedLLM([_submit_raw(payload)])
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(BUNDLE),
    )
    [src] = finding.sources
    assert [f.citation_ids for f in finding.key_facts] == [[src.id], [src.id]]


@pytest.mark.parametrize("web", [False, True])
async def test_key_fact_citing_unknown_url_without_sources_stays_uncited(web: bool) -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    payload = {"key_facts": [{"statement": "f", "source_urls": ["https://made.up/x"]}]}
    llm = _scholarly_llm(web, _submit_raw(payload))
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=web,
        scholarly_fetch=_fetch(BUNDLE),
    )
    assert finding.sources == []
    assert finding.key_facts[0].citation_ids == []


def test_offline_addendum_asks_to_list_cited_candidates_in_sources() -> None:
    assert "List every candidate paper you cite in `sources` as well (url + title)." in (
        SCHOLARLY_OFFLINE_ADDENDUM
    )


async def test_key_fact_citing_arxiv_pdf_variant_matches_doi_canonical_paper() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    cited = "http://arxiv.org/pdf/1706.03762v7"
    payload = {
        "key_facts": [{"statement": "f", "source_urls": [cited]}],
        "sources": [{"url": cited, "title": "t"}],
    }
    llm = _ScriptedLLM([_submit_raw(payload)])
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(BUNDLE),
    )
    [src] = finding.sources
    assert src.kind == "scholarly"
    assert str(src.url) == PAPER.url  # canonical DOI URL, not the cited PDF link
    assert finding.key_facts[0].citation_ids == [src.id]


def _bundle_with(**kw: Any) -> ScholarlyBundle:
    from dataclasses import replace

    return ScholarlyBundle(terms=("t",), papers=(replace(PAPER, **kw),), counts={"openalex": 1})


async def test_registry_title_longer_than_limit_is_clipped() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    long_title = "Long \n  title " + "x" * 600  # catalogs do not trim titles
    llm = _ScriptedLLM([_submit([{"url": PAPER.url, "title": "t"}], [PAPER.url])])
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(_bundle_with(title=long_title)),
    )
    [src] = finding.sources
    assert len(src.title) == 500
    assert src.title.startswith("Long title xxx")  # whitespace collapsed before the cut


async def test_stored_author_list_is_capped() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.HIGH)
    authors = tuple(f"Author {i}" for i in range(40))
    llm = _ScriptedLLM([_submit([{"url": PAPER.url, "title": "t"}], [PAPER.url])])
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq,
        llm=llm,
        model="m",
        emit=emit,
        web_search_enabled=False,
        scholarly_fetch=_fetch(_bundle_with(authors=authors)),
    )
    [src] = finding.sources
    assert src.authors == list(authors[:25])
