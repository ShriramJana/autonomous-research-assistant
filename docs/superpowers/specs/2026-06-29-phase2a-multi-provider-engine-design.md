# Phase 2a — Multi-Provider Engine (Backend) Design

> Design spec. Status: design approved by Shriram (2026-06-29); pending written-spec review.
> First half of Phase 2 (multi-provider BYOK). Phase 2b (encrypted per-user key storage +
> settings UI) is a separate, later spec/plan. Author: Claude Code session, 2026-06-29.

## Goal

Let the three-stage pipeline (planner → researchers → synthesizer) run on a **non-Anthropic,
OpenAI-compatible** provider (OpenRouter / OpenAI / Gemini-compat / Ollama) in addition to
the native Anthropic path — without adopting a generic abstraction layer. In 2a the provider
is chosen **per request** (extending the existing `X-Anthropic-Key` BYOK seam) and exercised
from a minimal run-form addition; 2b later moves credentials into stored per-user settings.

## Decisions captured during brainstorming

- **Provider structure:** an `LLMClient` **Protocol** with **two hand-written native clients** —
  `AnthropicClient` (today's code) and `OpenAICompatClient` (official `openai` SDK, configurable
  `base_url`). No LiteLLM, no LangChain — the "no abstraction layer" rule bans a generic shim,
  not a second concrete swap-point.
- **Search:** Anthropic uses its **native server-side web search** (best quality). Non-Anthropic
  uses **Tavily** (server-side Tavily key). The UI **recommends** bringing an Anthropic key for
  the built-in search.
- **Credentials in 2a:** **per-request** (headers for secrets, body for non-secret config).
  Persisting keys in Supabase is **2b**.
- **Cost meter:** always show token counts; show **$ only for models in the pricing table**
  (extended with common known models), else "cost n/a".
- **One model for BYOK:** a non-Anthropic BYOK run uses **one** user-chosen model for all three
  roles. The native Anthropic free-tier/BYOK path keeps its per-role models.

## Non-goals (deferred to 2b or out of scope)

- Encrypted per-user key storage in Supabase + the settings UI (2b).
- A global monthly **Tavily quota** accounting cap (needs the same persistent usage accounting
  as the free-tier USD cap — lands with 2b's storage work). 2a bounds search per-run via the
  existing `max_iterations` only.
- User-supplied Tavily keys (server provides Tavily in 2a).
- No change to the planner/synthesizer prompts, the SSE contract, depth presets, or free-tier
  behavior beyond what provider routing requires.

---

## Architecture

### A. The `LLMClient` Protocol and normalized results

Today `LLMClient` is a concrete class returning Anthropic's `Message`; agents read
`response.content` / `.stop_reason` / `.usage`. To support two providers cleanly, decouple the
agents from Anthropic's SDK types by normalizing the **return value** (the input message/tool
shapes stay in the current Anthropic-ish dict form; `OpenAICompatClient` translates them).

New normalized types (in `llm/`):

```python
@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]

@dataclass(frozen=True)
class CompletionResult:
    text: str                 # concatenated assistant text (may be "")
    tool_uses: list[ToolUse]  # client-side tool calls the model requested
    stop_reason: str
    input_tokens: int
    output_tokens: int
```

`LLMClient` Protocol (structural — both clients satisfy it):

```python
class LLMClient(Protocol):
    provider: str                       # "anthropic" | "openai"
    supports_server_side_search: bool   # True only for AnthropicClient

    async def complete_with_tools(self, *, model, messages, tools=None,
                                  tool_choice=None, system=None,
                                  max_tokens=4096) -> CompletionResult: ...
    async def stream_completion(self, *, model, messages, system=None,
                                max_tokens=4096) -> AsyncIterator[str]: ...
    # stream_completion_with_tools stays Anthropic-only (v2, unused by v1 call sites);
    # the Protocol may omit it, or AnthropicClient keeps it as an extra.
```

- `extract_tool_use(result, name)` is updated to read `CompletionResult.tool_uses` (was reading
  the Anthropic `Message`). This is the single change that ripples to planner + researcher.
