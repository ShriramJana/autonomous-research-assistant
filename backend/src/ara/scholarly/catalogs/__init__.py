"""One module per scholarly catalog. Each exposes `search(terms, *, limit, http, settings)`.

`CATALOGS` is a plain dict so tests can swap entries with `monkeypatch.setitem`.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Protocol

import httpx

from ara.config import Settings
from ara.scholarly.catalogs import arxiv, openalex, pubmed, semantic_scholar
from ara.scholarly.models import CATALOG_ORDER, CatalogId, Paper


class CatalogSearch(Protocol):
    def __call__(
        self, terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
    ) -> Awaitable[list[Paper]]: ...


CATALOGS: dict[CatalogId, CatalogSearch] = {
    "openalex": openalex.search,
    "semantic_scholar": semantic_scholar.search,
    "arxiv": arxiv.search,
    "pubmed": pubmed.search,
}


def enabled_catalogs(settings: Settings) -> list[CatalogId]:
    """All catalogs in canonical order, minus Semantic Scholar when it has no key."""
    return [
        c for c in CATALOG_ORDER
        if c != "semantic_scholar" or bool(settings.semantic_scholar_api_key)
    ]


__all__ = ["CATALOGS", "CatalogSearch", "enabled_catalogs"]
