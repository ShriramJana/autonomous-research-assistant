"""Researcher agent — runs web_search then submits a structured finding.

Supports two search paths based on the LLM provider's capabilities:
  1. Anthropic native: single API call with server-side web_search tool
     (dispatched when llm.supports_server_side_search is True)
  2. Client-side Tavily loop: multi-turn conversation using Tavily for search
     (dispatched when web_search_enabled and not llm.supports_server_side_search)
  3. Offline: no web search, single call with submit_finding only

Every path may also receive pre-fetched scholarly candidates (`scholarly_fetch`):
the papers are listed in the user message, a `scholarly_search(...)` progress
event is emitted, and cited papers are enriched from the registry (offline runs
keep only registry-backed sources).

Failure modes (all raise `ResearcherError`):
- response exceeds `input_token_budget`
- `submit_finding` not called (model responded with plain text only)
- `submit_finding` input fails Pydantic validation
- Tavily loop: model never calls submit_finding within max_iterations
- Tavily loop: model calls neither web_search nor submit_finding in a round
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ara.agents import EventEmitter, ResearcherError, extract_tool_use
from ara.llm.client import AnthropicClient, LLMClient, ToolSpec
from ara.llm.search import format_search_results, tavily_search
from ara.models.events import ResearcherProgress, ResearcherStarted
from ara.models.research import (
    MAX_SOURCE_TITLE_CHARS,
    KeyFact,
    Source,
    SubQuery,
    SubQueryFinding,
)
from ara.scholarly.models import Paper, ScholarlyBundle, authors_short, normalize_url

OnTavilySearch = Callable[[], Awaitable[None]]
ScholarlyFetch = Callable[[], Awaitable[ScholarlyBundle]]

SUBMIT_FINDING_TOOL_NAME = "submit_finding"
SCHOLARLY_TOOL_NAME = "scholarly_search"
_PROMPT_ABSTRACT_CHARS = 600
_MAX_AUTHORS_STORED = 25

RESEARCHER_SYSTEM_PROMPT = """\
You are the Researcher stage of an autonomous research assistant.

Your job: given ONE sub-query, use the web_search tool to gather authoritative \
sources, then submit a structured finding via the submit_finding tool.

Workflow:
1. Use web_search to find relevant, recent, reliable sources (up to 5 searches).
2. Read the search results carefully.
3. Synthesize 3-8 key facts that directly answer the sub-query.
4. For each key fact, list the exact source URLs that support it.
5. Call submit_finding with your summary, key_facts, and sources.

Critical constraints:
- Base all claims on actual search results — never fabricate.
- Every key_fact must cite at least one URL that appears in your sources list.
- Keep the summary to 2-4 sentences directly answering the sub-query.
- You MUST end by calling submit_finding. Plain-text-only replies are a failure.
"""

RESEARCHER_OFFLINE_SYSTEM_PROMPT = """\
You are the Researcher stage of an autonomous research assistant.

Web search is DISABLED for this run. Answer the sub-query using only your \
training knowledge and submit a structured finding via the submit_finding tool.

Workflow:
1. Consider the sub-query carefully using your existing knowledge.
2. Synthesize 3-8 key facts that directly answer the sub-query.
3. Do NOT list any sources — leave "sources" empty and give each key fact an \
   empty "source_urls" list. You cannot verify URLs without web access.
4. Call submit_finding with your summary and key_facts (leave sources empty).

