"""arXiv Atom API. Best-effort: the API stalled 46 s and then 503'd when probed."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from ara.config import Settings
from ara.scholarly.models import (
    Paper,
    arxiv_id_from_url,
    canonical_url,
    normalize_doi,
    trim_abstract,
)
from ara.scholarly.ratelimit import RateLimiter

URL = "https://export.arxiv.org/api/query"
LIMITER = RateLimiter(3.0)
_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
_YEAR_CHARS = 4


def _query(terms: list[str]) -> str:
    return " AND ".join(f'all:"{t}"' for t in terms)


async def search(
    terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
) -> list[Paper]:
    del settings  # arXiv needs no credentials; signature is shared across catalogs
    await LIMITER.acquire()
    try:
        resp = await http.get(
            URL, params={"search_query": _query(terms), "max_results": str(limit)}
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except (httpx.HTTPError, ET.ParseError):
        return []
    papers: list[Paper] = []
    for entry in root.findall("a:entry", _NS):
        paper = _parse_entry(entry)
        if paper is not None:
            papers.append(paper)
    return papers


def _text(entry: ET.Element, path: str) -> str:
    return " ".join((entry.findtext(path, "", _NS) or "").split())


def _authors(entry: ET.Element) -> tuple[str, ...]:
    return tuple(
        name.text.strip()
        for name in entry.findall("a:author/a:name", _NS)
        if name.text and name.text.strip()
    )


def _parse_entry(entry: ET.Element) -> Paper | None:
    arxiv_id = arxiv_id_from_url(_text(entry, "a:id"))
    title = _text(entry, "a:title")
    if not arxiv_id or not title:
        return None
    year_text = _text(entry, "a:published")[:_YEAR_CHARS]
    doi = normalize_doi(_text(entry, "arxiv:doi") or None)
    journal_ref = _text(entry, "arxiv:journal_ref")
    return Paper(
        catalog="arxiv",
        title=title,
        url=canonical_url(doi=doi, arxiv_id=arxiv_id, fallback=f"https://arxiv.org/abs/{arxiv_id}"),
        authors=_authors(entry),
        year=int(year_text) if year_text.isascii() and year_text.isdigit() else None,
        venue=journal_ref or "arXiv",
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=trim_abstract(_text(entry, "a:summary") or None),
        citation_count=None,
    )
