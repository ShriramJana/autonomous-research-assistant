"""Semantic Scholar Graph API paper search (JSON).

Unauthenticated calls are throttled to the point of uselessness (every probe
returned 429), so this catalog runs only when an API key is configured.
"""

from __future__ import annotations

from typing import Any

import httpx

from ara.config import Settings
from ara.scholarly.models import (
    Paper,
    canonical_url,
    normalize_doi,
    strip_arxiv_version,
    trim_abstract,
)
from ara.scholarly.ratelimit import RateLimiter

URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,venue,abstract,citationCount,externalIds,url"
LIMITER = RateLimiter(1.0)


async def search(
    terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
) -> list[Paper]:
    key = settings.semantic_scholar_api_key
    if not key:
        return []
    await LIMITER.acquire()
    try:
        resp = await http.get(
            URL,
            params={"query": " ".join(terms), "limit": str(limit), "fields": FIELDS},
            headers={"x-api-key": key},
        )
        resp.raise_for_status()
        data: Any = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return []
    papers: list[Paper] = []
    for row in rows:
        paper = _parse_paper(row) if isinstance(row, dict) else None
        if paper is not None:
            papers.append(paper)
    return papers


def _parse_paper(row: dict[str, Any]) -> Paper | None:
    title = row.get("title")
    landing = row.get("url")
    if not isinstance(title, str) or not title.strip() or not isinstance(landing, str):
        return None
    ext = row.get("externalIds")
    ext = ext if isinstance(ext, dict) else {}
    doi = normalize_doi(ext.get("DOI") if isinstance(ext.get("DOI"), str) else None)
    arxiv_id = strip_arxiv_version(ext.get("ArXiv") if isinstance(ext.get("ArXiv"), str) else None)
    raw_authors = row.get("authors")
    authors = tuple(
        a["name"].strip()
        for a in (raw_authors if isinstance(raw_authors, list) else [])
        if isinstance(a, dict) and isinstance(a.get("name"), str) and a["name"].strip()
    )
    year = row.get("year")
    venue = row.get("venue")
    abstract = row.get("abstract")
    cited = row.get("citationCount")
    return Paper(
        catalog="semantic_scholar",
        title=" ".join(title.split()),
        url=canonical_url(doi=doi, arxiv_id=arxiv_id, fallback=landing),
        authors=authors,
        year=year if isinstance(year, int) else None,
        venue=venue if isinstance(venue, str) and venue else None,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=trim_abstract(abstract if isinstance(abstract, str) else None),
        citation_count=cited if isinstance(cited, int) else None,
    )
