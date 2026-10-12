"""PubMed via NCBI E-utilities: esearch (ids, JSON) then efetch (records, XML)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import httpx

from ara.config import Settings
from ara.scholarly.models import Paper, canonical_url, normalize_doi, trim_abstract
from ara.scholarly.ratelimit import RateLimiter

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
LIMITER_ANON = RateLimiter(0.34)  # 3 req/s without a key
LIMITER_KEYED = RateLimiter(0.1)  # 10 req/s with NCBI_API_KEY
_YEAR_CHARS = 4


async def search(
    terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
) -> list[Paper]:
    key = settings.ncbi_api_key
    limiter = LIMITER_KEYED if key else LIMITER_ANON
    base: dict[str, str] = {"db": "pubmed"}
    if key:
        base["api_key"] = key
    try:
        await limiter.acquire()
        es = await http.get(
            ESEARCH_URL,
            params={**base, "term": " AND ".join(terms), "retmax": str(limit), "retmode": "json"},
        )
        es.raise_for_status()
        ids = _id_list(es.json())
        if not ids:
            return []
        await limiter.acquire()
        ef = await http.get(EFETCH_URL, params={**base, "id": ",".join(ids), "retmode": "xml"})
        ef.raise_for_status()
        root = ET.fromstring(ef.text)
    except (httpx.HTTPError, ValueError, ET.ParseError):
        return []
    papers: list[Paper] = []
    for article in root.findall("PubmedArticle"):
        paper = _parse_article(article)
        if paper is not None:
            papers.append(paper)
    return papers


def _id_list(data: Any) -> list[str]:
    result = data.get("esearchresult") if isinstance(data, dict) else None
    ids = result.get("idlist") if isinstance(result, dict) else None
    if not isinstance(ids, list):
        return []
    return [i for i in ids if isinstance(i, str) and i]


def _abstract(article: ET.Element) -> str | None:
    parts = [
        " ".join("".join(t.itertext()).split()) for t in article.findall("Abstract/AbstractText")
    ]
    text = " ".join(p for p in parts if p)
    return text or None


def _authors(article: ET.Element) -> tuple[str, ...]:
    names: list[str] = []
    for author in article.findall("AuthorList/Author"):
        last = (author.findtext("LastName") or "").strip()
        initials = (author.findtext("Initials") or "").strip()
        if last:
            names.append(f"{last} {initials}".strip())
    return tuple(names)


def _year(article: ET.Element) -> int | None:
    text = (
        article.findtext("Journal/JournalIssue/PubDate/Year")
        or article.findtext("Journal/JournalIssue/PubDate/MedlineDate")
        or ""
    ).strip()[:_YEAR_CHARS]
    return int(text) if text.isascii() and text.isdigit() else None


def _doi(record: ET.Element) -> str | None:
    # Only the article's own id list: PubmedData/ReferenceList carries other papers' DOIs.
    for aid in record.findall("PubmedData/ArticleIdList/ArticleId"):
        if aid.get("IdType") == "doi" and aid.text:
            return normalize_doi(aid.text)
    return None


def _parse_article(record: ET.Element) -> Paper | None:
    pmid = (record.findtext("MedlineCitation/PMID") or "").strip()
    article = record.find("MedlineCitation/Article")
    if not pmid or article is None:
        return None
    title = " ".join((article.findtext("ArticleTitle") or "").split())
    if not title:
        return None
    doi = _doi(record)
    venue = (article.findtext("Journal/Title") or "").strip() or None
    return Paper(
        catalog="pubmed",
        title=title,
        url=canonical_url(
            doi=doi, arxiv_id=None, fallback=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        ),
        authors=_authors(article),
        year=_year(article),
        venue=venue,
        doi=doi,
        arxiv_id=None,
        abstract=trim_abstract(_abstract(article)),
        citation_count=None,
    )
