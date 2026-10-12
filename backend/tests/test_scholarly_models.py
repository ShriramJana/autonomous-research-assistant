from __future__ import annotations

from ara.scholarly.models import (
    Paper,
    ScholarlyBundle,
    arxiv_id_from_url,
    authors_short,
    canonical_url,
    normalize_doi,
    normalize_url,
    strip_arxiv_version,
    trim_abstract,
)


def _paper(**kw: object) -> Paper:
    base: dict[str, object] = {
        "catalog": "openalex", "title": "T", "url": "https://doi.org/10.1/x",
        "authors": ("A",), "year": 2020, "venue": "V", "doi": "10.1/x",
        "arxiv_id": None, "abstract": None, "citation_count": 3,
    }
    base.update(kw)
    return Paper(**base)  # type: ignore[arg-type]


def test_normalize_doi_strips_prefixes_and_lowercases() -> None:
    assert normalize_doi("https://doi.org/10.1109/TVCG.2023.3327163") == "10.1109/tvcg.2023.3327163"
    assert normalize_doi("doi:10.1/ABC") == "10.1/abc"
    assert normalize_doi(" 10.1/x ") == "10.1/x"
    assert normalize_doi("") is None and normalize_doi(None) is None


def test_arxiv_id_helpers() -> None:
    assert arxiv_id_from_url("http://arxiv.org/abs/2310.06825v2") == "2310.06825"
    assert arxiv_id_from_url("https://arxiv.org/abs/hep-th/9901001") == "hep-th/9901001"
    assert arxiv_id_from_url("https://example.com/paper") is None
    assert arxiv_id_from_url(None) is None
    assert strip_arxiv_version("2310.06825v3") == "2310.06825"
    assert strip_arxiv_version(None) is None


def test_canonical_url_precedence() -> None:
    assert canonical_url(doi="10.1/x", arxiv_id="2310.06825", fallback="https://f") == "https://doi.org/10.1/x"
    assert canonical_url(doi=None, arxiv_id="2310.06825", fallback="https://f") == "https://arxiv.org/abs/2310.06825"
    assert canonical_url(doi=None, arxiv_id=None, fallback="https://f") == "https://f"


def test_normalize_url_and_bundle_registry() -> None:
    assert normalize_url(" https://doi.org/10.1/X/ ") == "https://doi.org/10.1/X"
    p = _paper()
    bundle = ScholarlyBundle(terms=("t",), papers=(p,), counts={"openalex": 1})
    assert bundle.by_url() == {"https://doi.org/10.1/x": p}


def test_trim_abstract_and_authors_short() -> None:
    assert trim_abstract(None) is None
    assert trim_abstract("   ") is None
    assert trim_abstract("a" * 1300) == "a" * 1200
    assert authors_short([]) == ""
    assert authors_short(["A", "B"]) == "A, B"
    assert authors_short(["A", "B", "C", "D"]) == "A, B, C et al."
