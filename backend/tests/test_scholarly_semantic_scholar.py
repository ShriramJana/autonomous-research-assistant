from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from ara.config import Settings
from ara.scholarly.catalogs import semantic_scholar
from ara.scholarly.ratelimit import RateLimiter

URL = "https://api.semanticscholar.org/graph/v1/paper/search"

FIXTURE: dict[str, Any] = {
    "total": 1,
    "data": [
        {
            "paperId": "abc123",
            "url": "https://www.semanticscholar.org/paper/abc123",
            "title": "Scaling Laws for Neural Language Models",
            "year": 2020,
            "venue": "arXiv.org",
            "abstract": "We study empirical scaling laws.",
            "citationCount": 3000,
            "externalIds": {"ArXiv": "2001.08361v1", "DOI": "10.48550/ARXIV.2001.08361"},
            "authors": [
                {"authorId": "1", "name": "Jared Kaplan"},
                {"authorId": "2", "name": "Sam McCandlish"},
            ],
        }
    ],
}


def _settings(key: str = "") -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.semantic_scholar_api_key = key
    return s


@pytest.fixture(autouse=True)
def _fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(semantic_scholar, "LIMITER", RateLimiter(0.0))


async def test_semantic_scholar_is_skipped_without_key() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))
        async with httpx.AsyncClient() as http:
            assert (
                await semantic_scholar.search(["q"], limit=3, http=http, settings=_settings()) == []
            )
    assert not route.called


async def test_semantic_scholar_parses_with_key_header() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))
        async with httpx.AsyncClient() as http:
            papers = await semantic_scholar.search(
                ["scaling laws"], limit=3, http=http, settings=_settings("s2-key")
            )
    req = route.calls[0].request
    assert req.headers["x-api-key"] == "s2-key"
    assert req.url.params["query"] == "scaling laws"
    assert req.url.params["limit"] == "3"
    assert "citationCount" in req.url.params["fields"]
    [p] = papers
    assert p.catalog == "semantic_scholar"
    assert p.doi == "10.48550/arxiv.2001.08361"
    assert p.arxiv_id == "2001.08361"
    assert p.url == "https://doi.org/10.48550/arxiv.2001.08361"
    assert p.authors == ("Jared Kaplan", "Sam McCandlish")
    assert (p.year, p.venue, p.citation_count) == (2020, "arXiv.org", 3000)
    assert p.abstract == "We study empirical scaling laws."


async def test_semantic_scholar_uses_landing_url_without_ids() -> None:
    body = {
        "data": [
            {"title": "T", "url": "https://www.semanticscholar.org/paper/x", "externalIds": {}}
        ]
    }
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as http:
            [p] = await semantic_scholar.search(["q"], limit=3, http=http, settings=_settings("k"))
    assert p.url == "https://www.semanticscholar.org/paper/x"
    assert p.authors == () and p.year is None and p.citation_count is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(200, content=b"<html>"),
        httpx.Response(200, json={"data": 5}),
    ],
)
async def test_semantic_scholar_degrades_to_empty(response: httpx.Response) -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=response)
        async with httpx.AsyncClient() as http:
            assert (
                await semantic_scholar.search(["q"], limit=3, http=http, settings=_settings("k"))
                == []
            )


async def test_semantic_scholar_tolerates_non_list_authors() -> None:
    url = "https://www.semanticscholar.org/paper/"
    body = {
        "data": [
            {"title": "Odd", "url": url + "a", "authors": True},
            {"title": "Fine", "url": url + "b"},
        ]
    }
    with respx.mock:
        respx.get(URL).mock(return_value=httpx.Response(200, json=body))
        async with httpx.AsyncClient() as http:
            papers = await semantic_scholar.search(
                ["q"], limit=3, http=http, settings=_settings("k")
            )
    assert [p.title for p in papers] == ["Odd", "Fine"]
    assert papers[0].authors == ()
