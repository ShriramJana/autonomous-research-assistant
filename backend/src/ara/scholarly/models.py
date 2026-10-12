"""Scholarly domain types shared by the catalogs, the service and the agents.

`Paper` is what a catalog returns; `ScholarlyBundle` is the ranked, deduped
set handed to one researcher. URL canonicalisation lives here because it is
what lets the same paper found by two catalogs collapse into one `Source`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Literal

CatalogId = Literal["openalex", "semantic_scholar", "arxiv", "pubmed"]
CATALOG_ORDER: tuple[CatalogId, ...] = ("openalex", "semantic_scholar", "arxiv", "pubmed")

ABSTRACT_MAX_CHARS = 1200
_AUTHORS_SHOWN = 3
_ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([^\s?#]+)", re.IGNORECASE)
_ARXIV_VERSION_RE = re.compile(r"v\d+$")
_PDF_SUFFIX = ".pdf"
_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://www.doi.org/",
    "http://www.doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
)
_DOI_START = "10."
_ARXIV_DOI_PREFIX = "10.48550/arxiv."  # DataCite DOIs minted for every arXiv preprint


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

    def lookup(self, url: str) -> Paper | None:
        """Find the candidate a cited URL refers to.

        Tries the exact normalised URL, then the DOI, then the arXiv id, so a
        cited variant (`dx.doi.org/...`, `arxiv.org/pdf/<id>v7`) still matches.
        """
        hit = self._url_index.get(normalize_url(url).lower())
        if hit is not None:
            return hit
        doi = doi_from_url(url)
        if doi is not None and doi in self._doi_index:
            return self._doi_index[doi]
        arxiv_id = arxiv_id_from_url(url) or _arxiv_id_from_doi(doi)
        return self._arxiv_index.get(arxiv_id) if arxiv_id is not None else None

    @cached_property
    def _url_index(self) -> dict[str, Paper]:
        index: dict[str, Paper] = {}
        for p in self.papers:
            index.setdefault(normalize_url(p.url).lower(), p)
        return index

    @cached_property
    def _doi_index(self) -> dict[str, Paper]:
        index: dict[str, Paper] = {}
        for p in self.papers:
            for doi in (doi_from_url(p.doi), doi_from_url(p.url)):
                if doi is not None:
                    index.setdefault(doi, p)
        return index

    @cached_property
    def _arxiv_index(self) -> dict[str, Paper]:
        index: dict[str, Paper] = {}
        for p in self.papers:
            candidates = (
                strip_arxiv_version(p.arxiv_id),
                arxiv_id_from_url(p.url),
                _arxiv_id_from_doi(doi_from_url(p.doi) or doi_from_url(p.url)),
            )
            for arxiv_id in candidates:
                if arxiv_id is not None:
                    index.setdefault(arxiv_id, p)
        return index


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
    doi = doi.strip().rstrip("/").lower()
    return doi or None


def doi_from_url(raw: str | None) -> str | None:
    """`normalize_doi`, but only when the result actually is a DOI (`10.` prefix)."""
    doi = normalize_doi(raw)
    return doi if doi is not None and doi.startswith(_DOI_START) else None


def strip_arxiv_version(raw: str | None) -> str | None:
    if not raw:
        return None
    return _ARXIV_VERSION_RE.sub("", raw.strip()) or None


def arxiv_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _ARXIV_URL_RE.search(url)
    if not m:
        return None
    raw = m.group(1).rstrip("/")
    if raw.lower().endswith(_PDF_SUFFIX):
        raw = raw[: -len(_PDF_SUFFIX)]
    return strip_arxiv_version(raw)


def _arxiv_id_from_doi(doi: str | None) -> str | None:
    if doi is None or not doi.startswith(_ARXIV_DOI_PREFIX):
        return None
    return strip_arxiv_version(doi[len(_ARXIV_DOI_PREFIX) :])


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
