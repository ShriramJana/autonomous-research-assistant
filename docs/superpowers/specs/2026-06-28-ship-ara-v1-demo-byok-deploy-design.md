# Ship ARA v1: Free Demo + Multi-Provider BYOK + Live Deploy — Design

**Date:** 2026-06-28
**Status:** Approved for planning
**Author:** Shriram (with Claude Code)

## Context

The Autonomous Research Assistant (ARA) is ~95% feature-complete: the full
Planner → parallel Researchers → Synthesizer pipeline is wired end-to-end with
live SSE streaming, Supabase persistence, auth, free-tier quota, 60 tests, and a
polished Next.js 15 / shadcn frontend. Backend `sample replay` and `gallery`
already exist (replay saved events from Supabase at 80ms cadence, zero LLM cost).

Three gaps remain before this is portfolio-ready:

1. **No live, credit-free demo that survives a cold/asleep backend.** Today's
   replay streams *through* the FastAPI backend, so a free-tier backend
   cold-start would make the demo lag.
2. **BYOK is Anthropic-only.** The goal is for recruiters/visitors to plug in
   *any* LLM provider's API key and get results.
3. **Nothing is deployed.** No `vercel.json`, no chosen backend host, no
   portfolio entry.

This spec covers all three as **three independently shippable phases**, sequenced
so the free demo (highest value, lowest effort) ships first.

## Goals

- A recruiter with **no key** sees the entire research process replay instantly,
  client-side, with **zero backend dependency and zero cost**.
- A recruiter with **their own key (any provider)** can run a live query, picking
  whatever model they want, with a clear hint that quality scales with the
  model/key they bring.
- The app is **live on a free host**, linked from the portfolio alongside GitHub.

## Non-Goals (this effort)

- Per-stage model selection (one model for all three stages; per-stage is v2).
- PDF export, Slack/email, rate-limiting middleware (remain out per CLAUDE.md).
- Replacing the backend-based gallery/replay used by *authenticated* users for
  their own history — that stays as-is. Only the **public** demo goes static.
- A third-party LLM abstraction layer (LiteLLM/LangChain). We write our own thin
  adapter beside the existing Anthropic client, per CLAUDE.md.

---

## Phase 1 — Free client-side demo gallery

**Outcome:** public landing shows a gallery of finished sample reports; clicking
one replays the *entire* process (plan tree building, parallel researchers,
streaming synthesis, cost meter) entirely in the browser from static JSON. No
backend calls. Works even if the backend is deleted.

### Components

1. **`backend/scripts/record_run.py`** (new dev tool)
   - Runs `run_report()` for a given question using the local `ANTHROPIC_API_KEY`
     (one-time cost, a few cents per run).
   - Captures the ordered list of SSE events as they are emitted.
   - Serializes to `frontend/public/demos/<slug>.json` (array of event objects in
     the same wire shape the frontend already parses) and updates
     `frontend/public/demos/manifest.json` (list of `{slug, title, question,
     created_at, model, n_sources, summary}`).
   - Re-uses the existing `ResearchEventAdapter` serialization so recorded events
     are byte-compatible with the live wire format.

