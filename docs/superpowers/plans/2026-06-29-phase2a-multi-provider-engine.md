# Phase 2a — Multi-Provider Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the planner → researcher → synthesizer pipeline run on a non-Anthropic, OpenAI-compatible provider (with Tavily client-side search) in addition to the native Anthropic path, chosen per-request, without adopting a generic abstraction layer.

**Architecture:** Decouple agents from Anthropic SDK types by normalizing the completion *return value* into a `CompletionResult`. Introduce an `LLMClient` Protocol satisfied by two hand-written native clients — `AnthropicClient` (rename of today's class, native server-side web search) and `OpenAICompatClient` (official `openai` SDK, configurable `base_url`, client-side Tavily search loop in the researcher). A small factory routes per-request provider config to the right client. Cost meter shows tokens always and USD only for priced models.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, LangGraph, `anthropic` SDK, `openai` SDK (new dep), `httpx` (Tavily), Next.js 15 / TypeScript strict / Tailwind v4 frontend.

## Global Constraints

- **No abstraction layer:** no LiteLLM, no LangChain. Two concrete native clients behind a Protocol is the only allowed structure.
- **No `isinstance` for provider dispatch.** The researcher chooses its search strategy from the `llm.supports_server_side_search` capability flag only.
- **Anthropic native path must stay behaviorally identical** (parity). Free-tier behavior, depth presets, prompts, and the SSE contract are unchanged except for the additive `cost_update.priced` field.
- **Credentials are per-request in 2a:** non-secret config (`provider`, `base_url`, `model`) in the request body; secret keys in headers (`X-Anthropic-Key` for Anthropic, `X-Provider-Key` for the OpenAI-compatible path). No persistence (that is 2b).
- **One model for non-Anthropic BYOK:** a single user-chosen model drives all three roles. The native Anthropic path keeps its per-role models.
- **Tooling gates pass on every commit:** `make lint` (`ruff` + `mypy --strict`) and `make test` (`pytest`) must be green. Run from `backend/` (`uv run ...`) for backend, `frontend/` for frontend.
- **Conventional Commits, no `Co-Authored-By:` lines.** Commit per task.
- **Tavily global monthly quota cap is OUT of scope (2b).** 2a bounds search per-run via `max_iterations` only.

## Deviations from the spec (deliberate — review at plan approval)

1. **`CompletionResult` gains a `server_tool_uses: list[ToolUse]` field** (the spec's dataclass listed only `tool_uses`). It carries Anthropic *server-side* web_search calls so the researcher can keep emitting one `ResearcherProgress` per server-side search without touching the SDK `Message`. `OpenAICompatClient` always returns `[]` for it.
2. **`estimate_cost_usd` keeps its `float` return** (returns `0.0` for unknown models, as today) for backward compatibility with `scripts/run_planner.py`. A new `model_is_priced(model) -> bool` provides the priced/unpriced distinction the cost meter needs. (The spec phrased this as "estimator returns $/MTok or None"; this is the same behavior split across two functions to avoid breaking callers.)

## File map

**Created:**
- `backend/src/ara/llm/openai_client.py` — `OpenAICompatClient` (Protocol impl over `openai.AsyncOpenAI`).
- `backend/src/ara/llm/search.py` — `tavily_search`, `SearchResult`, `format_search_results`.
- `backend/src/ara/llm/factory.py` — `build_client(overrides, *, on_api_call)`.
- `backend/tests/test_openai_client.py`
- `backend/tests/test_tavily_search.py`
- `backend/tests/test_factory.py`

**Modified:**
- `backend/src/ara/llm/client.py` — add `ToolUse`/`CompletionResult`, `LLMClient` Protocol; rename class → `AnthropicClient`; `complete_with_tools` returns `CompletionResult`.
- `backend/src/ara/llm/__init__.py` — exports.
- `backend/src/ara/agents/__init__.py` — `extract_tool_use` reads `CompletionResult`.
- `backend/src/ara/agents/planner.py`, `researcher.py`, `synthesizer.py` — import/typing updates; researcher search dispatch.
- `backend/src/ara/graph/dag.py` — pass `tavily_api_key` to researcher.
- `backend/src/ara/runtime/orchestrator.py` — use `build_client`; emit `priced`.
- `backend/src/ara/runtime/overrides.py` — `provider`, `base_url` fields.
- `backend/src/ara/pricing.py` — extend table; add `model_is_priced`.
- `backend/src/ara/models/events.py` — `CostUpdate.priced`.
- `backend/src/ara/config.py` — `tavily_api_key`.
- `backend/src/ara/api/routes.py` — provider config in `create_research`.
- `backend/pyproject.toml` — add `openai` dependency.
- `backend/scripts/run_planner.py` — `LLMClient` → `AnthropicClient`.
- `backend/tests/test_llm_client.py`, `test_researcher.py` — adapt to `CompletionResult`.
- `backend/tests/test_api.py` — provider-config route tests.
- `frontend/lib/events.ts`, `frontend/hooks/use-research-stream.ts`, `frontend/components/cost-meter.tsx` — `priced` / "n/a".
- `frontend/components/research-form.tsx`, `frontend/lib/api.ts` — provider fields + `X-Provider-Key`.

---

## Task 1: Normalized `CompletionResult` + `LLMClient` Protocol + rename to `AnthropicClient`

Decouple the agents from Anthropic's `Message`. The native path must behave identically; this task only changes *types at the seam*. The Tavily loop and OpenAI client come later.

**Files:**
- Modify: `backend/src/ara/llm/client.py`
- Modify: `backend/src/ara/llm/__init__.py`
- Modify: `backend/src/ara/agents/__init__.py`
- Modify: `backend/src/ara/agents/planner.py:14` (import), `backend/src/ara/agents/researcher.py` (import + body), `backend/src/ara/agents/synthesizer.py:27` (import)
- Modify: `backend/src/ara/graph/dag.py:24` (import), `backend/src/ara/runtime/orchestrator.py:11,66` (import + construction)
- Modify: `backend/scripts/run_planner.py:23,38`
- Test: `backend/tests/test_llm_client.py`, `backend/tests/test_researcher.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ToolUse: id: str; name: str; input: dict[str, Any]`
  - `@dataclass(frozen=True) class CompletionResult: text: str; tool_uses: list[ToolUse]; server_tool_uses: list[ToolUse]; stop_reason: str; input_tokens: int; output_tokens: int`
  - `class LLMClient(Protocol)` with attrs `provider: str`, `supports_server_side_search: bool`, and async methods `complete_with_tools(...) -> CompletionResult`, `stream_completion(...) -> AsyncIterator[str]`.
  - `class AnthropicClient` (concrete, `provider="anthropic"`, `supports_server_side_search=True`, static `web_search_tool_spec`).
  - `extract_tool_use(result: CompletionResult, tool_name: str) -> dict[str, Any] | None` (reads `result.tool_uses`).
- Consumes: nothing new.

- [ ] **Step 1: Add the failing client test** — append to `backend/tests/test_llm_client.py` (also rename all `LLMClient(...)` constructions in that file to `AnthropicClient(...)` and update the import at line 14 to `from ara.llm.client import (WEB_SEARCH_TOOL_TYPE, AnthropicClient, CompletionResult, MessageStop, TextDelta, ToolUseBlock)`):

```python
def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _server_tool_use_block(name: str, payload: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "server_tool_use"
    b.id = "srv-1"
    b.name = name
    b.input = payload
    return b


async def test_complete_with_tools_returns_completion_result() -> None:
    response = MagicMock()
    response.usage = make_usage(input_tokens=11, output_tokens=4)
    response.stop_reason = "tool_use"
    response.content = [
        _text_block("thinking"),
        _server_tool_use_block("web_search", {"query": "rag"}),
        _tool_use_block("t1", "submit_finding", {"summary": "s"}),
    ]
    fake = make_fake_anthropic(create_return=response)

    client = AnthropicClient(anthropic_client=fake)
    result = await client.complete_with_tools(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )

    assert isinstance(result, CompletionResult)
    assert result.text == "thinking"
    assert result.stop_reason == "tool_use"
    assert result.input_tokens == 11
    assert [tu.name for tu in result.tool_uses] == ["submit_finding"]
    assert result.tool_uses[0].input == {"summary": "s"}
    assert [tu.input["query"] for tu in result.server_tool_uses] == ["rag"]


def test_anthropic_client_capability_flags() -> None:
    fake = MagicMock()
    client = AnthropicClient(anthropic_client=fake)
    assert client.provider == "anthropic"
    assert client.supports_server_side_search is True
```

Also adapt the three pre-existing tests that asserted `result is response` / `assert result is response`: `test_complete_with_tools_delegates_to_messages_create` and `test_complete_without_tools_omits_tools_kwarg` must give their mock a `.content = []` and `.stop_reason = "end_turn"`, and drop any `assert result is response` line (keep the `fake.messages.create` kwargs assertions). `test_on_api_call_hook_fires` keeps working once its mock gets `.content = []` and `.stop_reason = "end_turn"`.

- [ ] **Step 2: Run the new tests — verify they fail**

Run: `cd backend && uv run pytest tests/test_llm_client.py -q`
Expected: FAIL (`ImportError: cannot import name 'AnthropicClient'` / `CompletionResult`).

- [ ] **Step 3: Implement the types, Protocol, and rename in `client.py`**

Add imports near the top of `backend/src/ara/llm/client.py`:

```python
from typing import Any, Protocol, cast
```

Add the new types after the existing `MessageStop` dataclass block (before `class LLMClient`):

```python
@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class CompletionResult:
    text: str
    tool_uses: list[ToolUse]
    server_tool_uses: list[ToolUse]
    stop_reason: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    """Structural interface both native clients satisfy."""

    provider: str
    supports_server_side_search: bool

    async def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec] | None = None,
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult: ...

    def __call__(self) -> None: ...  # placeholder removed below
```

Remove that stray `__call__` line — instead declare `stream_completion` in the Protocol:

```python
class LLMClient(Protocol):
    provider: str
    supports_server_side_search: bool

    async def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec] | None = None,
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult: ...

    def stream_completion(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]: ...
```

Rename `class LLMClient:` (the concrete class, currently line 73) to `class AnthropicClient:` and add capability flags + change `complete_with_tools` to assemble a `CompletionResult`:

```python
class AnthropicClient:
    """Async, typed facade over `anthropic.AsyncAnthropic` (Protocol impl)."""

    provider: str = "anthropic"
    supports_server_side_search: bool = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        anthropic_client: AsyncAnthropic | None = None,
        on_api_call: OnApiCall | None = None,
    ) -> None:
        if anthropic_client is None:
            if not api_key:
                raise ValueError(
                    "AnthropicClient requires either `anthropic_client` or a non-empty `api_key`"
                )
            anthropic_client = AsyncAnthropic(api_key=api_key)
        self._client = anthropic_client
        self._on_api_call = on_api_call

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicClient:
        return cls(api_key=settings.anthropic_api_key)
```

Keep `web_search_tool_spec` unchanged. Change `complete_with_tools` so its final lines build and return a `CompletionResult` instead of the raw `Message`:

```python
        response: Message = await self._client.messages.create(**kwargs)
        await self._record(model, response.usage.input_tokens, response.usage.output_tokens)
        return _to_completion_result(response)
```

Add a module-level assembler:

```python
def _to_completion_result(response: Message) -> CompletionResult:
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    server_tool_uses: list[ToolUse] = []
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "tool_use":
            tool_uses.append(
                ToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=cast(dict[str, Any], getattr(block, "input", {}) or {}),
                )
            )
        elif btype == "server_tool_use":
            server_tool_uses.append(
                ToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=cast(dict[str, Any], getattr(block, "input", {}) or {}),
                )
            )
    return CompletionResult(
        text="".join(text_parts),
        tool_uses=tool_uses,
        server_tool_uses=server_tool_uses,
        stop_reason=response.stop_reason or "end_turn",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
```

Leave `stream_completion` and `stream_completion_with_tools` unchanged (they stay methods of `AnthropicClient`).

- [ ] **Step 4: Update `llm/__init__.py` exports**

```python
from ara.llm.client import (
    WEB_SEARCH_TOOL_NAME,
    WEB_SEARCH_TOOL_TYPE,
    AnthropicClient,
    CompletionResult,
    LLMClient,
    MessageStop,
    OnApiCall,
    StreamEvent,
    TextDelta,
    ToolUse,
    ToolUseBlock,
)

__all__ = [
    "WEB_SEARCH_TOOL_NAME",
    "WEB_SEARCH_TOOL_TYPE",
    "AnthropicClient",
    "CompletionResult",
    "LLMClient",
    "MessageStop",
    "OnApiCall",
    "StreamEvent",
    "TextDelta",
    "ToolUse",
    "ToolUseBlock",
]
```

- [ ] **Step 5: Update `extract_tool_use` in `agents/__init__.py`**

Replace the `from anthropic.types import Message` import and the function body:

```python
from collections.abc import Awaitable, Callable
from typing import Any

from ara.llm.client import CompletionResult
from ara.models.events import ResearchEvent

EventEmitter = Callable[[ResearchEvent], Awaitable[None]]
```

```python
def extract_tool_use(result: CompletionResult, tool_name: str) -> dict[str, Any] | None:
    """Return the input of the first client-side tool_use matching `tool_name`, or None."""
    for tu in result.tool_uses:
        if tu.name == tool_name:
            return tu.input
    return None
```

(Remove the now-unused `cast` import.)

- [ ] **Step 6: Update planner / synthesizer / dag / orchestrator / script imports**

In `agents/planner.py` line 14: `from ara.llm.client import LLMClient, ToolSpec` stays (the `llm: LLMClient` param is now the Protocol — fine). No body change.

In `agents/synthesizer.py` line 27: `from ara.llm.client import LLMClient` stays. No body change.

In `graph/dag.py` line 24: `from ara.llm.client import LLMClient` stays.

In `runtime/orchestrator.py`: change line 11 to `from ara.llm.client import AnthropicClient, LLMClient` and line 66 from `llm = LLMClient(...)` to:

```python
    if llm is None:
        llm = AnthropicClient(api_key=overrides.api_key, on_api_call=on_api_call)
```

(The `llm: LLMClient | None` annotation at line 28 stays — it is now the Protocol.)

In `scripts/run_planner.py`: change line 23 to `from ara.llm.client import AnthropicClient` and line 38 to `llm = AnthropicClient(api_key=settings.anthropic_api_key, on_api_call=record)`.

- [ ] **Step 7: Update researcher body to read `CompletionResult`** in `agents/researcher.py`

Change the import (line 22) to `from ara.llm.client import AnthropicClient, ToolSpec`. In `research_sub_query`, change `LLMClient.web_search_tool_spec(...)` (line 147) to `AnthropicClient.web_search_tool_spec(...)`. Add `from ara.llm.client import LLMClient` to the typing import as well so the `llm: LLMClient` param stays the Protocol — combine: `from ara.llm.client import AnthropicClient, LLMClient, ToolSpec`.

Replace the block from `response = await llm.complete_with_tools(...)` through the `extract_tool_use` call (lines 155–186) with:

```python
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
```

(`_build_finding` and the `try/except` below it are unchanged.)

- [ ] **Step 8: Rewrite `backend/tests/test_researcher.py` to build `CompletionResult`**

Replace the helper section (imports + `_server_tool_use` / `_tool_use` / `_make_response`) and every `_make_response([...])` call. New top of file:

```python
from ara.agents import ResearcherError
from ara.agents.researcher import (
    RESEARCHER_OFFLINE_SYSTEM_PROMPT,
    SUBMIT_FINDING_TOOL_NAME,
    research_sub_query,
)
from ara.llm.client import WEB_SEARCH_TOOL_TYPE, CompletionResult, ToolUse
from ara.models.events import ResearcherProgress, ResearcherStarted, ResearchEvent
from ara.models.research import Priority, SubQuery, SubQueryFinding


def _tu(name: str, payload: dict[str, Any]) -> ToolUse:
    return ToolUse(id=f"id-{name}", name=name, input=payload)


def _result(
    *,
    tool_uses: list[ToolUse] | None = None,
    server_tool_uses: list[ToolUse] | None = None,
    stop_reason: str = "tool_use",
    in_tokens: int = 100,
    out_tokens: int = 50,
) -> CompletionResult:
    return CompletionResult(
        text="",
        tool_uses=tool_uses or [],
        server_tool_uses=server_tool_uses or [],
        stop_reason=stop_reason,
        input_tokens=in_tokens,
        output_tokens=out_tokens,
    )
```

Convert each test's response. The mapping: a `_server_tool_use("web_search", {...})` becomes a `server_tool_uses=[_tu("web_search", {...})]` entry; a `_tool_use("submit_finding", {...})` becomes `tool_uses=[_tu("submit_finding", {...})]`. Examples (apply the same pattern to all tests in the file):

```python
async def test_researcher_happy_path() -> None:
    sq = SubQuery(question="What is RAG?", rationale="Foundations.", priority=Priority.HIGH)
    result = _result(
        server_tool_uses=[_tu("web_search", {"query": "RAG retrieval augmented generation"})],
        tool_uses=[
            _tu(
                SUBMIT_FINDING_TOOL_NAME,
                {
                    "summary": "RAG augments LLMs with retrieved context.",
                    "key_facts": [
                        {
                            "statement": "RAG retrieves before generating.",
                            "source_urls": ["https://example.com/rag"],
                        }
                    ],
                    "sources": [{"url": "https://example.com/rag", "title": "RAG intro"}],
                },
            )
        ],
    )
    llm = MagicMock()
    llm.supports_server_side_search = True
    llm.complete_with_tools = AsyncMock(return_value=result)
    emit, events = _make_emit()

    finding = await research_sub_query(sub_query=sq, llm=llm, model="m", emit=emit)
    assert isinstance(finding, SubQueryFinding)
    assert finding.summary == "RAG augments LLMs with retrieved context."
    assert finding.key_facts[0].citation_ids == [finding.sources[0].id]
    assert any(isinstance(e, ResearcherStarted) for e in events)
    assert any(isinstance(e, ResearcherProgress) for e in events)
```

For `test_researcher_emits_progress_per_search`: pass three `_tu("web_search", {"query": ...})` in `server_tool_uses` plus the submit_finding `_tu` in `tool_uses`. For `test_researcher_raises_when_submit_finding_missing`: `_result(server_tool_uses=[_tu("web_search", {"query": "q"})], stop_reason="end_turn")` with empty `tool_uses`. For the budget test: `_result(tool_uses=[_tu(SUBMIT_FINDING_TOOL_NAME, {...})], in_tokens=200_000)`. For the malformed / multi-source / skips-unknown / default-tools / disabled tests: put the single submit_finding `_tu` in `tool_uses`. **Every test that calls `research_sub_query` must set `llm.supports_server_side_search = True`** on its MagicMock (the dispatch in Task 5 reads it; setting it now keeps tests forward-compatible and is harmless in Task 1). The `test_researcher_includes_web_search_tool_by_default` / `test_researcher_omits_web_search_when_disabled` assertions on `llm.complete_with_tools.await_args.kwargs["tools"]` / `["system"]` are unchanged.

- [ ] **Step 9: Run the full backend suite + gates**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS (all tests green; no lint/type errors). If mypy flags the Protocol's `stream_completion` returning `AsyncIterator` vs the concrete `async def` generator, ensure the Protocol declares it as a plain `def ... -> AsyncIterator[str]: ...` (not `async def`) — generators structurally satisfy that.

- [ ] **Step 10: Commit**

```bash
cd backend && git add -A
git commit -m "refactor(llm): normalize completions to CompletionResult + LLMClient Protocol

Rename concrete client to AnthropicClient; agents read CompletionResult
(tool_uses + server_tool_uses) instead of the Anthropic Message. Native
path behavior is unchanged."
```

---

## Task 2: Pricing table extension, `model_is_priced`, and `cost_update.priced`

Make the cost meter able to say "n/a" for models with no known price, without lying with `$0`.

**Files:**
- Modify: `backend/src/ara/pricing.py`
- Modify: `backend/src/ara/models/events.py:66-73`
- Modify: `backend/src/ara/runtime/orchestrator.py:53-63`
- Test: `backend/tests/test_pricing.py` (create), `backend/tests/test_sse_contract.py` (verify still green)

**Interfaces:**
- Produces: `model_is_priced(model: str) -> bool`; `CostUpdate` gains `priced: bool = True`.
- Consumes: `estimate_cost_usd` (unchanged).

- [ ] **Step 1: Write the failing pricing test** — create `backend/tests/test_pricing.py`:

```python
from ara.pricing import estimate_cost_usd, model_is_priced


def test_known_anthropic_model_is_priced() -> None:
    assert model_is_priced("claude-haiku-4-5") is True
    assert estimate_cost_usd("claude-haiku-4-5", 1_000_000, 0) == 0.80


def test_known_openai_model_is_priced() -> None:
    assert model_is_priced("gpt-4o-mini") is True
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 1_000_000) == 0.15 + 0.60


def test_unknown_model_is_unpriced_and_costs_zero() -> None:
    assert model_is_priced("some/unknown-model") is False
    assert estimate_cost_usd("some/unknown-model", 9_999, 9_999) == 0.0
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_pricing.py -q`
Expected: FAIL (`ImportError: cannot import name 'model_is_priced'`).

- [ ] **Step 3: Extend `pricing.py`**

Add common OpenAI-family rows to `PRICING` (keep the comment that says update when prices change) and add the helper:

```python
PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-haiku-4-5": (0.80, 4.0),
    # OpenAI (and OpenRouter slugs) — list prices, update when they change.
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "openai/gpt-4o": (2.50, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
}


def model_is_priced(model: str) -> bool:
    """True when `model` has a known $/MTok rate (so USD is meaningful)."""
    return model in PRICING
```

- [ ] **Step 4: Add `priced` to `CostUpdate`** in `models/events.py`:

```python
class CostUpdate(BaseModel):
    """Running API cost snapshot; emitted after every provider response."""

    type: Literal["cost_update"] = "cost_update"
    model: str
    input_tokens: int
    output_tokens: int
    cumulative_usd: float
    priced: bool = True
```

- [ ] **Step 5: Wire it in the orchestrator** — replace the `on_api_call` body (`runtime/orchestrator.py` lines 53–63) and the import at line 15:

```python
from ara.pricing import estimate_cost_usd, model_is_priced
```

```python
    async def on_api_call(model: str, input_tokens: int, output_tokens: int) -> None:
        nonlocal cumulative_usd
        cumulative_usd += estimate_cost_usd(model, input_tokens, output_tokens)
        await emit(
            CostUpdate(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cumulative_usd=cumulative_usd,
                priced=model_is_priced(model),
            )
        )
```

- [ ] **Step 6: Run pricing + SSE contract tests + gates**

Run: `cd backend && uv run pytest tests/test_pricing.py tests/test_sse_contract.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS. (`cumulative_usd` stays monotonic because unpriced models add `0.0`.)

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A
git commit -m "feat(pricing): price OpenAI models + cost_update.priced for n/a rendering"
```

---

## Task 3: `OpenAICompatClient`

A second native client over the official `openai` SDK, satisfying the `LLMClient` Protocol. Translates normalized messages + Anthropic-shape tools to OpenAI Chat Completions and back to `CompletionResult`.

**Files:**
- Create: `backend/src/ara/llm/openai_client.py`
- Modify: `backend/pyproject.toml` (add `openai`)
- Test: `backend/tests/test_openai_client.py`

**Interfaces:**
- Produces: `class OpenAICompatClient` — `provider="openai"`, `supports_server_side_search=False`; `__init__(*, api_key=None, base_url=None, openai_client=None, on_api_call=None)`; `complete_with_tools(...) -> CompletionResult`; `stream_completion(...) -> AsyncIterator[str]`.
- Consumes: `CompletionResult`, `ToolUse`, `ToolSpec`, `MessageDict`, `OnApiCall` from `ara.llm.client`.

- [ ] **Step 1: Add the `openai` dependency**

In `backend/pyproject.toml` add to `dependencies`: `"openai>=1.55.0",`. Then:

Run: `cd backend && uv sync`
Expected: resolves and installs `openai`.

- [ ] **Step 2: Write the failing tests** — create `backend/tests/test_openai_client.py`:

```python
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ara.llm.client import CompletionResult
from ara.llm.openai_client import OpenAICompatClient


def _make_completion(
    *,
    content: str | None = "hi",
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 12,
    completion_tokens: int = 3,
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason
    comp = MagicMock()
    comp.choices = [choice]
    comp.usage = MagicMock()
    comp.usage.prompt_tokens = prompt_tokens
    comp.usage.completion_tokens = completion_tokens
    return comp


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _fake_openai(*, create_return: Any = None) -> MagicMock:
    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=create_return)
    return fake


def test_capability_flags() -> None:
    client = OpenAICompatClient(openai_client=MagicMock())
    assert client.provider == "openai"
    assert client.supports_server_side_search is False


async def test_complete_with_tools_parses_tool_calls() -> None:
    comp = _make_completion(
        content=None,
        tool_calls=[_tool_call("c1", "submit_finding", {"summary": "s"})],
        finish_reason="tool_calls",
    )
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)

    result = await client.complete_with_tools(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "submit_finding", "description": "d", "input_schema": {"type": "object"}}],
        system="sys",
    )

    assert isinstance(result, CompletionResult)
    assert result.stop_reason == "tool_use"
    assert result.server_tool_uses == []
    assert result.tool_uses[0].name == "submit_finding"
    assert result.tool_uses[0].input == {"summary": "s"}
    assert result.input_tokens == 12

    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "submit_finding"


async def test_complete_translates_tool_choice() -> None:
    comp = _make_completion(content="", tool_calls=[_tool_call("c1", "p", {})])
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)
    await client.complete_with_tools(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "p", "description": "d", "input_schema": {"type": "object"}}],
        tool_choice={"type": "tool", "name": "p"},
    )
    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "p"}}


async def test_complete_translates_assistant_and_tool_turns() -> None:
    comp = _make_completion()
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)
    await client.complete_with_tools(
        model="m",
        messages=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "web_search", "input": {"query": "x"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "results"},
        ],
    )
    sent = fake.chat.completions.create.await_args.kwargs["messages"]
    assistant = next(m for m in sent if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "web_search"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "x"}
    tool_msg = next(m for m in sent if m["role"] == "tool")
    assert tool_msg == {"role": "tool", "tool_call_id": "c1", "content": "results"}


async def test_complete_fires_on_api_call() -> None:
    comp = _make_completion(prompt_tokens=20, completion_tokens=8)
    fake = _fake_openai(create_return=comp)
    calls: list[tuple[str, int, int]] = []

    async def hook(m: str, i: int, o: int) -> None:
        calls.append((m, i, o))

    client = OpenAICompatClient(openai_client=fake, on_api_call=hook)
    await client.complete_with_tools(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert calls == [("gpt-4o", 20, 8)]


class _FakeChunkStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for c in self._chunks:
            yield c


def _delta_chunk(text: str | None) -> MagicMock:
    chunk = MagicMock()
    choice = MagicMock()
    choice.delta = MagicMock()
    choice.delta.content = text
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def _usage_chunk(prompt: int, completion: int) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = []
    chunk.usage = MagicMock()
    chunk.usage.prompt_tokens = prompt
    chunk.usage.completion_tokens = completion
    return chunk


async def test_stream_completion_yields_text_and_records_usage() -> None:
    stream = _FakeChunkStream([_delta_chunk("hel"), _delta_chunk("lo"), _usage_chunk(5, 2)])
    fake = _fake_openai()
    fake.chat.completions.create = AsyncMock(return_value=stream)
    calls: list[tuple[str, int, int]] = []

    async def hook(m: str, i: int, o: int) -> None:
        calls.append((m, i, o))

    client = OpenAICompatClient(openai_client=fake, on_api_call=hook)
    out: list[str] = []
    async for tok in client.stream_completion(model="m", messages=[{"role": "user", "content": "q"}]):
        out.append(tok)

    assert out == ["hel", "lo"]
    assert calls == [("m", 5, 2)]
    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
```

- [ ] **Step 3: Run the tests — verify they fail**

Run: `cd backend && uv run pytest tests/test_openai_client.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.llm.openai_client`).

- [ ] **Step 4: Implement `openai_client.py`**

```python
"""OpenAI-compatible native client (configurable base_url).

Translates the normalized message/tool shapes used by the agents into the
OpenAI Chat Completions wire format and back into a `CompletionResult`.
No server-side web search; the researcher drives a client-side Tavily loop
for this provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from ara.llm.client import (
    CompletionResult,
    MessageDict,
    OnApiCall,
    ToolSpec,
    ToolUse,
)

_FINISH_REASON_MAP = {"tool_calls": "tool_use", "stop": "end_turn"}


class OpenAICompatClient:
    provider: str = "openai"
    supports_server_side_search: bool = False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        openai_client: AsyncOpenAI | None = None,
        on_api_call: OnApiCall | None = None,
    ) -> None:
        if openai_client is None:
            if not api_key:
                raise ValueError(
                    "OpenAICompatClient requires either `openai_client` or a non-empty `api_key`"
                )
            openai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = openai_client
        self._on_api_call = on_api_call

    async def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec] | None = None,
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)

        comp: Any = await self._client.chat.completions.create(**kwargs)
        message = comp.choices[0].message
        text = message.content or ""
        tool_uses: list[ToolUse] = []
        for tc in message.tool_calls or []:
            try:
                parsed = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                parsed = {}
            tool_uses.append(ToolUse(id=tc.id, name=tc.function.name, input=parsed))

        in_tokens = comp.usage.prompt_tokens if comp.usage else 0
        out_tokens = comp.usage.completion_tokens if comp.usage else 0
        await self._record(model, in_tokens, out_tokens)

        finish = comp.choices[0].finish_reason or "stop"
        return CompletionResult(
            text=text,
            tool_uses=tool_uses,
            server_tool_uses=[],
            stop_reason=_FINISH_REASON_MAP.get(finish, finish),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )

    async def stream_completion(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        in_tokens = 0
        out_tokens = 0
        text_len = 0
        stream: Any = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.usage is not None:
                in_tokens = chunk.usage.prompt_tokens
                out_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                text_len += len(piece)
                yield piece
        if out_tokens == 0 and text_len:
            # Some base_urls omit usage on streaming — rough fallback so cost still records.
            out_tokens = max(1, text_len // 4)
        await self._record(model, in_tokens, out_tokens)

    async def _record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if self._on_api_call is not None:
            await self._on_api_call(model, input_tokens, output_tokens)


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object"}),
        },
    }


def _to_openai_tool_choice(tool_choice: dict[str, Any]) -> Any:
    if tool_choice.get("type") == "tool" and "name" in tool_choice:
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return tool_choice


def _to_openai_messages(
    messages: list[MessageDict], system: str | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system is not None:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out
```

- [ ] **Step 5: Run tests + gates**

Run: `cd backend && uv run pytest tests/test_openai_client.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS. If mypy can't resolve `openai` types under strict, add to the existing `[[tool.mypy.overrides]]` module list in `pyproject.toml`: change `module = ["langgraph.*", "asyncpg.*"]` to `module = ["langgraph.*", "asyncpg.*", "openai", "openai.*"]` with `ignore_missing_imports = true`.

- [ ] **Step 6: Commit**

```bash
cd backend && git add -A
git commit -m "feat(llm): OpenAICompatClient over the openai SDK (Protocol impl)"
```

---

## Task 4: Tavily search module

A thin async Tavily client + result formatter for the non-Anthropic researcher loop. Failures degrade to an empty list (partial failure is expected).

**Files:**
- Create: `backend/src/ara/llm/search.py`
- Test: `backend/tests/test_tavily_search.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class SearchResult: title: str; url: str; content: str`
  - `async def tavily_search(query: str, *, api_key: str | None, max_results: int = 5) -> list[SearchResult]`
  - `def format_search_results(results: list[SearchResult]) -> str`

- [ ] **Step 1: Write the failing tests** — create `backend/tests/test_tavily_search.py` (uses `respx`, already a dev dep):

```python
from __future__ import annotations

import httpx
import respx

from ara.llm.search import SearchResult, format_search_results, tavily_search

TAVILY_URL = "https://api.tavily.com/search"


async def test_tavily_search_parses_results() -> None:
    with respx.mock:
        respx.post(TAVILY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {"title": "T1", "url": "https://a.com", "content": "c1"},
                        {"title": "T2", "url": "https://b.com", "content": "c2"},
                    ]
                },
            )
        )
        results = await tavily_search("q", api_key="k")
    assert results == [
        SearchResult(title="T1", url="https://a.com", content="c1"),
        SearchResult(title="T2", url="https://b.com", content="c2"),
    ]


