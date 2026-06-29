"""Researcher agent — runs web_search then submits a structured finding.

Supports two search paths based on the LLM provider's capabilities:
  1. Anthropic native: single API call with server-side web_search tool
     (dispatched when llm.supports_server_side_search is True)
  2. Client-side Tavily loop: multi-turn conversation using Tavily for search
     (dispatched when web_search_enabled and not llm.supports_server_side_search)
  3. Offline: no web search, single call with submit_finding only

Failure modes (all raise `ResearcherError`):
- response exceeds `input_token_budget`
- `submit_finding` not called (model responded with plain text only)
- `submit_finding` input fails Pydantic validation
- Tavily loop: model never calls submit_finding within max_iterations
- Tavily loop: model calls neither web_search nor submit_finding in a round
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ara.agents import EventEmitter, ResearcherError, extract_tool_use
from ara.llm.client import AnthropicClient, LLMClient, ToolSpec
from ara.llm.search import format_search_results, tavily_search
from ara.models.events import ResearcherProgress, ResearcherStarted
from ara.models.research import KeyFact, Source, SubQuery, SubQueryFinding

SUBMIT_FINDING_TOOL_NAME = "submit_finding"

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
3. Cite canonical sources you are confident exist (e.g. the homepage of a \
   well-known site, a canonical paper or spec). Do NOT invent specific URLs, \
   blog posts, or papers that might not exist.
4. Call submit_finding with your summary, key_facts, and sources.

Critical constraints:
- Acknowledge uncertainty in the summary when your knowledge may be stale.
- Every key_fact must cite at least one URL from your sources list.
- If you cannot think of a confident canonical source, use the root homepage \
  of an authoritative publisher (arxiv.org, ietf.org, who.int, etc.) rather \
  than guessing a deep link.
- You MUST end by calling submit_finding. Plain-text-only replies are a failure.
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
) -> SubQueryFinding:
    """Research one sub-query end-to-end.

    Dispatches to one of three paths based on capability flags:
    1. client-side Tavily loop  — web_search_enabled and not llm.supports_server_side_search
    2. Anthropic server-side    — web_search_enabled and llm.supports_server_side_search
    3. offline single-call      — not web_search_enabled (works for both providers)

    Dispatch is on the `llm.supports_server_side_search` capability flag only —
    never on isinstance checks.

    Emits `ResearcherStarted` before any API call and one `ResearcherProgress`
    per web_search call. Returns a `SubQueryFinding` on success; raises
    `ResearcherError` on failure so the orchestrator can build a degraded
    finding + `ErrorEvent`.
    """
    await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))

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
        )

    tools: list[ToolSpec]
    system: str
    if web_search_enabled:
        tools = [
            AnthropicClient.web_search_tool_spec(max_uses=max_iterations),
            SUBMIT_FINDING_TOOL,
        ]
        system = RESEARCHER_SYSTEM_PROMPT
    else:
        tools = [SUBMIT_FINDING_TOOL]
        system = RESEARCHER_OFFLINE_SYSTEM_PROMPT

    result = await llm.complete_with_tools(
        model=model,
        messages=[{"role": "user", "content": sub_query.question}],
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
        return _build_finding(sub_query.id, finding_input)
    except (ValidationError, KeyError, TypeError) as exc:
        raise ResearcherError(f"Researcher output failed validation: {exc}") from exc


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
) -> SubQueryFinding:
    """Client-side search loop for providers without server-side web search.

    Runs up to `max_iterations + 1` model calls. Each round the model may:
    - call web_search → we execute each search via Tavily and append results
    - call submit_finding → we validate and return the finding
    - call neither → ResearcherError (stuck)

    After max_iterations + 1 calls without submit_finding: ResearcherError.
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": sub_query.question}]
    tools = [WEB_SEARCH_CLIENT_TOOL, SUBMIT_FINDING_TOOL]
    total_input = 0

    for _ in range(max_iterations + 1):
        result = await llm.complete_with_tools(
            model=model,
            messages=messages,
            tools=tools,
            system=RESEARCHER_TAVILY_SYSTEM_PROMPT,
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
                return _build_finding(sub_query.id, finding_input)
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
            rows = await tavily_search(query, api_key=tavily_api_key)
            messages.append(
                {"role": "tool", "tool_call_id": tu.id, "content": format_search_results(rows)}
            )

    raise ResearcherError(
        f"Researcher did not call {SUBMIT_FINDING_TOOL_NAME!r} within "
        f"{max_iterations} search iterations"
    )


def _build_finding(sub_query_id: UUID, data: dict[str, Any]) -> SubQueryFinding:
    """Translate the raw submit_finding input into a `SubQueryFinding`.

    The model cites by URL; we assign stable UUIDs to each Source and
    rewrite each KeyFact's `source_urls` into `citation_ids: list[UUID]`.
    URL-level dedup happens here (same URL, different titles → keep first).
    Key facts that reference unknown URLs get an empty citation list
    rather than failing the whole finding.
    """
    summary = data["summary"]
    raw_sources = data.get("sources", [])
    raw_facts = data.get("key_facts", [])

    sources: list[Source] = []
    url_to_id: dict[str, UUID] = {}
    for raw in raw_sources:
        url = raw["url"]
        title = raw["title"]
        if url in url_to_id:
            continue
        src = Source.model_validate({"url": url, "title": title})
        sources.append(src)
        url_to_id[url] = src.id

    key_facts: list[KeyFact] = []
    for raw in raw_facts:
        urls = raw.get("source_urls", [])
        citation_ids = [url_to_id[u] for u in urls if u in url_to_id]
        key_facts.append(KeyFact(statement=raw["statement"], citation_ids=citation_ids))

    return SubQueryFinding(
        sub_query_id=sub_query_id,
        summary=summary,
        key_facts=key_facts,
        sources=sources,
    )
