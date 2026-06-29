from __future__ import annotations

import httpx
import respx

from ara.llm.search import SearchResult, format_search_results, tavily_search

TAVILY_URL = "https://api.tavily.com/search"


async def test_tavily_search_parses_results() -> None:
    with respx.mock:
        respx.post(TAVILY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "T1", "url": "https://a.com", "content": "c1"},
                        {"title": "T2", "url": "https://b.com", "content": "c2"},
                    ]
                },
            )
        )
        results = await tavily_search("q", api_key="k")
    assert results == [
        SearchResult(title="T1", url="https://a.com", content="c1"),
        SearchResult(title="T2", url="https://b.com", content="c2"),
    ]


async def test_tavily_search_empty_key_returns_empty() -> None:
    results = await tavily_search("q", api_key=None)
    assert results == []


async def test_tavily_search_http_error_degrades_to_empty() -> None:
    with respx.mock:
        respx.post(TAVILY_URL).mock(return_value=httpx.Response(500))
        results = await tavily_search("q", api_key="k")
    assert results == []


def test_format_search_results_renders_rows() -> None:
    text = format_search_results(
        [SearchResult(title="T1", url="https://a.com", content="c1")]
    )
    assert "T1" in text
    assert "https://a.com" in text
    assert "c1" in text


def test_format_empty_results() -> None:
    assert "no results" in format_search_results([]).lower()
