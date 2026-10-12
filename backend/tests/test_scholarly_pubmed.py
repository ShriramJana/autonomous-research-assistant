from __future__ import annotations

import httpx
import pytest
import respx

from ara.config import Settings
from ara.scholarly.catalogs import pubmed
from ara.scholarly.ratelimit import RateLimiter

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

EFETCH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">42846624</PMID>
    <Article PubModel="Electronic">
      <Journal>
        <Title>Frontiers in bioinformatics</Title>
        <JournalIssue CitedMedium="Internet"><PubDate><Year>2026</Year></PubDate></JournalIssue>
      </Journal>
      <ArticleTitle>Immunoinformatics-based design of a multi-epitope mRNA vaccine.</ArticleTitle>
      <Abstract>
        <AbstractText Label="BACKGROUND">Vaccines matter.</AbstractText>
        <AbstractText Label="METHODS">We designed <i>in silico</i> epitopes.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y">
          <LastName>Doe</LastName><ForeName>Jane</ForeName><Initials>J</Initials>
        </Author>
        <Author ValidYN="Y">
          <LastName>Roe</LastName><ForeName>Rick</ForeName><Initials>R</Initials>
        </Author>
      </AuthorList>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ReferenceList>
      <Reference><ArticleIdList>
        <ArticleId IdType="doi">10.1016/j.softx.2015.06.001</ArticleId>
      </ArticleIdList></Reference>
    </ReferenceList>
    <ArticleIdList>
      <ArticleId IdType="pubmed">42846624</ArticleId>
      <ArticleId IdType="doi">10.3389/fbinf.2026.1922523</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""


def _settings(key: str = "") -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.ncbi_api_key = key
    return s


@pytest.fixture(autouse=True)
def _fast_limiters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pubmed, "LIMITER_ANON", RateLimiter(0.0))
    monkeypatch.setattr(pubmed, "LIMITER_KEYED", RateLimiter(0.0))


async def test_pubmed_two_step_search_parses_article_with_scoped_doi() -> None:
    with respx.mock:
        es = respx.get(ESEARCH).mock(
            return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["42846624"]}})
        )
        ef = respx.get(EFETCH).mock(return_value=httpx.Response(200, text=EFETCH_XML))
        async with httpx.AsyncClient() as http:
            papers = await pubmed.search(
                ["mrna vaccine", "efficacy"], limit=5, http=http, settings=_settings()
            )
    es_params = es.calls[0].request.url.params
    assert es_params["term"] == "mrna vaccine AND efficacy"
    assert es_params["retmax"] == "5"
    assert es_params["retmode"] == "json"
    assert es_params["db"] == "pubmed"
    assert "api_key" not in es_params
    ef_params = ef.calls[0].request.url.params
    assert ef_params["id"] == "42846624"
    assert ef_params["retmode"] == "xml"
    [p] = papers
    assert p.catalog == "pubmed"
    assert p.title == "Immunoinformatics-based design of a multi-epitope mRNA vaccine."
    assert p.doi == "10.3389/fbinf.2026.1922523"  # NOT the reference-list DOI
    assert p.url == "https://doi.org/10.3389/fbinf.2026.1922523"
    assert p.authors == ("Doe J", "Roe R")
    assert (p.year, p.venue, p.citation_count) == (2026, "Frontiers in bioinformatics", None)
    assert p.abstract == "Vaccines matter. We designed in silico epitopes."


async def test_pubmed_passes_api_key_to_both_requests() -> None:
    with respx.mock:
        es = respx.get(ESEARCH).mock(
            return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}})
        )
        ef = respx.get(EFETCH).mock(return_value=httpx.Response(200, text=EFETCH_XML))
        async with httpx.AsyncClient() as http:
            await pubmed.search(["q"], limit=1, http=http, settings=_settings("ncbi-key"))
    assert es.calls[0].request.url.params["api_key"] == "ncbi-key"
    assert ef.calls[0].request.url.params["api_key"] == "ncbi-key"


async def test_pubmed_empty_idlist_skips_efetch() -> None:
    with respx.mock:
        respx.get(ESEARCH).mock(
            return_value=httpx.Response(200, json={"esearchresult": {"idlist": []}})
        )
        ef = respx.get(EFETCH).mock(return_value=httpx.Response(200, text=EFETCH_XML))
        async with httpx.AsyncClient() as http:
            assert await pubmed.search(["q"], limit=3, http=http, settings=_settings()) == []
    assert not ef.called


async def test_pubmed_falls_back_to_pubmed_url_without_doi() -> None:
    xml = EFETCH_XML.replace('<ArticleId IdType="doi">10.3389/fbinf.2026.1922523</ArticleId>', "")
    with respx.mock:
        respx.get(ESEARCH).mock(
            return_value=httpx.Response(200, json={"esearchresult": {"idlist": ["42846624"]}})
        )
        respx.get(EFETCH).mock(return_value=httpx.Response(200, text=xml))
        async with httpx.AsyncClient() as http:
            [p] = await pubmed.search(["q"], limit=3, http=http, settings=_settings())
    assert p.doi is None
    assert p.url == "https://pubmed.ncbi.nlm.nih.gov/42846624/"


@pytest.mark.parametrize(
    ("esearch", "efetch"),
    [
        (httpx.Response(429), httpx.Response(200, text=EFETCH_XML)),
        (httpx.Response(200, content=b"nope"), httpx.Response(200, text=EFETCH_XML)),
        (httpx.Response(200, json={"esearchresult": {}}), httpx.Response(200, text=EFETCH_XML)),
        (httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}}), httpx.Response(503)),
        (
            httpx.Response(200, json={"esearchresult": {"idlist": ["1"]}}),
            httpx.Response(200, text="<broken"),
        ),
    ],
)
async def test_pubmed_degrades_to_empty(esearch: httpx.Response, efetch: httpx.Response) -> None:
    with respx.mock:
        respx.get(ESEARCH).mock(return_value=esearch)
        respx.get(EFETCH).mock(return_value=efetch)
        async with httpx.AsyncClient() as http:
            assert await pubmed.search(["q"], limit=3, http=http, settings=_settings()) == []