- `messages` stay normalized dicts. Plain text turns are `{"role": "user", "content": str}`.
  The non-Anthropic researcher loop additionally uses assistant-tool-call and tool-result turns
  (a small normalized block shape); `OpenAICompatClient` maps those to OpenAI `tool_calls` /
  `role:"tool"` messages, and `AnthropicClient` maps them to Anthropic `tool_use`/`tool_result`
  content blocks. Exact block schema is pinned in the plan.
- Tool specs remain authored in the existing Anthropic-ish shape
  (`{"name","description","input_schema"}`); `OpenAICompatClient` converts each to OpenAI's
  `{"type":"function","function":{"name","description","parameters"}}` internally. `tool_choice`
  is likewise translated.

### B. `AnthropicClient` (rename of today's class)

The current `LLMClient` class becomes `AnthropicClient` implementing the Protocol:
`provider="anthropic"`, `supports_server_side_search=True`, `web_search_tool_spec(...)` retained.
`complete_with_tools` now returns a `CompletionResult` (assembled from the Anthropic `Message` —
text blocks joined, `tool_use` blocks → `ToolUse`, usage + stop_reason copied). `stream_completion`
unchanged. Behavior is otherwise identical, so the native path is untouched in spirit.

### C. `OpenAICompatClient` (new)

Uses `openai.AsyncOpenAI(api_key=..., base_url=...)`. Implements the Protocol:
`provider="openai"`, `supports_server_side_search=False`.

