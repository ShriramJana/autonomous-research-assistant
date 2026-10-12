from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from ara.config import Settings
from ara.scholarly import catalogs as catalogs_mod
from ara.scholarly import service
from ara.scholarly.catalogs import enabled_catalogs
from ara.scholarly.models import Paper, ScholarlyBundle
from ara.scholarly.service import fetch_papers, merge_papers, rank_papers


def _paper(catalog: str = "openalex", **kw: object) -> Paper:
    base: dict[str, object] = {
        "catalog": catalog,
        "title": "Title",
        "url": "https://x/1",
        "authors": ("A",),
        "year": 2020,
        "venue": None,
        "doi": None,
        "arxiv_id": None,
        "abstract": None,
        "citation_count": None,
    }
    base.update(kw)
    return Paper(**base)  # type: ignore[arg-type]


_SCHOLARLY_KEYS = ("openalex_mailto", "semantic_scholar_api_key", "ncbi_api_key")


def _settings(**kw: str) -> Settings:
    """Settings with every scholarly key blank unless overridden.

    An exported `SEMANTIC_SCHOLAR_API_KEY` would otherwise enable a catalog the
    test did not fake and turn it into a real network call.
    """
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    for k, v in {**dict.fromkeys(_SCHOLARLY_KEYS, ""), **kw}.items():
        setattr(s, k, v)
    return s


def _fake(papers: list[Paper]) -> Any:
    async def search(
        terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
    ) -> list[Paper]:
        return papers

    return search


def test_enabled_catalogs_gates_semantic_scholar_on_key() -> None:
    assert enabled_catalogs(_settings()) == ["openalex", "arxiv", "pubmed"]
    assert enabled_catalogs(_settings(semantic_scholar_api_key="k")) == [
        "openalex",
        "semantic_scholar",
        "arxiv",
        "pubmed",
    ]


def test_merge_dedupes_by_doi_then_arxiv_then_title_and_backfills() -> None:
    a = _paper(
        "openalex", doi="10.1/x", url="https://doi.org/10.1/x", abstract=None, citation_count=10
    )
    b = _paper("pubmed", doi="10.1/x", url="https://doi.org/10.1/x", abstract="Abstract", venue="J")
    c = _paper(
        "arxiv", title="Title", url="https://arxiv.org/abs/1", arxiv_id="1"
    )  # same title as a
    d = _paper("arxiv", title="Other paper!", url="https://arxiv.org/abs/2", arxiv_id="2")
    merged = merge_papers([a, b, c, d])
    assert [p.url for p in merged] == ["https://doi.org/10.1/x", "https://arxiv.org/abs/2"]
    first = merged[0]
    assert (first.abstract, first.venue, first.citation_count, first.arxiv_id) == (
        "Abstract",
        "J",
        10,
        "1",
    )


def test_merge_joins_arxiv_and_openalex_records_by_arxiv_id() -> None:
    arxiv = _paper(
        "arxiv", title="Mistral 7B", url="https://arxiv.org/abs/2310.06825", arxiv_id="2310.06825"
    )
    openalex = _paper(
        "openalex",
        title="Mistral 7B (preprint)",
        doi="10.48550/arxiv.2310.06825",
        url="https://doi.org/10.48550/arxiv.2310.06825",
        arxiv_id="2310.06825",
        citation_count=500,
    )
    [merged] = merge_papers([arxiv, openalex])
    assert merged.doi == "10.48550/arxiv.2310.06825"
    assert (
        merged.url == "https://doi.org/10.48550/arxiv.2310.06825"
    )  # canonical recomputed after fill
    assert merged.citation_count == 500


def test_merge_ignores_empty_normalized_titles() -> None:
    a = _paper("openalex", title="???", url="https://x/1")
    b = _paper("pubmed", title="!!!", url="https://x/2")
    assert len(merge_papers([a, b])) == 2


def test_rank_by_citations_then_year_then_catalog_order() -> None:
    low = _paper("openalex", url="https://x/low", citation_count=1, year=2024)
    high = _paper("pubmed", url="https://x/high", citation_count=50, year=2001)
    none_new = _paper("arxiv", url="https://x/new", citation_count=None, year=2025)
    none_old = _paper("openalex", url="https://x/old", citation_count=None, year=2010)
    assert [p.url for p in rank_papers([none_old, low, none_new, high])] == [
        "https://x/high",
        "https://x/low",
        "https://x/new",
        "https://x/old",
    ]