async def test_tavily_search_empty_key_returns_empty() -> None:
    results = await tavily_search("q", api_key=None)
    assert results == []


async def test_tavily_search_http_error_degrades_to_empty() -> None:
    with respx.mock:
        respx.post(TAVILY_URL).mock(return_value=httpx.Response(500))
        results = await tavily_search("q", api_key="k")
    assert results == []


def test_format_search_results_renders_rows() -> None:
    text = format_search_results(
        [SearchResult(title="T1", url="https://a.com", content="c1")]
    )
    assert "T1" in text
    assert "https://a.com" in text
    assert "c1" in text


def test_format_empty_results() -> None:
    assert "no results" in format_search_results([]).lower()
```

- [ ] **Step 2: Run them — verify they fail**

Run: `cd backend && uv run pytest tests/test_tavily_search.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.llm.search`).

- [ ] **Step 3: Implement `search.py`**

```python
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
```

- [ ] **Step 4: Run tests + gates**

Run: `cd backend && uv run pytest tests/test_tavily_search.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd backend && git add -A
git commit -m "feat(llm): Tavily client-side search module"
```

---

## Task 5: Researcher search dispatch (server-side vs Tavily loop)

Add the client-side Tavily loop and dispatch on the `supports_server_side_search` capability flag. Wire the server Tavily key through config → dag → researcher.

**Files:**
- Modify: `backend/src/ara/config.py` (add `tavily_api_key`)
- Modify: `backend/src/ara/agents/researcher.py`
- Modify: `backend/src/ara/graph/dag.py:77-85` (pass `tavily_api_key`)
- Test: `backend/tests/test_researcher.py` (add tests), `backend/tests/test_config.py` (add field assertion)

**Interfaces:**
- Consumes: `tavily_search`, `format_search_results` (Task 4); `supports_server_side_search` on `LLMClient`.
- Produces: `research_sub_query(..., tavily_api_key: str | None = None)` new kwarg; module constants `WEB_SEARCH_CLIENT_TOOL_NAME = "web_search"`, `WEB_SEARCH_CLIENT_TOOL: ToolSpec`, `RESEARCHER_TAVILY_SYSTEM_PROMPT`.

- [ ] **Step 1: Add the `tavily_api_key` setting** in `config.py`, under the Anthropic block:

```python
    # Tavily (server-provided client-side search for non-Anthropic providers)
    tavily_api_key: str = Field(default="")
