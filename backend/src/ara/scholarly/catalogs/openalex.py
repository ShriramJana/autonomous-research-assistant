"""OpenAlex works search (JSON). Backbone catalog: also indexes arXiv preprints."""

from __future__ import annotations

from typing import Any

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

URL = "https://api.openalex.org/works"
LIMITER = RateLimiter(0.1)


async def search(
    terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
) -> list[Paper]:
    params: dict[str, str] = {"search": " ".join(terms), "per-page": str(limit)}
    if settings.openalex_mailto:
        params["mailto"] = settings.openalex_mailto
    await LIMITER.acquire()
    try:
        resp = await http.get(URL, params=params)
        resp.raise_for_status()
        data: Any = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return []
    papers: list[Paper] = []
    for work in results:
        paper = _parse_work(work) if isinstance(work, dict) else None
        if paper is not None:
            papers.append(paper)
    return papers


def _reconstruct_abstract(index: Any) -> str | None:
    """OpenAlex ships abstracts as {word: [positions]}; put the words back in order."""
    if not isinstance(index, dict):
        return None
    positions: list[tuple[int, str]] = []
    for word, pos_list in index.items():
        if not isinstance(pos_list, list):
            continue
        positions.extend((pos, str(word)) for pos in pos_list if isinstance(pos, int))
    if not positions:
        return None
    positions.sort()
    return " ".join(word for _, word in positions)


def _authors(work: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    authorships = work.get("authorships")
    if not isinstance(authorships, list):
        return ()
    for authorship in authorships:
        author = authorship.get("author") if isinstance(authorship, dict) else None
        name = author.get("display_name") if isinstance(author, dict) else None
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return tuple(names)


def _venue_and_landing(work: dict[str, Any]) -> tuple[str | None, str | None]:
    location = work.get("primary_location")
    if not isinstance(location, dict):
        return None, None
    source = location.get("source")
    venue = source.get("display_name") if isinstance(source, dict) else None
    landing_page = location.get("landing_page_url")
    return (
        venue if isinstance(venue, str) and venue else None,
        landing_page if isinstance(landing_page, str) else None,
    )


def _parse_work(work: dict[str, Any]) -> Paper | None:
    title = work.get("display_name")
    if not isinstance(title, str) or not title.strip():
        return None
    ids = work.get("ids")
    landing = ids.get("openalex") if isinstance(ids, dict) else None
    if not isinstance(landing, str) or not landing:
        landing = work.get("id") if isinstance(work.get("id"), str) else None
    if not landing:
        return None
    venue, landing_page = _venue_and_landing(work)
    doi = normalize_doi(work.get("doi") if isinstance(work.get("doi"), str) else None)
    arxiv_id = arxiv_id_from_url(landing_page)
    year = work.get("publication_year")
    cited = work.get("cited_by_count")
    return Paper(
        catalog="openalex",
        title=" ".join(title.split()),
        url=canonical_url(doi=doi, arxiv_id=arxiv_id, fallback=landing),
        authors=_authors(work),
        year=year if isinstance(year, int) else None,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=trim_abstract(_reconstruct_abstract(work.get("abstract_inverted_index"))),
        citation_count=cited if isinstance(cited, int) else None,
    )
