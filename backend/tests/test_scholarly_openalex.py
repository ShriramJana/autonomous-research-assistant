from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from ara.config import Settings
from ara.scholarly.catalogs import openalex
from ara.scholarly.ratelimit import RateLimiter

URL = "https://api.openalex.org/works"

FIXTURE: dict[str, Any] = {
    "results": [
        {
            "id": "https://openalex.org/W2741809807",
            "ids": {"openalex": "https://openalex.org/W2741809807"},
            "doi": "https://doi.org/10.1109/TVCG.2023.3327163",
            "display_name": "Attention Is All You Need",
            "publication_year": 2017,
            "cited_by_count": 90000,
            "authorships": [
                {"author": {"display_name": "Ashish Vaswani"}},
                {"author": {"display_name": "Noam Shazeer"}},
            ],
            "primary_location": {
                "source": {"display_name": "NeurIPS"},
                "landing_page_url": "https://arxiv.org/abs/1706.03762v7",
            },
            "abstract_inverted_index": {
                "Attention": [0],
                "is": [1],
                "all": [2],
                "you": [3],
                "need": [4],
            },
        },
        {"id": "https://openalex.org/W1", "display_name": "   "},  # untitled → skipped
    ]
}


def _settings(**kw: str) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    for k, v in kw.items():
        setattr(s, k, v)
    return s


@pytest.fixture(autouse=True)
def _fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(openalex, "LIMITER", RateLimiter(0.0))


async def test_openalex_parses_work_and_reconstructs_abstract() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json=FIXTURE))
        async with httpx.AsyncClient() as http:
            papers = await openalex.search(
                ["transformer", "attention"],
                limit=5,
                http=http,
                settings=_settings(openalex_mailto="me@example.com"),
            )
    params = route.calls[0].request.url.params
    assert params["search"] == "transformer attention"
    assert params["per-page"] == "5"
    assert params["mailto"] == "me@example.com"
    [p] = papers
    assert p.catalog == "openalex"
    assert p.title == "Attention Is All You Need"
    assert p.doi == "10.1109/tvcg.2023.3327163"
    assert p.url == "https://doi.org/10.1109/tvcg.2023.3327163"
    assert p.arxiv_id == "1706.03762"
    assert p.authors == ("Ashish Vaswani", "Noam Shazeer")
    assert (p.year, p.venue, p.citation_count) == (2017, "NeurIPS", 90000)
    assert p.abstract == "Attention is all you need"


async def test_openalex_omits_mailto_when_unset() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, json={"results": []}))
        async with httpx.AsyncClient() as http:
            assert await openalex.search(["q"], limit=3, http=http, settings=_settings()) == []
    assert "mailto" not in route.calls[0].request.url.params


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json={"results": "nope"}),
        httpx.Response(200, json=[1, 2]),
    ],
)
async def test_openalex_degrades_to_empty(response: httpx.Response) -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=response)
        async with httpx.AsyncClient() as http:
            assert await openalex.search(["q"], limit=3, http=http, settings=_settings()) == []


async def test_openalex_timeout_degrades_to_empty() -> None:
    with respx.mock:
        respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
        async with httpx.AsyncClient() as http:
            assert await openalex.search(["q"], limit=3, http=http, settings=_settings()) == []