Critical constraints:
- Acknowledge uncertainty in the summary when your knowledge may be stale.
- Never include URLs or sources of any kind; key facts are uncited in this mode.
- You MUST end by calling submit_finding. Plain-text-only replies are a failure.
"""

SCHOLARLY_ADDENDUM = """\
CANDIDATE SCHOLARLY SOURCES: the user message lists papers fetched from academic \
catalogs (OpenAlex, Semantic Scholar, arXiv, PubMed). They are real. When a key fact \
rests on one of them, cite it by its exact URL in both `sources` and `source_urls`. \
Prefer them for established findings; use web search (when available) for recency and \
non-academic angles.
"""

SCHOLARLY_OFFLINE_ADDENDUM = """\
EXCEPTION: the user message lists CANDIDATE SCHOLARLY SOURCES fetched from academic \
catalogs. They are real and verified. You MAY cite those exact URLs — and only those — \
in `sources` and `source_urls`. Any other URL will be discarded. List every candidate \
paper you cite in `sources` as well (url + title).
"""

WEB_SEARCH_CLIENT_TOOL_NAME = "web_search"

WEB_SEARCH_CLIENT_TOOL: ToolSpec = {
    "name": WEB_SEARCH_CLIENT_TOOL_NAME,
    "description": "Search the web. Returns titled results with URLs and snippets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."}
        },
        "required": ["query"],
    },
}

RESEARCHER_TAVILY_SYSTEM_PROMPT = """\
You are the Researcher stage of an autonomous research assistant.

Your job: given ONE sub-query, call the web_search tool to gather authoritative \
sources, then submit a structured finding via the submit_finding tool.

Workflow:
1. Call web_search with focused queries to find relevant, recent, reliable sources.
2. Read the returned results (each has a title, URL, and snippet).
3. Synthesize 3-8 key facts that directly answer the sub-query.
4. For each key fact, cite the exact source URLs (from the results) that support it.
5. Call submit_finding with your summary, key_facts, and sources.

