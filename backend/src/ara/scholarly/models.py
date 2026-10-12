"""Scholarly domain types shared by the catalogs, the service and the agents.

`Paper` is what a catalog returns; `ScholarlyBundle` is the ranked, deduped
set handed to one researcher. URL canonicalisation lives here because it is
what lets the same paper found by two catalogs collapse into one `Source`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

CatalogId = Literal["openalex", "semantic_scholar", "arxiv", "pubmed"]
CATALOG_ORDER: tuple[CatalogId, ...] = ("openalex", "semantic_scholar", "arxiv", "pubmed")

ABSTRACT_MAX_CHARS = 1200
_AUTHORS_SHOWN = 3
_ARXIV_ABS_RE = re.compile(r"arxiv\.org/abs/([^\s?#]+)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:")


@dataclass(frozen=True)
class Paper:
    catalog: CatalogId
    title: str
    url: str
    authors: tuple[str, ...]
    year: int | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    abstract: str | None
    citation_count: int | None


@dataclass(frozen=True)
class ScholarlyBundle:
    terms: tuple[str, ...]
    papers: tuple[Paper, ...]
    counts: dict[str, int]

    def by_url(self) -> dict[str, Paper]:
        """Registry keyed by lower-cased normalised canonical URL."""
        return {normalize_url(p.url).lower(): p for p in self.papers}


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def normalize_doi(raw: str | None) -> str | None:
    if not raw:
        return None
    doi = raw.strip()
    lowered = doi.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            doi = doi[len(prefix) :]
            break
    doi = doi.strip().lower()
    return doi or None


def strip_arxiv_version(raw: str | None) -> str | None:
    if not raw:
        return None
    return _ARXIV_VERSION_RE.sub("", raw.strip()) or None


def arxiv_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _ARXIV_ABS_RE.search(url)
    return strip_arxiv_version(m.group(1)) if m else None


def canonical_url(*, doi: str | None, arxiv_id: str | None, fallback: str) -> str:
    if doi:
        return f"https://doi.org/{doi}"
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return fallback


def trim_abstract(text: str | None, limit: int = ABSTRACT_MAX_CHARS) -> str | None:
    if text is None:
        return None
    cleaned = " ".join(text.split())
    if not cleaned:
        return None
    return cleaned[:limit]


def authors_short(authors: Sequence[str], max_names: int = _AUTHORS_SHOWN) -> str:
    if not authors:
        return ""
    head = ", ".join(authors[:max_names])
    return f"{head} et al." if len(authors) > max_names else head
