"""Researcher agent — runs web_search then submits a structured finding.

Single API call per sub-query. Anthropic's server-side web_search tool
(`web_search_20250305`) executes up to `max_iterations` searches server-side
within the one request; the model then finishes by calling our client-side
`submit_finding` tool with the structured output. We extract and validate.

Failure modes (all raise `ResearcherError`):
- response exceeds `input_token_budget`
- `submit_finding` not called (model responded with plain text only)
- `submit_finding` input fails Pydantic validation
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from ara.agents import EventEmitter, ResearcherError, extract_tool_use
from ara.llm.client import LLMClient, ToolSpec
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
) -> SubQueryFinding:
    """Research one sub-query end-to-end.

    Emits `ResearcherStarted` before the API call and one
    `ResearcherProgress` per server-side web_search. Returns a
    `SubQueryFinding` on success; raises `ResearcherError` on failure so
    the orchestrator can build a degraded finding + `ErrorEvent`.
    """
    await emit(ResearcherStarted(sub_query_id=sub_query.id, question=sub_query.question))

    response = await llm.complete_with_tools(
        model=model,
        messages=[{"role": "user", "content": sub_query.question}],
        tools=[
            LLMClient.web_search_tool_spec(max_uses=max_iterations),
            SUBMIT_FINDING_TOOL,
        ],
        system=RESEARCHER_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )

    if response.usage.input_tokens > input_token_budget:
        raise ResearcherError(
            f"Input token budget exceeded: "
            f"{response.usage.input_tokens} > {input_token_budget}"
        )

    for block in response.content:
        if getattr(block, "type", None) == "server_tool_use":
            tool_name = getattr(block, "name", "")
            tool_input = getattr(block, "input", None)
            query = tool_input.get("query", "") if isinstance(tool_input, dict) else ""
            await emit(
                ResearcherProgress(
                    sub_query_id=sub_query.id,
                    tool_call=f"{tool_name}({query!r})",
                )
            )

    finding_input = extract_tool_use(response, SUBMIT_FINDING_TOOL_NAME)
    if finding_input is None:
        raise ResearcherError(
            f"Researcher did not call {SUBMIT_FINDING_TOOL_NAME!r} "
            f"(stop_reason={response.stop_reason!r})"
        )

    try:
        return _build_finding(sub_query.id, finding_input)
    except (ValidationError, KeyError, TypeError) as exc:
        raise ResearcherError(f"Researcher output failed validation: {exc}") from exc


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
