from __future__ import annotations

from ara.scholarly.models import (
    Paper,
    ScholarlyBundle,
    arxiv_id_from_url,
    authors_short,
    canonical_url,
    doi_from_url,
    normalize_doi,
    normalize_url,
    strip_arxiv_version,
    trim_abstract,
)


def _paper(**kw: object) -> Paper:
    base: dict[str, object] = {
        "catalog": "openalex",
        "title": "T",
        "url": "https://doi.org/10.1/x",
        "authors": ("A",),
        "year": 2020,
        "venue": "V",
        "doi": "10.1/x",
        "arxiv_id": None,
        "abstract": None,
        "citation_count": 3,
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
    assert (
        canonical_url(doi="10.1/x", arxiv_id="2310.06825", fallback="https://f")
        == "https://doi.org/10.1/x"
    )
    assert (
        canonical_url(doi=None, arxiv_id="2310.06825", fallback="https://f")
        == "https://arxiv.org/abs/2310.06825"
    )
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


def test_normalize_doi_handles_www_dx_http_and_trailing_slash() -> None:
    assert normalize_doi("https://www.doi.org/10.1/ABC") == "10.1/abc"
    assert normalize_doi("http://dx.doi.org/10.1/ABC/") == "10.1/abc"
    assert normalize_doi("http://www.doi.org/10.1/x") == "10.1/x"
    assert normalize_doi("https://dx.doi.org/10.1/x") == "10.1/x"


def test_doi_from_url_only_accepts_real_dois() -> None:
    assert doi_from_url("https://dx.doi.org/10.1/X") == "10.1/x"
    assert doi_from_url("https://example.com/paper") is None
    assert doi_from_url(None) is None


def test_arxiv_id_from_pdf_urls() -> None:
    assert arxiv_id_from_url("http://arxiv.org/pdf/1706.03762v7") == "1706.03762"
    assert arxiv_id_from_url("https://arxiv.org/pdf/1706.03762v7.pdf") == "1706.03762"
    assert arxiv_id_from_url("https://arxiv.org/pdf/1706.03762.PDF") == "1706.03762"
    assert arxiv_id_from_url("https://arxiv.org/abs/1706.03762/") == "1706.03762"
    assert arxiv_id_from_url("https://arxiv.org/pdf/hep-th/9901001v1") == "hep-th/9901001"


def _bundle(*papers: Paper) -> ScholarlyBundle:
    return ScholarlyBundle(terms=("t",), papers=papers, counts={"openalex": len(papers)})


def test_lookup_by_exact_url_doi_and_arxiv_id() -> None:
    doi_paper = _paper(
        title="Attention",
        url="https://doi.org/10.5555/3295222",
        doi="10.5555/3295222",
        arxiv_id="1706.03762",
    )
    arxiv_only = _paper(
        title="Mistral",
        url="https://arxiv.org/abs/2310.06825",
        doi=None,
        arxiv_id="2310.06825",
    )
    url_only = _paper(title="Web", url="https://pubmed.ncbi.nlm.nih.gov/1/", doi=None)
    bundle = _bundle(doi_paper, arxiv_only, url_only)

    assert bundle.lookup("https://DOI.org/10.5555/3295222/") is doi_paper  # exact, normalised
    assert bundle.lookup("http://dx.doi.org/10.5555/3295222") is doi_paper  # DOI
    assert bundle.lookup("doi:10.5555/3295222") is doi_paper
    assert bundle.lookup("http://arxiv.org/pdf/1706.03762v7") is doi_paper  # arXiv id
    assert bundle.lookup("https://arxiv.org/abs/2310.06825v2") is arxiv_only
    assert bundle.lookup("https://doi.org/10.48550/arXiv.2310.06825") is arxiv_only  # arXiv DOI
    assert bundle.lookup("https://pubmed.ncbi.nlm.nih.gov/1") is url_only
    assert bundle.lookup("https://example.com/other") is None
    assert bundle.lookup("https://doi.org/10.9999/unknown") is None


def test_lookup_matches_arxiv_url_against_paper_known_by_arxiv_doi() -> None:
    p = _paper(
        url="https://doi.org/10.48550/arxiv.2402.04177",
        doi="10.48550/arxiv.2402.04177",
        arxiv_id=None,
    )
    assert _bundle(p).lookup("https://arxiv.org/abs/2402.04177v1") is p
