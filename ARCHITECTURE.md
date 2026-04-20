# Architecture

## One-screen summary

```
┌────────────────┐  POST /api/research              ┌───────────────────┐
│   Browser UI   │ ────────────────────────────────▶│  FastAPI (main)   │
│ (Next.js 15)   │                                  │                   │
│                │  GET /api/research/{id}/stream   │  app.state.store  │
│                │ ◀─ SSE ──────────────────────────│  (InMemoryReport  │
└────────────────┘                                  │    Store)         │
        ▲                                           └──────┬────────────┘
        │                                                  │ asyncio.create_task
        │                                                  ▼
        │                                           ┌───────────────────┐
        │                                           │ runtime/run_report│
        │       per-report ring buffer (50 events)  │                   │
        │◀──────────────────────────────────────────│  compiles graph:  │
                                                    │  ┌─────────────┐  │
                                                    │  │ plan_node   │  │
                                                    │  └──────┬──────┘  │
                                                    │         ▼         │
                                                    │  ┌─────────────┐  │
                                                    │  │research_node│  │
                                                    │  │ (asyncio.   │  │
                                                    │  │  gather ×N) │  │
                                                    │  └──────┬──────┘  │
                                                    │         ▼         │
                                                    │  ┌─────────────┐  │
                                                    │  │synthesize_  │  │
                                                    │  │   node      │  │
                                                    │  └─────────────┘  │
                                                    └───────┬───────────┘
                                                            │ emit(ResearchEvent)
                                                            ▼
                                            (writes to ring buffer + live queues)

     every LLM call ──▶ LLMClient ──▶ Anthropic ──▶ on_api_call hook ──▶
                                                  emits CostUpdate event
```

## Three stages

### 1. Planner (`agents/planner.py`)

- Input: the user's research question (string).
- Output: `ResearchPlan` with 3–7 `SubQuery` objects (`question`, `rationale`, `priority`).
- Implementation: single Anthropic call to `CLAUDE_PLANNER_MODEL` with a **forced tool-use** pattern — `tool_choice={"type": "tool", "name": "submit_research_plan"}` guarantees structured output. The tool's JSON Schema encodes the 3–7 bound and the priority enum; invalid output raises `PlannerError`.

### 2. Researchers (`agents/researcher.py`)

- Input: one `SubQuery`.
- Output: one `SubQueryFinding` (`summary`, `key_facts[]` each with citations, `sources[]`).
- Implementation: **single Anthropic call per researcher** that combines two tools:
  - `web_search_20250305` (server-side, up to 5 uses per call).
  - `submit_finding` (client-side, for structured output).
  The model performs its web searches server-side, reads results, then calls `submit_finding` with the structured finding. We parse the result, assign stable UUIDs to each `Source`, and rewrite the model's URL-based citations into `citation_ids: list[UUID]`.
- Guardrails: `max_iterations` (default 5) + `input_token_budget` (default 100k). Budget overruns raise `ResearcherError`.
- Parallelism: `asyncio.gather` across all sub-queries inside `research_node` (see "The one non-obvious thing" below).

### 3. Synthesizer (`agents/synthesizer.py`)

- Input: original question + all findings (including any degraded ones).
- Output: `FinalReport` with `executive_summary`, `sections[]`, master `citations[]`.
- Implementation: **streaming** Anthropic call to `CLAUDE_SYNTHESIZER_MODEL`. Tokens emit as `SynthesisToken` events live; the accumulated markdown is parsed into the structured `FinalReport` after the stream ends.
- Source dedup: sources from all findings are URL-deduped into a master list **before** the call; the model sees them as a numbered list and writes `[n]` inline. The parser translates `[n]` back into stable `Source.id` UUIDs.

## The streaming protocol

All events flow over SSE from `GET /api/research/{id}/stream`. Each event is a JSON-serialized member of a Pydantic discriminated union (`ResearchEvent`) validated by `ResearchEventAdapter`.

| Event | Fires when | Payload |
| --- | --- | --- |
| `plan_ready` | After the planner returns | `{ plan: ResearchPlan }` |
| `researcher_started` | Start of each researcher | `{ sub_query_id, question }` |
| `researcher_progress` | Each server-side web_search use | `{ sub_query_id, tool_call }` |
| `researcher_complete` | End of each researcher (success OR degraded) | `{ sub_query_id, finding }` |
| `synthesis_token` | Each token from the synthesizer stream | `{ token }` |
| `report_complete` | Terminal success | `{ report: FinalReport }` |
| `error` | Terminal (plan/synthesis) or scoped (research) failure | `{ stage, message, sub_query_id? }` |
| `cost_update` | After every Anthropic API response | `{ model, input_tokens, output_tokens, cumulative_usd }` |

### Ordering invariants (guarded by `tests/test_sse_contract.py`)

1. `plan_ready` precedes every `researcher_started`.
2. Every `researcher_started` has a matching `researcher_complete` (same `sub_query_id`).
3. Each `researcher_progress` falls between its `researcher_started` and `researcher_complete`.
4. `synthesis_token`s arrive only after **all** `researcher_complete`s.
5. `report_complete` is terminal — no `synthesis_token` or `report_complete` may follow it.
6. `cost_update.cumulative_usd` is monotonically non-decreasing.
7. Every event round-trips through `ResearchEventAdapter.validate_python(event.model_dump())`.

### Reconnect continuity

`InMemoryReportStore` keeps a per-report `deque(maxlen=50)` ring buffer. A client reconnecting mid-stream gets:
1. All events currently in the buffer (replay).
2. Then live events via its newly registered `asyncio.Queue`.

