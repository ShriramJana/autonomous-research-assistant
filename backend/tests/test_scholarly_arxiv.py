from __future__ import annotations

import httpx
import pytest
import respx

from ara.config import Settings
from ara.scholarly.catalogs import arxiv
from ara.scholarly.ratelimit import RateLimiter

URL = "https://export.arxiv.org/api/query"

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2310.06825v2</id>
    <published>2023-10-10T17:59:58Z</published>
    <title>Mistral 7B</title>
    <summary>  We introduce Mistral 7B,
      a 7-billion-parameter language model.  </summary>
    <author><name>Albert Q. Jiang</name></author>
    <author><name>Alexandre Sablayrolles</name></author>
    <arxiv:primary_category term="cs.CL"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v7</id>
    <published>2017-06-12T17:57:34Z</published>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models.</summary>
    <author><name>Ashish Vaswani</name></author>
    <arxiv:doi>10.5555/3295222.3295349</arxiv:doi>
    <arxiv:journal_ref>NeurIPS 2017</arxiv:journal_ref>
  </entry>
</feed>
"""


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _fast_limiter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(arxiv, "LIMITER", RateLimiter(0.0))


async def test_arxiv_parses_entries_and_builds_phrase_query() -> None:
    with respx.mock:
        route = respx.get(URL).mock(return_value=httpx.Response(200, text=ATOM))
        async with httpx.AsyncClient() as http:
            papers = await arxiv.search(
                ["mistral 7b", "language model"], limit=2, http=http, settings=_settings()
            )
    params = route.calls[0].request.url.params
    assert params["search_query"] == 'all:"mistral 7b" AND all:"language model"'
    assert params["max_results"] == "2"
    first, second = papers
    assert first.catalog == "arxiv"
    assert first.arxiv_id == "2310.06825"
    assert first.url == "https://arxiv.org/abs/2310.06825"
    assert first.title == "Mistral 7B"
    assert first.abstract == "We introduce Mistral 7B, a 7-billion-parameter language model."
    assert first.authors == ("Albert Q. Jiang", "Alexandre Sablayrolles")
    assert (first.year, first.venue, first.doi, first.citation_count) == (2023, "arXiv", None, None)
    assert second.doi == "10.5555/3295222.3295349"
    assert second.url == "https://doi.org/10.5555/3295222.3295349"
    assert second.venue == "NeurIPS 2017"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, text="<feed>unclosed"),
        httpx.Response(200, text=""),
    ],
)
async def test_arxiv_degrades_to_empty(response: httpx.Response) -> None:
    with respx.mock:
        respx.get(URL).mock(return_value=response)
        async with httpx.AsyncClient() as http:
            assert await arxiv.search(["q"], limit=3, http=http, settings=_settings()) == []


async def test_arxiv_timeout_degrades_to_empty() -> None:
    with respx.mock:
        respx.get(URL).mock(side_effect=httpx.ConnectTimeout("slow"))
        async with httpx.AsyncClient() as http:
            assert await arxiv.search(["q"], limit=3, http=http, settings=_settings()) == []
