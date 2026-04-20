# CLAUDE.md — working notes for Claude Code sessions on this repo

## Project

**Autonomous Research Assistant (ARA) v1.** Flagship portfolio project for **LLMTechno** (AI consulting).
Three-stage agent pipeline — Planner → Researchers (parallel) → Synthesizer — with live SSE streaming to a Next.js UI. Details in [ARCHITECTURE.md](ARCHITECTURE.md) (written at the end of v1).

## Ground rules

- **Conventional Commits**, clear scope (`feat(models):`, `fix(api):`, `chore(dev):`). **No `Co-Authored-By:` lines.**
- **Propose-then-approve** for non-trivial decisions (file tree, schemas, interfaces). When Shriram says "stop and show me X before Y", stop, show X, wait — do not pre-emptively do Y.
- **Commit per stage.** Makes granular reverts cheap.
- **Trust the test + type gates**: `mypy --strict` and `ruff` are expected to pass on every commit. Don't push through failures.

## Stack (non-negotiable)

| Layer | Choice |
| --- | --- |
| Backend | Python 3.11+, FastAPI, async throughout, Pydantic v2, LangGraph |
| LLM | **Anthropic SDK directly** — no LangChain, no LiteLLM, no abstraction layer |
| Models | `CLAUDE_PLANNER_MODEL` / `CLAUDE_RESEARCHER_MODEL` / `CLAUDE_SYNTHESIZER_MODEL` (env-driven) |
| Web search | Anthropic server-side tool `web_search_20250305` |
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
