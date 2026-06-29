# CLAUDE.md — working notes for Claude Code sessions on this repo

## Project

**Autonomous Research Assistant (ARA) v1.** Flagship portfolio project for **LLMTechno** (AI consulting).
Three-stage agent pipeline — Planner → Researchers (parallel) → Synthesizer — with live SSE streaming to a Next.js UI. Details in [ARCHITECTURE.md](ARCHITECTURE.md) (written at the end of v1).

## Current status — RESUME HERE (updated 2026-06-29)

v1 core pipeline is ~95% complete (planner/researcher/synthesizer, SSE, Supabase storage, auth, free-tier quota, polished Next.js UI). **Phase 1, 1.5, 2a, AND 2b are DONE on `dev`** — next up is **Phase 3 (deploy)**: frontend → Vercel, backend host TBD, + portfolio post.

- **✅ Phase 2b — DONE (on `dev`, final review clean):** [spec](docs/superpowers/specs/2026-06-29-phase2b-persisted-byok-tavily-cap-design.md) · [plan](docs/superpowers/plans/2026-06-29-phase2b-persisted-byok-tavily-cap.md). Encrypted per-user credential storage (Fernet, `ara/crypto.py`) in a new `user_credentials` table (**migration `backend/migrations/002_credentials.sql` — MUST be applied to Supabase**); `ara/credentials.py` store; pure `runtime/resolver.py resolve_overrides` maps the user's **single active provider** (`free`|`anthropic`|`openai`) → the 2a `RuntimeOverrides`. **Saved-only**: keys live in Settings (write-only, never returned), `create_research` resolves from storage — the 2a `X-Anthropic-Key`/`X-Provider-Key` headers and body `provider`/`base_url`/`model` fields are **REMOVED**; run form has no key fields; localStorage `api-key.ts` retired. Global monthly **Tavily cap** (`reports.tavily_searches` counted per run via `on_tavily_search`, summed in `check_tavily_cap`; OpenAI+search runs **degrade to offline** when reached, surfaced on `/api/quota`). **NEW env vars (root `.env`): `ARA_ENCRYPTION_KEY`** (Fernet key — required for credential storage; unset → endpoints 503; generate via `uv run python -c "from ara.crypto import generate_key; print(generate_key())"`) and **`TAVILY_GLOBAL_MONTHLY_CAP`** (default 1000). Decrypt failure → 400 "re-save". Many store/endpoint tests are **DB-gated** (`requires_db`, skip without `SUPABASE_DB_URL`) — prove them with a manual smoke test. Deferred minors in `.superpowers/sdd/progress.md` (Phase 2b section), all non-blocking.

- **✅ Phase 2a — DONE (on `dev`, final review clean — review-clean, not yet pushed):** [spec](docs/superpowers/specs/2026-06-29-phase2a-multi-provider-engine-design.md) · [plan](docs/superpowers/plans/2026-06-29-phase2a-multi-provider-engine.md). `LLMClient` **Protocol** + concrete `AnthropicClient` (rename) & `OpenAICompatClient` (official `openai` SDK, `base_url`); normalized `CompletionResult` (with extra `server_tool_uses` for Anthropic server-side search progress) so agents no longer touch the Anthropic `Message`; **client-side Tavily loop** in the researcher for non-Anthropic, dispatched on `llm.supports_server_side_search` (NO isinstance); `build_client` factory (note: circular import w/ `runtime/__init__`→orchestrator solved via `TYPE_CHECKING` + deferred annotations); per-request provider config (`provider`/`base_url`/`model` in body, key via **`X-Provider-Key`** header; `X-Anthropic-Key` path unchanged); `pricing.py` extended + `model_is_priced` + `CostUpdate.priced` → cost meter shows tokens always, "$" when priced else **"n/a"**; minimal run-form provider fields (per-request, not stored). **NEW optional env var: `TAVILY_API_KEY`** (root `.env`) — required server-side for non-Anthropic web search; if unset, Tavily returns `[]` and findings degrade to model-knowledge-only (intentional). One model drives all 3 roles for non-Anthropic BYOK. Deferred minors live in `.superpowers/sdd/progress.md` (Phase 2a section) — all non-blocking.