`subscribe()` registers the queue **before** snapshotting the buffer, in two consecutive synchronous statements. The asyncio single-threaded loop guarantees no `put_event` can interleave between those two, so there's no duplicate-yield window. When the report closes (`store.close`), a `None` sentinel on each queue terminates its subscriber.

## Error handling

Failures have two scopes:

1. **Stage-scoped, terminal** (plan or synthesis): emit an `ErrorEvent(stage=…)` and raise out of the node. `run_report` catches it, skips remaining stages, closes the report. The UI marks status as `"error"`.
2. **Sub-query-scoped, non-terminal** (one researcher fails): the DAG's `research_node` catches `ResearcherError`, emits `ErrorEvent(stage="research", sub_query_id=...)`, and **constructs a degraded `SubQueryFinding`** with `summary="Research failed: ..."` and empty facts/sources. All researchers' findings (degraded or not) are passed to the synthesizer, which acknowledges coverage gaps in the report ("Evidence on X was incomplete"). The UI marks that one agent red but the overall status stays `"researching"` → `"synthesizing"` → `"complete"`.

## The one non-obvious thing

**LangGraph sees a three-node chain; the researcher fan-out lives *inside* `research_node` via `asyncio.gather`.**

- **Why not add N researcher branches to the graph?** Because the number of researchers is determined dynamically by the planner (3–7), and LangGraph's conditional-fan-out patterns would add topology complexity for zero behavioral gain — the fan-out is just parallel async calls, not stateful branching.
- **Why not skip LangGraph entirely?** Three reasons: (a) it structures the state transitions cleanly with a TypedDict; (b) it's the contract (non-negotiable stack); (c) v2 extensions (retry on plan failure, conditional routing, checkpointing) will actually use its features.
- **Cost**: the `research_node` looks simpler than it is. Future-you reading this will wonder why the parallelism isn't visible in the graph topology. **It's here, intentionally, to keep the graph readable.**

## v2 extension points

| Extension | Where it plugs in | Size |
| --- | --- | --- |
| Persistent storage (Supabase/Postgres) | `storage/base.py` `ReportStore` Protocol — add `storage/supabase.py` implementing it; instantiate in `main.py:create_app`. | ~1 file |
| Auth | FastAPI dependency on `create_research` + `stream_research`; attach user to `Report`. Adjust `ReportStore.create` signature to carry owner. | 2 files |
| Prompt caching | `llm/client.py`: add `cache_control` blocks to system messages + long researcher context. Single-location change. | 1 file |
| Token-level observability (Langfuse, OTel) | `llm/client.py:_record()` already exists; wire it to a tracer. | 1 file |
| Rate limiting | FastAPI middleware in `main.py`; no agent changes. | 1 file |
| Eval harness | New `evals/` directory; orchestrator is callable from tests via `run_report` with a mocked `LLMClient`. Use LangSmith or a flat JSON fixture set. | ~3 files |
| Synthesizer cite-checking | `llm/client.py:stream_completion_with_tools()` is already scaffolded — swap the synthesizer's `stream_completion` for the tool-capable variant when ready. | 1 file in `agents/synthesizer.py` |
| Event replay beyond the ring buffer | Extend `ReportStore` to persist events, add `subscribe(report_id, since_seq)` with a sequence number. The per-report `deque` → append-only list + index. | ~1 file |
| Retry on planner failure | In `graph/dag.py` add a conditional edge from `plan` → `plan` with a retry counter in state. | 1 file |
| Streaming tool-use (mid-stream citations) | `stream_completion_with_tools` interface already exists; implement tool-use deltas in the streamer. | 1 file |

## File map

```
backend/src/ara/
  models/       — Pydantic domain + SSE event envelopes (ResearchEventAdapter)
  llm/          — Thin async Anthropic wrapper (complete_with_tools /
                   stream_completion / stream_completion_with_tools)
  agents/       — planner.py, researcher.py, synthesizer.py
  graph/        — state.py (TypedDict), dag.py (StateGraph)
  storage/      — base.py (Protocol), memory.py (InMemoryReportStore)
  runtime/      — orchestrator.py (run_report)
  api/          — routes.py (POST + SSE GET)
  main.py       — FastAPI app factory
  config.py     — Settings (pydantic-settings)
  pricing.py    — $/MTok table + estimate_cost_usd

frontend/
  app/
    page.tsx                   — landing form
    r/[reportId]/page.tsx      — live split-pane view
    layout.tsx                 — fonts + metadata
    globals.css                — Tailwind v4 + shadcn theme + typography
  components/
    research-form.tsx          — textarea + submit
    plan-tree.tsx              — sub-query list with agent-status chips
    agent-status.tsx           — phase badge (pending/running/done/error)
    report-stream.tsx          — react-markdown with inline [n] sup citations
    citation.tsx               — popover source card
    cost-meter.tsx             — running $$ with per-model breakdown
    status-pill.tsx            — derived stream status badge
    research-live.tsx          — split-pane composition
    ui/                        — shadcn primitives
  hooks/
    use-research-stream.ts     — typed EventSource + derived status enum
  lib/
    types.ts                   — TypeScript mirrors of backend models
    events.ts                  — SSE discriminated union
    api.ts                     — createResearch() POST client
```

## Dependencies on external services

- **Anthropic** (required): for all three LLM calls. Server-side `web_search_20250305` is the only external data source.
- That's it. No database, no cache, no vector store, no queue, no auth provider in v1.

## Not in v1 (by decision)

- User auth, multi-tenancy
- Database persistence
- PDF / docx export
- Slack / email delivery
- Rate limiting
- Redis / Celery / any external broker
- LangChain (LangGraph only — DAG orchestration)
- LiteLLM or any LLM abstraction layer (Anthropic SDK directly)