- `complete_with_tools`: translate normalized messages + Anthropic-shape tools → OpenAI
  `chat.completions.create(...)`; read back assistant text + `tool_calls` → `CompletionResult`
  (parse each tool call's JSON arguments into `ToolUse.input`); map `finish_reason` → `stop_reason`;
  copy `usage.prompt_tokens`/`completion_tokens`.
- `stream_completion`: stream `chat.completions.create(stream=True)` text deltas; recover usage
  from the final chunk (request `stream_options={"include_usage": True}` where supported, else
  fall back to a token estimate so `_record` still fires).
- Both call the same `_record(model, in, out)` cost hook.

### D. Search: native vs Tavily

- **`web_search_enabled=False`** → unchanged offline path for both providers.
- **Anthropic + search on** → unchanged single-call **server-side** web search (the researcher's
  current path), gated on `llm.supports_server_side_search`.
- **Non-Anthropic + search on** → a **client-side Tavily loop** in the researcher:
  1. Tools offered: a client-side `web_search` function (`{"query": str}`) + `submit_finding`.
  2. Loop up to `max_iterations`: call `complete_with_tools`; for each `web_search` `ToolUse`,
     run `tavily_search(query)`, emit a `ResearcherProgress`, append the assistant tool call and
     a tool-result message with the results, and continue.
  3. When the model calls `submit_finding` (or `max_iterations` is hit), build the finding with
     the existing `_build_finding`. If it never calls `submit_finding`, raise `ResearcherError`
     (same degraded-finding handling as today).
- New `llm/search.py` (or `tools/tavily.py`): `async def tavily_search(query, *, api_key,
  max_results=5) -> list[SearchResult]` — a thin `httpx` POST to Tavily, returning
  `{title, url, content}` rows formatted into the tool-result text. Failures degrade gracefully
  (return an empty/error result so the loop can continue, consistent with "partial failure is
  expected").
- The researcher chooses its strategy from `llm.supports_server_side_search` (capability flag) —
  **no `isinstance`**. The dispatch is the only structural change to `researcher.py`; the
  server-side branch is the current code verbatim.

### E. Per-request provider config + routing

- `RuntimeOverrides` gains `provider: Literal["anthropic","openai"] = "anthropic"` and
  `base_url: str | None = None` (back-compatible; existing fields unchanged). For a non-Anthropic
  BYOK run the three `*_model` fields are all set to the single user model.
- A small **client factory** (`llm/factory.py`): `build_client(overrides, *, on_api_call) ->
  LLMClient` returns `AnthropicClient` or `OpenAICompatClient(base_url=...)`. The orchestrator
  uses it instead of constructing `AnthropicClient` directly.
- `create_research` (API): non-secret provider config (`provider`, `base_url`, `model`) arrives
  in the request body; the **secret key** arrives via header (reuse `X-Anthropic-Key` for
  Anthropic; add `X-Provider-Key` for the OpenAI-compatible path). `used_byok` already exists.
  Validation: `openai` provider requires `base_url` + `model` + key; reject with a clear 4xx
  otherwise. The free-tier path is untouched.

### F. Cost / pricing

- Extend `pricing.py` with common known models (OpenAI GPT family, a few popular OpenRouter
  slugs). The estimator returns a known $/MTok or **None** for unrecognized models.
- The `cost_update` event keeps carrying `model` + token counts. When a model is unpriced its
  USD contribution is treated as unknown: `cumulative_usd` sums only priced models, and the
  per-model breakdown marks the unpriced ones so the UI shows **tokens + "cost n/a"** rather than
  a misleading $0. (Frontend cost meter already keys off `costByModel`; it gains an "n/a" render
  for entries with no price. Exact event/field shape pinned in the plan — preferred: a `priced:
  bool` or nullable `usd` per model.)

### G. Minimal frontend (run form)

- The run form gains an optional **provider** selector (Anthropic | OpenAI-compatible) revealing
  `base_url`, `model`, and a key field when non-Anthropic; sent **per request, not stored**.
- Copy/hint: *"Bring an Anthropic key for built-in web search (recommended). Other providers
  search via Tavily; quality scales with the model you bring."*
- The existing Anthropic `X-Anthropic-Key` flow is unchanged. 2b replaces typing-each-run with
  saved settings, reusing this exact per-request request shape.

## Data flow

```
run form ─(provider, base_url, model in body; key in header)→ create_research
         → RuntimeOverrides(provider, base_url, model[, api_key]) → build_client()
            ├─ anthropic → AnthropicClient (server-side web search)
            └─ openai    → OpenAICompatClient(base_url) + researcher Tavily loop
         → orchestrator → planner / researchers / synthesizer (unchanged prompts)
         → SSE events (same contract) → existing UI + cost meter (n/a for unpriced models)
```

## Error handling

- Provider/auth errors surface as the run's terminal `error` event (existing path), with a clear
  message (bad key / unreachable `base_url` / model not found).
- Tavily failure on a single search degrades that search (empty result), not the run.
- A non-Anthropic researcher that never calls `submit_finding` → `ResearcherError` → degraded
  finding + `ErrorEvent` (existing behavior).
- Missing/invalid provider config → 4xx before the run starts.

## Testing

- `AnthropicClient`: existing tests adapted to the `CompletionResult` return (behavior parity).
- `OpenAICompatClient`: unit tests with a mocked `AsyncOpenAI` — message/tool translation,
  `tool_calls` → `ToolUse`, usage/stop_reason mapping, streaming text + usage recovery.
- `tavily_search`: unit test with a mocked `httpx` client (result formatting, failure → empty).
- Researcher Tavily loop: test with a fake `LLMClient` that scripts `web_search` then
  `submit_finding`, asserting the loop calls search, feeds results back, respects `max_iterations`,
  emits `ResearcherProgress`, and builds the finding (and the no-`submit_finding` failure path).
- `build_client` factory: returns the right client per `provider`; validation rejects incomplete
  OpenAI config.
- `pricing`: known model → $, unknown → None; cost meter renders "n/a".
- SSE contract tests stay green (no event/order changes).

## Risks

- **Message/tool translation fidelity** (Anthropic blocks ↔ OpenAI tool_calls) is the main risk;
  covered by focused translation unit tests on `OpenAICompatClient`.
- **OpenAI-compat usage reporting varies** (some `base_url`s omit token usage in streaming);
  mitigated by `include_usage` where available and a token-estimate fallback so cost/record still
  fires.
- **Tavily result quality** is lower than Anthropic's native search; this is acknowledged in the
  UI recommendation, not a code problem.

## Execution

Implementation plan via writing-plans → subagent-driven-development (TDD, commit per stage), same
as Phases 1 / 1.5.