- **✅ Phase 1.5 — DONE:** [spec](docs/superpowers/specs/2026-06-29-phase1.5-richer-demo-gallery-design.md) · [plan](docs/superpowers/plans/2026-06-29-phase1.5-richer-demo-gallery.md). Vertical `ResearchTimeline` (pure `lib/timeline.ts deriveStages`, retired PlanTree, shows on live runs too); `lib/replay.ts computeReplaySchedule` (scale-to-~20s + per-stage dwell + readable synthesis cadence); enriched manifest (`build_manifest` derives summary/sources/sub-queries/cost) + `DemoCard`; 3 committed real recordings (`quantum-supremacy`, `financial-crisis-2008`, `transformer-models`). **Note:** `.env` synthesizer model set to `claude-sonnet-4-5` (all three roles Sonnet) to keep recording cost down; each real `record_run.py` capture is ~$0.55. mRNA-vaccines topic dropped — its manufacturing sub-query reliably returns `stop_reason='refusal'`.

- **Spec (all 3 phases):** [docs/superpowers/specs/2026-06-28-ship-ara-v1-demo-byok-deploy-design.md](docs/superpowers/specs/2026-06-28-ship-ara-v1-demo-byok-deploy-design.md)
- **✅ Phase 1 — DONE:** [docs/superpowers/plans/2026-06-28-phase1-client-side-demo-gallery.md](docs/superpowers/plans/2026-06-28-phase1-client-side-demo-gallery.md). Free, credit-free demo: record real runs to static JSON in `frontend/public/demos/`, replay 100% client-side via `useReplayFromJson` (drives the live reducer over a timer), public gallery + `/demo/[slug]` route. Recorder: `backend/scripts/record_run.py "Q" --slug s --title T`. Committed fixture `sample-quantum.json`. Final review: ready to merge. **Deferred (recorded in `.superpowers/sdd/progress.md`):** 4 Minor findings (guard recorder write on `status=="completed"`; add a recorder↔frontend JSON contract test; demo-banner copy nuance re free Supabase auth calls; vitest devDep ordering), the first real `record_run.py` capture (needs `ANTHROPIC_API_KEY`), and in-browser visual confirmation of the animation.
- **Phase 2 — both halves DONE (2a + 2b, above).**
- **▶ Phase 3 — DO THIS NEXT (not yet specced/brainstormed):** Deploy live — frontend → Vercel; backend host TBD; set prod env vars (`ANTHROPIC_API_KEY`, `SUPABASE_*`, `TAVILY_API_KEY`, `ARA_ENCRYPTION_KEY`, `TAVILY_GLOBAL_MONTHLY_CAP`); apply migrations 001 + 002 to the live Supabase; + portfolio post linking GitHub + live URL. **RESUME: `superpowers:brainstorming` → `writing-plans` → `subagent-driven-development`.**

Phase 3 needs brainstorming → writing-plans. Execute with **superpowers:subagent-driven-development** (or executing-plans).

Permissions: `.claude/settings.local.json` (gitignored) is set to `bypassPermissions` — no prompts.

## Ground rules

- **Conventional Commits**, clear scope (`feat(models):`, `fix(api):`, `chore(dev):`). **No `Co-Authored-By:` lines.**
- **Propose-then-approve** for non-trivial decisions (file tree, schemas, interfaces). When Shriram says "stop and show me X before Y", stop, show X, wait — do not pre-emptively do Y.
- **Commit per stage.** Makes granular reverts cheap.
- **Trust the test + type gates**: `mypy --strict` and `ruff` are expected to pass on every commit. Don't push through failures.

## Stack (non-negotiable)