async def test_fetch_papers_gathers_enabled_catalogs_and_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def recording(catalog: str, papers: list[Paper]) -> Any:
        async def search(
            terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
        ) -> list[Paper]:
            calls.append(catalog)
            assert terms == ["a", "b"] and limit == 2
            return papers

        return search

    monkeypatch.setitem(
        catalogs_mod.CATALOGS,
        "openalex",
        recording(
            "openalex",
            [
                _paper("openalex", url="https://x/1", citation_count=5),
                _paper("openalex", url="https://x/2", title="Two", citation_count=9),
            ],
        ),
    )
    monkeypatch.setitem(
        catalogs_mod.CATALOGS,
        "arxiv",
        recording(
            "arxiv",
            [
                _paper("arxiv", url="https://x/3", title="Three", citation_count=7),
            ],
        ),
    )
    monkeypatch.setitem(catalogs_mod.CATALOGS, "pubmed", recording("pubmed", []))
    monkeypatch.setitem(
        catalogs_mod.CATALOGS, "semantic_scholar", recording("semantic_scholar", [])
    )

    bundle = await fetch_papers([" a ", "b", ""], settings=_settings(), limit=2)
    assert isinstance(bundle, ScholarlyBundle)
    assert sorted(calls) == ["arxiv", "openalex", "pubmed"]  # no key → no Semantic Scholar
    assert bundle.terms == ("a", "b")
    assert bundle.counts == {"openalex": 2, "arxiv": 1, "pubmed": 0}
    assert [p.url for p in bundle.papers] == ["https://x/2", "https://x/3"]  # ranked, cut to limit


async def test_fetch_papers_with_no_terms_is_empty_without_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*a: Any, **k: Any) -> list[Paper]:
        raise AssertionError("must not be called")

    for c in catalogs_mod.CATALOGS:
        monkeypatch.setitem(catalogs_mod.CATALOGS, c, boom)
    bundle = await fetch_papers(["", "  "], settings=_settings())
    assert bundle == ScholarlyBundle(terms=(), papers=(), counts={})


async def test_fetch_papers_treats_catalog_exception_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(*a: Any, **k: Any) -> list[Paper]:
        raise RuntimeError("catalog bug")

    monkeypatch.setitem(catalogs_mod.CATALOGS, "openalex", boom)
    monkeypatch.setitem(catalogs_mod.CATALOGS, "arxiv", _fake([_paper("arxiv", url="https://x/a")]))
    monkeypatch.setitem(catalogs_mod.CATALOGS, "pubmed", _fake([]))
    bundle = await fetch_papers(["q"], settings=_settings())
    assert bundle.counts == {"openalex": 0, "arxiv": 1, "pubmed": 0}
    assert [p.url for p in bundle.papers] == ["https://x/a"]


async def test_fetch_papers_returns_partial_results_when_a_catalog_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang(*a: Any, **k: Any) -> list[Paper]:
        await asyncio.sleep(60)
        return []

    monkeypatch.setattr(service, "_BUNDLE_TIMEOUT_S", 0.05)
    monkeypatch.setitem(catalogs_mod.CATALOGS, "arxiv", hang)
    monkeypatch.setitem(
        catalogs_mod.CATALOGS, "openalex", _fake([_paper("openalex", url="https://x/fast")])
    )
    monkeypatch.setitem(catalogs_mod.CATALOGS, "pubmed", _fake([]))
    bundle = await asyncio.wait_for(fetch_papers(["q"], settings=_settings()), timeout=2.0)
    assert [p.url for p in bundle.papers] == ["https://x/fast"]
    assert bundle.counts["arxiv"] == 0


async def test_fetch_papers_uses_injected_http_client(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.AsyncClient] = []

    async def search(
        terms: list[str], *, limit: int, http: httpx.AsyncClient, settings: Settings
    ) -> list[Paper]:
        seen.append(http)
        return []

    for c in catalogs_mod.CATALOGS:
        monkeypatch.setitem(catalogs_mod.CATALOGS, c, search)
    async with httpx.AsyncClient() as client:
        await fetch_papers(["q"], settings=_settings(), http=client)
    assert seen and all(h is client for h in seen)


def test_settings_helper_ignores_ambient_scholarly_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "ambient")
    monkeypatch.setenv("NCBI_API_KEY", "ambient")
    s = _settings()
    assert (s.semantic_scholar_api_key, s.ncbi_api_key, s.openalex_mailto) == ("", "", "")
    assert "semantic_scholar" not in enabled_catalogs(s)


async def test_cancelling_fetch_papers_cancels_catalog_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def hang(*a: Any, **k: Any) -> list[Paper]:
        started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return []

    monkeypatch.setitem(catalogs_mod.CATALOGS, "arxiv", hang)
    monkeypatch.setitem(catalogs_mod.CATALOGS, "openalex", _fake([]))
    monkeypatch.setitem(catalogs_mod.CATALOGS, "pubmed", _fake([]))
    task = asyncio.create_task(fetch_papers(["q"], settings=_settings()))
    await asyncio.wait_for(started.wait(), timeout=2.0)
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()  # the catalog task was cancelled and awaited, not orphaned
