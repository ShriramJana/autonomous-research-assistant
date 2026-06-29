"""Client-side web search via Tavily (for non-Anthropic providers).

Anthropic uses its native server-side web_search; everything else routes a
client-side loop through here. Failures degrade to an empty result list so a
single bad search never kills a run.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_TAVILY_URL = "https://api.tavily.com/search"
_TIMEOUT = httpx.Timeout(20.0)


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


async def tavily_search(
    query: str, *, api_key: str | None, max_results: int = 5
) -> list[SearchResult]:
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _TAVILY_URL,
                json={"api_key": api_key, "query": query, "max_results": max_results},
            )
            resp.raise_for_status()
            data = resp.json()
    except (httpx.HTTPError, ValueError):
        return []
    rows = data.get("results", []) if isinstance(data, dict) else []
    return [
        SearchResult(
            title=str(r.get("title", "")),
            url=str(r.get("url", "")),
            content=str(r.get("content", "")),
        )
        for r in rows
        if isinstance(r, dict)
    ]


def format_search_results(results: list[SearchResult]) -> str:
    if not results:
        return "(no results)"
    return "\n\n".join(
        f"[{i + 1}] {r.title}\nURL: {r.url}\n{r.content}"
        for i, r in enumerate(results)
    )