| Layer | Choice |
| --- | --- |
| Backend | Python 3.11+, FastAPI, async throughout, Pydantic v2, LangGraph |
| LLM | **Anthropic + OpenAI SDKs directly** behind an `LLMClient` **Protocol** (`AnthropicClient`, `OpenAICompatClient`) — still no LangChain, no LiteLLM, no generic shim (Phase 2a) |
| Models | `CLAUDE_PLANNER_MODEL` / `CLAUDE_RESEARCHER_MODEL` / `CLAUDE_SYNTHESIZER_MODEL` (env-driven, Anthropic path); non-Anthropic BYOK uses one per-request model for all 3 roles |
| Web search | Anthropic server-side `web_search_20250305`; non-Anthropic uses a client-side **Tavily** loop (`TAVILY_API_KEY`), dispatched on `llm.supports_server_side_search` |
| Packaging | `uv` + `pyproject.toml` (NOT pip/requirements.txt) |
| Frontend | Next.js 15 App Router, TypeScript strict, Tailwind v4, **shadcn/ui** (no hand-rolled styling) |
| Persistence | In-memory v1 behind a `ReportStore` Protocol — v2 swap point |

## v1 scope — intentionally OUT

Do **not** add any of these without an explicit request:

- User auth / multi-tenancy
- Database persistence (in-memory dict for v1)
- PDF export
- Slack / email integrations
- Rate-limiting middleware
- Redis, Celery, or any external broker
- LangChain (LangGraph only, for the DAG)

## Where things live

```
backend/
  src/ara/
    models/      — Pydantic domain + SSE event envelopes
    llm/         — Thin async Anthropic wrapper (single swap-point)
    agents/      — planner / researcher / synthesizer
    graph/       — LangGraph DAG + state TypedDict
    storage/     — ReportStore Protocol + in-memory impl (ring buffer)
    runtime/     — orchestrator (run_report end-to-end)
    api/         — FastAPI routes + SSE endpoint
    pricing.py   — $/MTok table + cost estimator (edit when prices change)
    config.py    — Settings (pydantic-settings)
    main.py      — FastAPI app factory
  tests/         — pytest; one file per module; test_sse_contract.py guards ordering invariants
  scripts/       — dev tooling (run_planner.py for manual planner eval)
frontend/        — Next.js 15, shadcn, TypeScript strict
```

## Streaming contract (SSE)

Events: `plan_ready`, `researcher_started`, `researcher_progress`, `researcher_complete`,
`synthesis_token`, `report_complete`, `error`, `cost_update`.

Invariants asserted in [backend/tests/test_sse_contract.py](backend/tests/test_sse_contract.py):
- `plan_ready` precedes every `researcher_started`
- Every `researcher_started` has a matching `researcher_complete` (same `sub_query_id`)
- `synthesis_token`s arrive only after all researchers complete
- `report_complete` is terminal
- `cost_update.cumulative_usd` is monotonically non-decreasing
- Every event round-trips through the discriminated-union `ResearchEventAdapter`

## Key design choices worth knowing

- **Citations by stable UUID, never by list index.** `Source.id: UUID`; `KeyFact.citation_ids` / `ReportSection.citation_ids` are `list[UUID]`. The synthesizer dedups sources across findings by URL, so any index-based scheme would break.
- **Partial researcher failure is expected.** When one researcher raises `ResearcherError`, the orchestrator emits an `ErrorEvent` and a **degraded** `SubQueryFinding` (`summary="Research failed: …"`, empty facts/sources). Synthesizer still runs and acknowledges the gap in the report.
- **Researcher guardrails**: max 5 server-side `web_search` uses + 100k input-token budget per researcher. Breaches raise `ResearcherError`.
- **Ring buffer on the store**: 50 events per report, so a client reconnecting mid-stream replays the tail before picking up live events.
- **LangGraph sees a 3-node chain; the researcher fan-out lives INSIDE `research_node`** via `asyncio.gather`. This is the single non-obvious piece — documented in ARCHITECTURE.md.

## Development

```bash
make install        # backend deps via uv
make test           # pytest
make lint           # ruff + mypy --strict
make dev-backend    # uvicorn on :8000
make dev-frontend   # next dev on :3000

# Live planner eval (needs ANTHROPIC_API_KEY in .env at repo root):
cd backend && uv run python scripts/run_planner.py "your question here"
```

## Config location note

`.env` lives at **repo root** (not one level up). `backend/src/ara/config.py` uses
`env_file=("../.env", ".env")` so both the root and `backend/` work for dev.