```

- [ ] **Step 2: Write failing researcher loop tests** — append to `backend/tests/test_researcher.py`:

```python
class _ScriptedLLM:
    """Fake LLMClient that returns a queued CompletionResult per call."""

    provider = "openai"
    supports_server_side_search = False

    def __init__(self, results: list[CompletionResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def complete_with_tools(self, **kwargs: Any) -> CompletionResult:
        self.calls.append(kwargs)
        return self._results.pop(0)


async def test_researcher_tavily_loop_searches_then_submits(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    searched: list[str] = []

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        searched.append(query)
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="What is RAG?", rationale="r", priority=Priority.HIGH)
    llm = _ScriptedLLM(
        [
            _result(tool_uses=[_tu("web_search", {"query": "rag basics"})], stop_reason="tool_use"),
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "RAG augments LLMs.",
                            "key_facts": [
                                {"statement": "x", "source_urls": ["https://a.com"]}
                            ],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            ),
        ]
    )
    emit, events = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="gpt-4o", emit=emit, tavily_api_key="k"
    )

    assert searched == ["rag basics"]
    assert finding.summary == "RAG augments LLMs."
    assert any(isinstance(e, ResearcherProgress) for e in events)
    # Second call must carry the assistant tool-call turn + tool result turn.
    second_msgs = llm.calls[1]["messages"]
    assert any(m["role"] == "assistant" and m.get("tool_calls") for m in second_msgs)
    assert any(m["role"] == "tool" for m in second_msgs)