Critical constraints:
- Base all claims on actual search results — never fabricate.
- Every key_fact must cite at least one URL that appears in your sources list.
- Keep the summary to 2-4 sentences directly answering the sub-query.
- You MUST end by calling submit_finding. Plain-text-only replies are a failure.
"""

SUBMIT_FINDING_TOOL: ToolSpec = {
    "name": SUBMIT_FINDING_TOOL_NAME,
    "description": "Submit the structured finding for this sub-query.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "A 2-4 sentence summary answering the sub-query.",
            },
            "key_facts": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "string"},
                        "source_urls": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 1,
                            "description": (
                                "URLs from the sources list below that support this fact."
                            ),
                        },
                    },
                    "required": ["statement", "source_urls"],
                },
            },
            "sources": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                    },
                    "required": ["url", "title"],
                },
            },
        },
        "required": ["summary", "key_facts", "sources"],
    },
}


def _empty_bundle() -> ScholarlyBundle:
    return ScholarlyBundle(terms=(), papers=(), counts={})


async def _load_bundle(fetch: ScholarlyFetch) -> ScholarlyBundle:
    try:
        return await fetch()
    except Exception:  # the fetch is best-effort; a broken catalog never fails the run
        return _empty_bundle()


def _paper_meta(paper: Paper) -> str:
    byline = " ".join(
        p for p in (authors_short(paper.authors), f"({paper.year})" if paper.year else "") if p
    )
    parts = [
        byline,
        paper.venue or "",
        f"{paper.citation_count} citations" if paper.citation_count is not None else "",
    ]
    return " · ".join(p for p in parts if p)


def _scholarly_block(bundle: ScholarlyBundle) -> str:
    lines = ["CANDIDATE SCHOLARLY SOURCES (fetched from academic catalogs; cite by URL):"]
    for i, paper in enumerate(bundle.papers, start=1):
        lines.append(f"[S{i}] {paper.title}")
        meta = _paper_meta(paper)
        if meta:
            lines.append(f"     {meta}")
        lines.append(f"     URL: {paper.url}")
        if paper.abstract:
            lines.append(f"     {paper.abstract[:_PROMPT_ABSTRACT_CHARS]}")
    return "\n".join(lines)


def _user_message(question: str, bundle: ScholarlyBundle | None) -> str:
    if bundle is None or not bundle.papers:
        return question
    return f"{question}\n\n{_scholarly_block(bundle)}"


def _system_prompt(base: str, bundle: ScholarlyBundle | None, *, offline: bool) -> str:
    if bundle is None or not bundle.papers:
        return base
    return base + "\n" + (SCHOLARLY_OFFLINE_ADDENDUM if offline else SCHOLARLY_ADDENDUM)


def _registry(bundle: ScholarlyBundle | None) -> ScholarlyBundle | None:
    """The bundle when it has papers to match citations against, else None."""
    return bundle if bundle is not None and bundle.papers else None


async def research_sub_query(
    *,
    sub_query: SubQuery,
    llm: LLMClient,
    model: str,
    emit: EventEmitter,
    max_iterations: int = 5,
    input_token_budget: int = 100_000,
    max_tokens: int = 8192,
    web_search_enabled: bool = True,
    tavily_api_key: str | None = None,
    on_tavily_search: OnTavilySearch | None = None,
    scholarly_fetch: ScholarlyFetch | None = None,
) -> SubQueryFinding:
    """Research one sub-query end-to-end.

    Dispatches to one of three paths based on capability flags:
    1. client-side Tavily loop  — web_search_enabled and not llm.supports_server_side_search
    2. Anthropic server-side    — web_search_enabled and llm.supports_server_side_search
    3. offline single-call      — not web_search_enabled (works for both providers)

    Dispatch is on the `llm.supports_server_side_search` capability flag only —
    never on isinstance checks.

    Emits `ResearcherStarted` before any API call and one `ResearcherProgress`
    per web_search call. When `scholarly_fetch` is given it is awaited after
    `ResearcherStarted` and one `scholarly_search(...)` progress event follows.
    Returns a `SubQueryFinding` on success; raises
    `ResearcherError` on failure so the orchestrator can build a degraded
    finding + `ErrorEvent`.
    """
    await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))

    bundle: ScholarlyBundle | None = None
    if scholarly_fetch is not None:
        bundle = await _load_bundle(scholarly_fetch)
        await emit(
            ResearcherProgress(
                sub_query_id=sub_query.id,
                tool_call=(
                    f"{SCHOLARLY_TOOL_NAME}({list(bundle.terms)!r}) → {len(bundle.papers)} papers"
                ),
            )
        )
    registry = _registry(bundle)

    if web_search_enabled and not llm.supports_server_side_search:
        return await _research_with_tavily(
            sub_query=sub_query,
            llm=llm,
            model=model,
            emit=emit,
            max_iterations=max_iterations,
            input_token_budget=input_token_budget,
            max_tokens=max_tokens,
            tavily_api_key=tavily_api_key,
            on_tavily_search=on_tavily_search,
            bundle=bundle,
        )

    tools: list[ToolSpec]
    system: str
    if web_search_enabled:
        tools = [
            AnthropicClient.web_search_tool_spec(max_uses=max_iterations),
            SUBMIT_FINDING_TOOL,
        ]
        system = _system_prompt(RESEARCHER_SYSTEM_PROMPT, bundle, offline=False)
    else:
        tools = [SUBMIT_FINDING_TOOL]
        system = _system_prompt(RESEARCHER_OFFLINE_SYSTEM_PROMPT, bundle, offline=True)

    result = await llm.complete_with_tools(
        model=model,
        messages=[{"role": "user", "content": _user_message(sub_query.question, bundle)}],
        tools=tools,
        system=system,
        max_tokens=max_tokens,
    )

    if result.input_tokens > input_token_budget:
        raise ResearcherError(
            f"Input token budget exceeded: {result.input_tokens} > {input_token_budget}"
        )

    for tu in result.server_tool_uses:
        query = tu.input.get("query", "") if isinstance(tu.input, dict) else ""
        await emit(
            ResearcherProgress(
                sub_query_id=sub_query.id,
                tool_call=f"{tu.name}({query!r})",
            )
        )

    finding_input = extract_tool_use(result, SUBMIT_FINDING_TOOL_NAME)
    if finding_input is None:
        raise ResearcherError(
            f"Researcher did not call {SUBMIT_FINDING_TOOL_NAME!r} "
            f"(stop_reason={result.stop_reason!r})"
        )

    try:
        finding = _build_finding(sub_query.id, finding_input, registry)
    except (ValidationError, KeyError, TypeError) as exc:
        raise ResearcherError(f"Researcher output failed validation: {exc}") from exc
    if not web_search_enabled:
        finding = _restrict_to_registry(finding, registry)
    return finding


async def _research_with_tavily(
    *,
    sub_query: SubQuery,
    llm: LLMClient,
    model: str,
    emit: EventEmitter,
    max_iterations: int,
    input_token_budget: int,
    max_tokens: int,
    tavily_api_key: str | None,
    on_tavily_search: OnTavilySearch | None = None,
    bundle: ScholarlyBundle | None = None,
) -> SubQueryFinding:
    """Client-side search loop for providers without server-side web search.

    Runs up to `max_iterations + 1` model calls. Each round the model may:
    - call web_search → we execute each search via Tavily and append results
    - call submit_finding → we validate and return the finding
    - call neither → ResearcherError (stuck)

    After max_iterations + 1 calls without submit_finding: ResearcherError.
    """
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": _user_message(sub_query.question, bundle)}
    ]
    system = _system_prompt(RESEARCHER_TAVILY_SYSTEM_PROMPT, bundle, offline=False)
    registry = _registry(bundle)
    tools = [WEB_SEARCH_CLIENT_TOOL, SUBMIT_FINDING_TOOL]
    total_input = 0

    for _ in range(max_iterations + 1):
        result = await llm.complete_with_tools(
            model=model,
            messages=messages,
            tools=tools,
            system=system,
            max_tokens=max_tokens,
        )
        total_input += result.input_tokens
        if total_input > input_token_budget:
            raise ResearcherError(
                f"Input token budget exceeded: {total_input} > {input_token_budget}"
            )

        finding_input = extract_tool_use(result, SUBMIT_FINDING_TOOL_NAME)
        if finding_input is not None:
            try:
                return _build_finding(sub_query.id, finding_input, registry)
            except (ValidationError, KeyError, TypeError) as exc:
                raise ResearcherError(f"Researcher output failed validation: {exc}") from exc

        searches = [tu for tu in result.tool_uses if tu.name == WEB_SEARCH_CLIENT_TOOL_NAME]
        if not searches:
            raise ResearcherError(
                f"Researcher called neither {SUBMIT_FINDING_TOOL_NAME!r} nor "
                f"{WEB_SEARCH_CLIENT_TOOL_NAME!r} (stop_reason={result.stop_reason!r})"
            )

        messages.append(
            {
                "role": "assistant",
                "content": result.text,
                "tool_calls": [
                    {"id": tu.id, "name": tu.name, "input": tu.input} for tu in searches
                ],
            }
        )
        for tu in searches:
            query = tu.input.get("query", "") if isinstance(tu.input, dict) else ""
            await emit(
                ResearcherProgress(
                    sub_query_id=sub_query.id,
                    tool_call=f"{WEB_SEARCH_CLIENT_TOOL_NAME}({query!r})",
                )
            )
            if on_tavily_search is not None:
                await on_tavily_search()
            rows = await tavily_search(query, api_key=tavily_api_key)
            messages.append(
                {"role": "tool", "tool_call_id": tu.id, "content": format_search_results(rows)}
            )

    raise ResearcherError(
        f"Researcher did not call {SUBMIT_FINDING_TOOL_NAME!r} within "
        f"{max_iterations} search iterations"
    )


def _lookup(registry: ScholarlyBundle | None, url: str) -> Paper | None:
    """Exact normalised URL, then DOI, then arXiv id (see `ScholarlyBundle.lookup`)."""
    return registry.lookup(url) if registry is not None else None


def _build_finding(
    sub_query_id: UUID, data: dict[str, Any], registry: ScholarlyBundle | None = None
) -> SubQueryFinding:
    """Translate the raw submit_finding input into a `SubQueryFinding`.

    The model cites by URL; we assign stable UUIDs to each Source and rewrite
    each KeyFact's `source_urls` into `citation_ids`. A cited URL that matches
    a pre-fetched paper is enriched from the registry (kind="scholarly",
    canonical URL, catalog title and metadata) — the model never supplies
    metadata. Unknown URLs stay `kind="web"`. Dedup is by normalised URL.

    A key fact may cite a candidate paper the model left out of `sources`
    (small models do this offline); a registry hit is verified data, so the
    Source is created from the paper. Unknown URLs cited only in key facts
    resolve to nothing.
    """
    summary = data["summary"]
    raw_sources = data.get("sources") or []
    raw_facts = data.get("key_facts") or []

    sources: list[Source] = []
    url_to_id: dict[str, UUID] = {}
    for raw in raw_sources:
        cited = str(raw["url"])
        paper = _lookup(registry, cited)
        keys = {normalize_url(cited)}
        if paper is not None:
            keys.add(normalize_url(paper.url))
        existing = next((url_to_id[k] for k in keys if k in url_to_id), None)
        if existing is not None:
            for k in keys:
                url_to_id.setdefault(k, existing)
            continue
        src = _source_from(paper, cited, str(raw["title"]))
        sources.append(src)
        for k in keys:
            url_to_id[k] = src.id

    key_facts: list[KeyFact] = []
    for raw in raw_facts:
        urls = raw.get("source_urls") or []
        citation_ids: list[UUID] = []
        for u in urls:
            cid = _resolve_citation(str(u), registry, sources, url_to_id)
            if cid is not None and cid not in citation_ids:
                citation_ids.append(cid)
        key_facts.append(KeyFact(statement=raw["statement"], citation_ids=citation_ids))

    return SubQueryFinding(
        sub_query_id=sub_query_id, summary=summary, key_facts=key_facts, sources=sources
    )


def _resolve_citation(
    cited: str,
    registry: ScholarlyBundle | None,
    sources: list[Source],
    url_to_id: dict[str, UUID],
) -> UUID | None:
    """Map one key-fact URL to a Source id, creating the Source on a registry hit."""
    key = normalize_url(cited)
    cid = url_to_id.get(key)
    if cid is not None:
        return cid
    paper = _lookup(registry, cited)
    if paper is None:
        return None
    canonical = normalize_url(paper.url)
    cid = url_to_id.get(canonical)
    if cid is None:
        src = _source_from(paper, cited, paper.title)
        sources.append(src)
        cid = src.id
        url_to_id[canonical] = cid
    url_to_id[key] = cid
    return cid


def _clip_title(title: str) -> str:
    return " ".join(title.split())[:MAX_SOURCE_TITLE_CHARS]


def _source_from(paper: Paper | None, cited_url: str, cited_title: str) -> Source:
    if paper is None:
        return Source.model_validate({"url": cited_url, "title": cited_title})
    return Source.model_validate(
        {
            "url": paper.url,
            "title": _clip_title(paper.title) or _clip_title(paper.url),
            "kind": "scholarly",
            "authors": list(paper.authors[:_MAX_AUTHORS_STORED]),
            "year": paper.year,
            "venue": paper.venue,
            "doi": paper.doi,
            "citation_count": paper.citation_count,
        }
    )


def _restrict_to_registry(
    finding: SubQueryFinding, registry: ScholarlyBundle | None
) -> SubQueryFinding:
    """Offline runs keep only sources backed by fetched papers (small models invent URLs)."""
    keep = (
        {s.id for s in finding.sources if s.kind == "scholarly"} if registry is not None else set()
    )
    return finding.model_copy(
        update={
            "sources": [s for s in finding.sources if s.id in keep],
            "key_facts": [
                f.model_copy(update={"citation_ids": [c for c in f.citation_ids if c in keep]})
                for f in finding.key_facts
            ],
        }
    )
