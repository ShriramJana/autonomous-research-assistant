"""`fetch_papers`: query the enabled catalogs in parallel, dedupe, rank, cut.

Never raises. A catalog that errors, times out or hangs contributes nothing;
the bundle guard returns whatever finished.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import replace

import httpx

from ara.config import Settings
from ara.scholarly import catalogs as catalogs_mod
from ara.scholarly.models import CATALOG_ORDER, CatalogId, Paper, ScholarlyBundle, canonical_url

DEFAULT_LIMIT = 8
_CATALOG_TIMEOUT_S = 15.0
_BUNDLE_TIMEOUT_S = 20.0
_USER_AGENT = "autonomous-research-assistant/1.0 (+https://ara.llmtechno.com)"
_TITLE_STRIP_RE = re.compile(r"[^a-z0-9]+")


async def fetch_papers(
    terms: list[str],
    *,
    settings: Settings,
    limit: int = DEFAULT_LIMIT,
    http: httpx.AsyncClient | None = None,
) -> ScholarlyBundle:
    clean = [t.strip() for t in terms if t.strip()]
    if not clean:
        return ScholarlyBundle(terms=(), papers=(), counts={})
    enabled = catalogs_mod.enabled_catalogs(settings)
    if http is None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(_CATALOG_TIMEOUT_S),
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            results = await _run_all(clean, enabled, limit=limit, http=client, settings=settings)
    else:
        results = await _run_all(clean, enabled, limit=limit, http=http, settings=settings)
    ordered = [p for c in CATALOG_ORDER for p in results.get(c, [])]
    ranked = rank_papers(merge_papers(ordered))[:limit]
    return ScholarlyBundle(
        terms=tuple(clean),
        papers=tuple(ranked),
        counts={c: len(ps) for c, ps in results.items()},
    )


async def _run_all(
    terms: list[str],
    enabled: list[CatalogId],
    *,
    limit: int,
    http: httpx.AsyncClient,
    settings: Settings,
) -> dict[CatalogId, list[Paper]]:
    tasks: dict[CatalogId, asyncio.Task[list[Paper]]] = {
        c: asyncio.create_task(
            _call(catalogs_mod.CATALOGS[c], terms, limit=limit, http=http, settings=settings)
        )
        for c in enabled
    }
    done, pending = await asyncio.wait(tasks.values(), timeout=_BUNDLE_TIMEOUT_S)
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    out: dict[CatalogId, list[Paper]] = {}
    for catalog, task in tasks.items():
        ok = task in done and not task.cancelled() and task.exception() is None
        out[catalog] = task.result() if ok else []
    return out


async def _call(
    search: catalogs_mod.CatalogSearch,
    terms: list[str],
    *,
    limit: int,
    http: httpx.AsyncClient,
    settings: Settings,
) -> list[Paper]:
    """Await a catalog call; `create_task` needs a coroutine, the Protocol says Awaitable."""
    return await search(terms, limit=limit, http=http, settings=settings)


def _norm_title(title: str) -> str:
    return _TITLE_STRIP_RE.sub("", title.lower())


def _keys(paper: Paper) -> list[str]:
    keys: list[str] = []
    if paper.doi:
        keys.append(f"doi:{paper.doi}")
    if paper.arxiv_id:
        keys.append(f"arxiv:{paper.arxiv_id}")
    title = _norm_title(paper.title)
    if title:
        keys.append(f"title:{title}")
    return keys


def _fill(base: Paper, other: Paper) -> Paper:
    """Keep `base`, fill its gaps from `other`, recompute the canonical URL."""
    doi = base.doi or other.doi
    arxiv_id = base.arxiv_id or other.arxiv_id
    merged = replace(
        base,
        authors=base.authors or other.authors,
        year=base.year if base.year is not None else other.year,
        venue=base.venue or other.venue,
        doi=doi,
        arxiv_id=arxiv_id,
        abstract=base.abstract or other.abstract,
        citation_count=(
            base.citation_count if base.citation_count is not None else other.citation_count
        ),
    )
    return replace(merged, url=canonical_url(doi=doi, arxiv_id=arxiv_id, fallback=base.url))


def merge_papers(papers: list[Paper]) -> list[Paper]:
    """First-seen-wins dedupe across DOI, arXiv id and normalised title."""
    merged: list[Paper] = []
    index: dict[str, int] = {}
    for paper in papers:
        keys = _keys(paper)
        hit = next((index[k] for k in keys if k in index), None)
        if hit is None:
            hit = len(merged)
            merged.append(paper)
        else:
            merged[hit] = _fill(merged[hit], paper)
        for k in keys:
            index.setdefault(k, hit)
    return merged


def rank_papers(papers: list[Paper]) -> list[Paper]:
    return sorted(
        papers,
        key=lambda p: (-(p.citation_count or 0), -(p.year or 0), CATALOG_ORDER.index(p.catalog)),
    )