async def test_researcher_tavily_loop_raises_when_never_submits(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM(
        [_result(tool_uses=[_tu("web_search", {"query": "q"})]) for _ in range(10)]
    )
    emit, _ = _make_emit()
    with pytest.raises(ResearcherError):
        await research_sub_query(
            sub_query=sq, llm=llm, model="gpt-4o", emit=emit, max_iterations=2, tavily_api_key="k"
        )


async def test_researcher_offline_works_for_openai_client() -> None:
    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM(
        [
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "offline.",
                            "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            )
        ]
    )
    emit, _ = _make_emit()
    finding = await research_sub_query(
        sub_query=sq, llm=llm, model="gpt-4o", emit=emit, web_search_enabled=False
    )
    assert finding.summary == "offline."
```

- [ ] **Step 3: Run them — verify they fail**

Run: `cd backend && uv run pytest tests/test_researcher.py -k "tavily or offline_works" -q`
Expected: FAIL (`research_sub_query` has no `tavily_api_key`; no Tavily branch).

- [ ] **Step 4: Implement the dispatch + loop in `researcher.py`**

Add imports:

```python
from ara.agents import EventEmitter, ResearcherError, extract_tool_use
from ara.llm.client import AnthropicClient, CompletionResult, LLMClient, ToolSpec
from ara.llm.search import format_search_results, tavily_search
```

Add constants near `SUBMIT_FINDING_TOOL`:

```python
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
```

Change the signature of `research_sub_query` to add `tavily_api_key: str | None = None` (place it after `web_search_enabled`). Replace the body after the `await emit(ResearcherStarted(...))` line so the offline + server-side single-call path is factored and a Tavily branch is added:

```python
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
            ResearcherProgress(sub_query_id=sub_query.id, tool_call=f"{tu.name}({query!r})")
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
```

Add the Tavily loop helper after `research_sub_query`:

```python
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
    """Client-side search loop for providers without server-side web search."""
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
```

Ensure `from typing import Any` is imported (it already is) and `SubQuery`, `SubQueryFinding` remain imported.

- [ ] **Step 5: Pass `tavily_api_key` from the dag** — in `graph/dag.py`, in `run_one` (the `research_sub_query(...)` call around line 77), add:

```python
                finding = await research_sub_query(
                    sub_query=sq,
                    llm=llm,
                    model=models.researcher,
                    emit=emit,
                    max_iterations=opts.max_iterations,
                    input_token_budget=settings.ara_researcher_input_token_budget,
                    web_search_enabled=opts.web_search_enabled,
                    tavily_api_key=settings.tavily_api_key,
                )
```

- [ ] **Step 6: Add a config field test** — append to `backend/tests/test_config.py`:

```python
def test_settings_has_tavily_key_default_empty() -> None:
    from ara.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.tavily_api_key == ""
```

- [ ] **Step 7: Run tests + gates**

Run: `cd backend && uv run pytest tests/test_researcher.py tests/test_config.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd backend && git add -A
git commit -m "feat(researcher): client-side Tavily search loop for non-Anthropic providers"
```

---

## Task 6: `RuntimeOverrides` provider fields + client factory + orchestrator wiring

Route per-request provider config to the right client.

**Files:**
- Modify: `backend/src/ara/runtime/overrides.py`
- Create: `backend/src/ara/llm/factory.py`
- Modify: `backend/src/ara/runtime/orchestrator.py:65-66`
- Test: `backend/tests/test_factory.py`, `backend/tests/test_orchestrator.py` (verify still green)

**Interfaces:**
- Produces:
  - `RuntimeOverrides` gains `provider: str = "anthropic"`, `base_url: str | None = None` (added after `options`, with defaults — existing positional/kw constructions unaffected).
  - `build_client(overrides: RuntimeOverrides, *, on_api_call: OnApiCall | None = None) -> LLMClient`.
- Consumes: `AnthropicClient`, `OpenAICompatClient`.

- [ ] **Step 1: Add provider fields to `RuntimeOverrides`**

```python
@dataclass(frozen=True)
class RuntimeOverrides:
    api_key: str
    planner_model: str
    researcher_model: str
    synthesizer_model: str
    options: ResearchOptions
    provider: str = "anthropic"
    base_url: str | None = None
```

- [ ] **Step 2: Write the failing factory tests** — create `backend/tests/test_factory.py`:

```python
from __future__ import annotations

import pytest

from ara.llm.client import AnthropicClient
from ara.llm.factory import build_client
from ara.llm.openai_client import OpenAICompatClient
from ara.options import options_for_depth
from ara.runtime.overrides import RuntimeOverrides


def _overrides(**kw: object) -> RuntimeOverrides:
    base: dict[str, object] = {
        "api_key": "k",
        "planner_model": "m",
        "researcher_model": "m",
        "synthesizer_model": "m",
        "options": options_for_depth("quick"),
    }
    base.update(kw)
    return RuntimeOverrides(**base)  # type: ignore[arg-type]


def test_build_client_anthropic_default() -> None:
    client = build_client(_overrides())
    assert isinstance(client, AnthropicClient)


def test_build_client_openai() -> None:
    client = build_client(
        _overrides(provider="openai", base_url="https://api.openai.com/v1")
    )
    assert isinstance(client, OpenAICompatClient)


def test_build_client_openai_requires_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_client(_overrides(provider="openai", base_url=None))
```

- [ ] **Step 3: Run them — verify they fail**

Run: `cd backend && uv run pytest tests/test_factory.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.llm.factory`).

- [ ] **Step 4: Implement `factory.py`**

```python
"""Pick the right native LLM client for a per-request provider config."""

from __future__ import annotations

from ara.llm.client import AnthropicClient, LLMClient, OnApiCall
from ara.llm.openai_client import OpenAICompatClient
from ara.runtime.overrides import RuntimeOverrides


def build_client(
    overrides: RuntimeOverrides, *, on_api_call: OnApiCall | None = None
) -> LLMClient:
    if overrides.provider == "openai":
        if not overrides.base_url:
            raise ValueError("openai provider requires a base_url")
        return OpenAICompatClient(
            api_key=overrides.api_key,
            base_url=overrides.base_url,
            on_api_call=on_api_call,
        )
    return AnthropicClient(api_key=overrides.api_key, on_api_call=on_api_call)
```

- [ ] **Step 5: Use the factory in the orchestrator** — `runtime/orchestrator.py`: replace the import at line 11 and the construction at lines 65–66:

```python
from ara.llm.client import LLMClient
from ara.llm.factory import build_client
```

```python
    if llm is None:
        llm = build_client(overrides, on_api_call=on_api_call)
```

(Remove the now-unused `AnthropicClient` import added in Task 1 if it is no longer referenced in this file.)

- [ ] **Step 6: Run factory + orchestrator tests + gates**

Run: `cd backend && uv run pytest tests/test_factory.py tests/test_orchestrator.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS (orchestrator tests inject `llm=` so the factory branch is exercised only by the default path; the existing `_RecordingLLM` tests still work).

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A
git commit -m "feat(runtime): provider config on RuntimeOverrides + build_client factory"
```

---

## Task 7: API — per-request provider config in `create_research`

Accept `provider` / `base_url` / `model` in the request body and `X-Provider-Key` in the header; validate; build the right overrides.

**Files:**
- Modify: `backend/src/ara/api/routes.py:40-43` (request model), `:329-396` (`create_research`)
- Test: `backend/tests/test_api.py` (add cases)

**Interfaces:**
- Consumes: `RuntimeOverrides(provider=..., base_url=...)`.
- Produces: `CreateResearchRequest` gains `provider: Literal["anthropic", "openai"] = "anthropic"`, `base_url: str | None = None`, `model: str | None = None`. New header param `x_provider_key`.

- [ ] **Step 1: Inspect how `test_api.py` drives `create_research`**

Run: `cd backend && uv run pytest tests/test_api.py -q` and open the file to see the existing client fixture / monkeypatch of `run_report`. Mirror that style for the new tests (do NOT hit a real provider — the existing tests already patch `run_report` or the store; reuse that exact mechanism).

- [ ] **Step 2: Write failing route tests** — add to `backend/tests/test_api.py` following the file's existing fixture pattern. The intent (translate to the file's actual client/fixture):

```python
async def test_create_research_openai_requires_base_url_and_model(...) -> None:
    # POST /api/research with body provider="openai" but no base_url/model and
    # header X-Provider-Key set → 400.
    resp = await client.post(
        "/api/research",
        json={"question": "q", "provider": "openai"},
        headers={**auth_headers, "X-Provider-Key": "sk-test"},
    )
    assert resp.status_code == 400


async def test_create_research_openai_builds_openai_overrides(...) -> None:
    # Capture the overrides passed to run_report (patch run_report with a recorder).
    captured: dict[str, Any] = {}

    async def fake_run_report(**kwargs: Any) -> None:
        captured["overrides"] = kwargs["overrides"]

    monkeypatch.setattr("ara.api.routes.run_report", fake_run_report)
    resp = await client.post(
        "/api/research",
        json={
            "question": "q",
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "depth": "standard",
            "browse_web": True,
        },
        headers={**auth_headers, "X-Provider-Key": "sk-test"},
    )
    assert resp.status_code == 200
    ov = captured["overrides"]
    assert ov.provider == "openai"
    assert ov.base_url == "https://api.openai.com/v1"
    assert ov.api_key == "sk-test"
    assert ov.planner_model == ov.researcher_model == ov.synthesizer_model == "gpt-4o"
```

- [ ] **Step 3: Run them — verify they fail**

Run: `cd backend && uv run pytest tests/test_api.py -k "openai" -q`
Expected: FAIL (provider rejected / fields ignored).

- [ ] **Step 4: Extend `CreateResearchRequest`** in `routes.py`:

```python
class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Depth = "standard"
    browse_web: bool = True
    provider: Literal["anthropic", "openai"] = "anthropic"
    base_url: str | None = None
    model: str | None = None
```

- [ ] **Step 5: Branch on provider in `create_research`** — add the `x_provider_key` header param to the signature and a leading OpenAI branch. Insert before the existing `if x_anthropic_key:` block:

```python
async def create_research(
    req: CreateResearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    x_anthropic_key: str | None = Header(default=None, alias="X-Anthropic-Key"),
    x_provider_key: str | None = Header(default=None, alias="X-Provider-Key"),
) -> CreateResearchResponse:
    pool = _pool_or_503(request)
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks

    if req.provider == "openai":
        if not (req.base_url and req.model and x_provider_key):
            raise HTTPException(
                status_code=400,
                detail="openai provider requires base_url, model, and X-Provider-Key header",
            )
        options = options_for_depth(req.depth, web_search_enabled=req.browse_web)
        overrides = RuntimeOverrides(
            api_key=x_provider_key,
            planner_model=req.model,
            researcher_model=req.model,
            synthesizer_model=req.model,
            options=options,
            provider="openai",
            base_url=req.base_url,
        )
    elif x_anthropic_key:
        api_key = x_anthropic_key
        options = options_for_depth(req.depth, web_search_enabled=req.browse_web)
        overrides = RuntimeOverrides(
            api_key=api_key,
            planner_model=settings.claude_planner_model,
            researcher_model=settings.claude_researcher_model,
            synthesizer_model=settings.claude_synthesizer_model,
            options=options,
        )
    else:
        # ... existing free-tier block unchanged ...
```

Keep the existing free-tier `else` body (quota check + Haiku) exactly as-is, and the `report_id = uuid4()` / `asyncio.create_task(run_report(...))` tail unchanged.

- [ ] **Step 6: Run route tests + full suite + gates**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A
git commit -m "feat(api): per-request provider config (OpenAI-compat) in create_research"
```

---

## Task 8: Frontend — cost meter "n/a" for unpriced models

**Files:**
- Modify: `frontend/lib/events.ts:48-54`
- Modify: `frontend/hooks/use-research-stream.ts:34,122-138`
- Modify: `frontend/components/cost-meter.tsx:69-71`

**Interfaces:**
- Produces: `CostUpdateEvent.priced?: boolean`; `costByModel[model].priced: boolean`.

- [ ] **Step 1: Add `priced` to the event type** in `lib/events.ts`:

```typescript
export interface CostUpdateEvent {
  type: "cost_update";
  model: string;
  input_tokens: number;
  output_tokens: number;
  cumulative_usd: number;
  priced?: boolean;
}
```

- [ ] **Step 2: Track `priced` in the reducer state** — `hooks/use-research-stream.ts`. Change the `costByModel` type (line 34):

```typescript
  costByModel: Record<
    string,
    { inputTokens: number; outputTokens: number; usd: number; priced: boolean }
  >;
```

Update the `cost_update` case (lines 122–138):

```typescript
    case "cost_update": {
      const prev = state.costByModel[event.model] ?? {
        inputTokens: 0,
        outputTokens: 0,
        usd: 0,
        priced: true,
      };
      const updated = {
        inputTokens: prev.inputTokens + event.input_tokens,
        outputTokens: prev.outputTokens + event.output_tokens,
        usd: event.cumulative_usd,
        priced: event.priced ?? true,
      };
      return {
        ...state,
        cumulativeCostUsd: event.cumulative_usd,
        costByModel: { ...state.costByModel, [event.model]: updated },
      };
    }
```

- [ ] **Step 3: Render "n/a" in the cost meter** — `components/cost-meter.tsx`, the per-model USD cell (lines 69–71):

```tsx
                  <td className="py-1.5 text-right font-mono text-[11px]">
                    {u.priced ? `$${u.usd.toFixed(4)}` : "n/a"}
                  </td>
```

- [ ] **Step 4: Verify build + lint**

Run: `cd frontend && npm run lint && npx tsc --noEmit`
Expected: PASS (no type errors; `priced` flows through).

- [ ] **Step 5: Commit**

```bash
cd frontend && git add -A
git commit -m "feat(cost-meter): show n/a for models without a known price"
```

---

## Task 9: Frontend — run-form provider fields + `X-Provider-Key`

Minimal, per-request (not stored) provider selector revealing `base_url`, `model`, and a key field for the OpenAI-compatible path.

**Files:**
- Modify: `frontend/lib/api.ts:75-88` (createResearch options + provider key header)
- Modify: `frontend/components/research-form.tsx`

**Interfaces:**
- Consumes: backend `create_research` provider contract (Task 7).
- Produces: `CreateResearchOptions` gains `provider?`, `baseUrl?`, `model?`, `providerKey?`; `createResearch` sends body fields + `X-Provider-Key` header when provider is openai.

- [ ] **Step 1: Extend `createResearch`** in `lib/api.ts`. Because `authedFetch` always sets `X-Anthropic-Key` from localStorage, pass the per-request provider key as an explicit header here:

```typescript
export interface CreateResearchOptions {
  depth?: Depth;
  browseWeb?: boolean;
  provider?: "anthropic" | "openai";
  baseUrl?: string;
  model?: string;
  providerKey?: string;
}

export async function createResearch(
  question: string,
  options: CreateResearchOptions = {},
): Promise<CreateResearchResponse> {
  const body: Record<string, unknown> = { question };
  if (options.depth) body.depth = options.depth;
  if (typeof options.browseWeb === "boolean") body.browse_web = options.browseWeb;
  if (options.provider) body.provider = options.provider;
  if (options.baseUrl) body.base_url = options.baseUrl;
  if (options.model) body.model = options.model;

  const headers: Record<string, string> =
    options.provider === "openai" && options.providerKey
      ? { "X-Provider-Key": options.providerKey }
      : {};
  return apiPost<CreateResearchResponse>("/api/research", body, headers);
}
```

Update `apiPost` to accept optional extra headers (merge after the JSON content-type):

```typescript
export async function apiPost<T>(
  path: string,
  body: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const res = await authedFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...extraHeaders },
    body: JSON.stringify(body),
  });
  return throwOrJson<T>(res);
}
```

- [ ] **Step 2: Add provider UI to `research-form.tsx`**

Add local state near the other `useState` hooks:

```tsx
  const [provider, setProvider] = useState<"anthropic" | "openai">("anthropic");
  const [baseUrl, setBaseUrl] = useState("https://api.openai.com/v1");
  const [providerModel, setProviderModel] = useState("");
  const [providerKey, setProviderKey] = useState("");
```

In `submit`, pass the provider options:

```tsx
      const { report_id } = await createResearch(trimmed, {
        depth,
        browseWeb,
        provider,
        ...(provider === "openai"
          ? { baseUrl, model: providerModel, providerKey }
          : {}),
      });
```

Add a compact provider control row inside the toolbar `<div className="flex gap-4">` (after the Browse Web button), and, when `provider === "openai"`, a small set of inputs below the textarea region. Keep styling consistent with the existing toolbar buttons (font-mono, muted-foreground). Minimal markup:

```tsx
            <button
              type="button"
              onClick={() => setProvider((p) => (p === "anthropic" ? "openai" : "anthropic"))}
              className="text-muted-foreground hover:text-foreground flex items-center gap-2 transition-colors"
              aria-label={`Provider: ${provider}`}
            >
              <span className="font-mono text-[10px] uppercase tracking-wider">
                Provider · {provider === "anthropic" ? "Anthropic" : "OpenAI-compat"}
              </span>
            </button>
```

Below the input card (after the closing toolbar div, still inside the form), render the OpenAI fields conditionally:

```tsx
      {provider === "openai" ? (
        <div className="mt-3 flex flex-col gap-2">
          <p className="text-muted-foreground/70 font-mono text-[10px] tracking-wider">
            Bring an Anthropic key for built-in web search (recommended). Other
            providers search via Tavily; quality scales with the model you bring.
          </p>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="Base URL (e.g. https://api.openai.com/v1)"
            className="bg-secondary text-foreground placeholder:text-muted-foreground/50 rounded-md px-3 py-2 font-mono text-xs outline-none"
          />
          <input
            value={providerModel}
            onChange={(e) => setProviderModel(e.target.value)}
            placeholder="Model (e.g. gpt-4o)"
            className="bg-secondary text-foreground placeholder:text-muted-foreground/50 rounded-md px-3 py-2 font-mono text-xs outline-none"
          />
          <input
            type="password"
            value={providerKey}
            onChange={(e) => setProviderKey(e.target.value)}
            placeholder="Provider API key (sent per request, not stored)"
            className="bg-secondary text-foreground placeholder:text-muted-foreground/50 rounded-md px-3 py-2 font-mono text-xs outline-none"
          />
        </div>
      ) : null}
```

Disable the submit button for an incomplete OpenAI config — extend the existing `disabled` expression:

```tsx
            disabled={
              !question.trim() ||
              submitting ||
              freeBlocked ||
              (provider === "openai" && (!baseUrl || !providerModel || !providerKey))
            }
```

- [ ] **Step 3: Verify build + lint**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm run build`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd frontend && git add -A
git commit -m "feat(run-form): per-request OpenAI-compatible provider fields"
```

---

## Final verification

- [ ] **Backend full gate:** `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src` → all green.
- [ ] **Frontend full gate:** `cd frontend && npm run lint && npx tsc --noEmit && npm run build` → all green.
- [ ] **Manual smoke (optional, needs keys):** set `TAVILY_API_KEY` in root `.env`; run a report via the form with Provider = OpenAI-compat, `base_url=https://api.openai.com/v1`, `model=gpt-4o`, a real OpenAI key → confirm researcher progress events appear and the cost meter shows USD (gpt-4o is priced). Then try `model=some/unknown` → cost meter shows "n/a".
- [ ] **Update `CLAUDE.md` resume notes:** mark Phase 2a DONE, point to this plan, note `TAVILY_API_KEY` is a new optional `.env` var, and that Phase 2b (encrypted key storage + settings UI + Tavily monthly cap) is next.

---

## Self-review notes (author)

- **Spec coverage:** A (CompletionResult + Protocol) → Task 1; B (AnthropicClient rename) → Task 1; C (OpenAICompatClient) → Task 3; D (search native vs Tavily) → Tasks 4–5; E (per-request config + factory + routing) → Tasks 6–7; F (pricing / n/a) → Tasks 2, 8; G (run form) → Task 9. Testing section → tests in each task. Risks (translation fidelity, usage reporting, Tavily quality) → covered by Task 3 translation tests + streaming usage-fallback + UI hint.
- **Type consistency:** `CompletionResult`/`ToolUse` field names are used identically across client.py, openai_client.py, researcher.py, and their tests. `build_client(overrides, *, on_api_call)`, `tavily_search(query, *, api_key, max_results)`, `model_is_priced(model)`, `CostUpdate.priced` / `costByModel[].priced` match across backend and frontend.
- **Deviations** flagged at top (server_tool_uses field; estimate_cost_usd kept float + model_is_priced) — confirm at plan approval.