2. **`frontend/src/hooks/use-replay-from-json.ts`** (new)
   - Mirrors the public interface of `use-research-stream.ts` (same derived
     status enum, same accumulated state), but the source is a static JSON array
     fetched from `/demos/<slug>.json`.
   - Replays events using their relative timestamps (or a fixed inter-event delay
     matching the backend's 80ms if timestamps are absent), so the visual cadence
     matches a live run. Supports a "skip to end" / "replay" control.

3. **Public gallery repoint**
   - The unauthenticated landing gallery (`gallery-snapshot.tsx` /
     `gallery/page.tsx`) reads `manifest.json` statically instead of calling
     `GET /api/gallery`.
   - Clicking a card routes to a replay view driven by `use-replay-from-json`,
     reusing `research-live`, `plan-tree`, `report-stream`, `citation`,
     `cost-meter` unchanged.

### Data flow

```
record_run.py (one-time, local) ──> public/demos/*.json + manifest.json
                                          │ (committed to git, shipped with app)
                                          ▼
visitor ──> landing gallery (reads manifest) ──> click card
        ──> use-replay-from-json (fetch static JSON) ──> existing UI components
        (no backend, no LLM, $0)
```

### Testing

- Frontend unit test: `use-replay-from-json` emits events in order and reaches a
  terminal `report_complete` state from a fixture JSON.
- A committed fixture `demos/manifest.json` + at least one `<slug>.json` so the
  gallery renders in CI without recording.
- Manual: run `record_run.py` for 3–4 questions, verify replay matches a live run
  visually.

---

## Phase 2 — Multi-provider BYOK

**Outcome:** a visitor pastes their own API key for any provider, picks any model,
and runs a live query. Anthropic keys keep the premium native-web-search path;
all other providers route through an OpenAI-compatible path with provider-neutral
web search.

### Architecture

Introduce an `LLMProvider` Protocol that the three agents depend on (they
currently call `complete_with_tools`, `stream_completion`,
`stream_completion_with_tools`). Two implementations:

- **`AnthropicClient`** — existing `llm/client.py`, unchanged behavior.
  Uses server-side `web_search_20250305`.
- **`OpenAICompatClient`** (new, `llm/openai_compat.py`) — uses the `openai` SDK
  with a configurable `base_url`. One integration covers OpenRouter (one key →
  hundreds of models incl. Claude/GPT/Gemini/Llama), OpenAI, Groq, Together,
  Gemini's OpenAI-compat endpoint, and local Ollama.
  - Web search: a new backend-executed **provider-neutral search tool**
    (`llm/web_search_tavily.py`, Tavily free tier) exposed to the model as a
    function/tool. The backend runs the search and feeds results back; the model
    reasons over them and cites. Subject to the same researcher guardrails
    (max 5 searches, 100k input-token budget).

A small factory (`llm/factory.py`) builds the right provider from per-request
overrides.

### Tool-calling compatibility (main risk)

Planner (`submit_research_plan`) and Researcher (`submit_finding`) rely on forced
tool use. The OpenAI-compat path uses OpenAI-style function calling. For models
with weak/no tool support, fall back to **JSON-in-prompt + parse** (instruct the
model to emit a JSON object matching the schema; validate with the existing
Pydantic models; retry once on parse failure). This is the area most likely to
need iteration during implementation.

### Request flow & config

- Extend `runtime/overrides.py` to carry: `provider` (`anthropic` |
  `openai_compat`), `base_url` (optional; default OpenRouter), `api_key`,
  `model`.
- Headers: keep `X-Anthropic-Key` for back-compat; add `X-LLM-Provider`,
  `X-LLM-Base-URL`, `X-LLM-Key`, `X-LLM-Model`. `api/routes.py` builds overrides
  from these and selects the provider via the factory.
- `runtime/orchestrator.py` receives the provider instance instead of always
  constructing `AnthropicClient`.

### Frontend (settings + run)

- `settings/page.tsx` + `lib/api-key.ts`: provider dropdown
  (Anthropic / OpenAI-compatible), optional `base_url` (default OpenRouter,
  with a helper note), API key, and **one model field** (free text, e.g.
  `anthropic/claude-opus-4-5` or `openai/gpt-4o`). Stored in localStorage.
- A clear, friendly hint near the model field: **"Output quality depends on the
  model you choose — stronger models produce noticeably better research. You can
  use any model your key supports."**
- `lib/api.ts`: `authedFetch` sends the new headers when a BYOK config exists.

### Cost meter

`pricing.py` is Anthropic-only. For BYOK runs:
- Known models (present in the pricing table): show USD as today.
- Unknown models: show token counts and display cost as **"n/a (BYOK)"** rather
  than guessing. Add a few common OpenRouter/OpenAI prices best-effort.

### Testing

- Unit: `OpenAICompatClient` against a mocked OpenAI-compatible server for both
  the function-calling path and the JSON-fallback path.
- Unit: Tavily search tool wrapper (mocked HTTP), incl. guardrail enforcement.
- Unit: `factory` selects the correct provider from overrides; `routes` parse the
  new headers correctly.
- Contract: `test_sse_contract.py` invariants must still hold for an
  OpenAI-compat run (use a mocked provider).

---

## Phase 3 — Deploy live + portfolio

**Outcome:** the app runs on a free host with a public URL, linked from the
portfolio next to the GitHub repo.

### Components

- **Frontend → Vercel**: `vercel.json`, `NEXT_PUBLIC_*` env (API base URL,
  Supabase), build settings. The static demo lives here, so it is always instant.
- **Backend host (chosen at this step)**: FastAPI on a free tier (Render or Fly).
  Cold-start affects **only** live BYOK runs, not the demo. Add a "warming up…"
  state in the run UI for the first request.
- **Env wiring**: `TAVILY_API_KEY`, `ANTHROPIC_API_KEY` (free-tier/demo
  recording), Supabase URLs, free-tier caps, CORS allowed origins → the Vercel
  domain. Update `.env.example` and README.
- **Portfolio**: README polish + a recorded GIF of a demo replay; a portfolio
  entry linking GitHub + the live URL.

### Testing / verification

- Verify the deployed demo gallery replays with the backend stopped.
- Verify a live BYOK run end-to-end against the deployed backend (one Anthropic,
  one OpenRouter key).
- Verify CORS + SSE work across the Vercel ↔ backend origin boundary.

---

## Sequencing & rollback

Phases are independent and each ends at a committable, shippable state:

1. **Phase 1** can ship and be demoed before Phase 2 exists.
2. **Phase 2** is additive — Anthropic path is untouched; OpenAI-compat is new
   code behind the factory.
3. **Phase 3** is config/ops.

Commit per stage (per CLAUDE.md) for cheap granular reverts. `mypy --strict` and
`ruff` must pass on every backend commit; the SSE contract test must stay green.

## Open questions (resolve during implementation)

- Exact backend host (Render vs Fly) — decided at Phase 3 start.
- Default `base_url` value and the set of models pre-listed as suggestions in the
  settings UI.
- Whether recorded demo JSON stores absolute timestamps or relies on a fixed
  replay cadence.
