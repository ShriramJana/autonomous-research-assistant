# Building an Autonomous Research Assistant with a Three-Stage LLM Pipeline

I built ARA (Autonomous Research Assistant) as the flagship portfolio project for LLMTechno, my AI consulting practice. It is a research agent that takes a natural-language question, decomposes it into parallel sub-queries, web-searches each one, and synthesizes a cited report — all streamed live to the browser as it runs. The source is on GitHub at [ShriramJana/autonomous-research-assistant](https://github.com/ShriramJana/autonomous-research-assistant).

**[Try it live](https://autonomous-research-assistant-tawny.vercel.app)** — no account required for the demo gallery; bring your own Anthropic or OpenAI key for a live run.

---

## The Problem

Doing background research manually is slow and produces uncited prose. You copy-paste from a dozen browser tabs, lose track of which claim came from where, and end up with something neither skimmable nor reproducible. LLMs make this worse in a specific way: they answer confidently from training data without telling you which sources they used or when those sources were written.

I wanted a tool that:

1. Breaks a broad question into focused sub-queries automatically.
2. Searches the web for each sub-query in parallel.
3. Returns a structured report where every fact has a stable, inspectable source citation.
4. Shows the work as it happens, not just the finished answer.

---

## The Solution

ARA is a three-stage agent pipeline:

- **Planner** — given the user's question, produces 3–7 sub-queries with rationale and priority.
- **Researchers** — one agent per sub-query, run in parallel; each searches the web and returns structured findings with citations.
- **Synthesizer** — combines all findings into a final report with an executive summary, sections, and a deduplicated master citation list.

The whole run streams over SSE in real time. The left pane of the UI shows each researcher agent's status (pending → running → done / error) and the cost meter ticking up. The right pane shows the synthesis tokens arriving as the model writes.

For portfolio visitors who do not have an Anthropic key, a static demo gallery lets them watch pre-recorded real runs replay in the browser at roughly 20x speed, client-side, with no backend calls.

---

## Architecture

### The LangGraph DAG

The orchestration layer is a three-node LangGraph `StateGraph`:

```
plan_node → research_node → synthesize_node
```

The state is a TypedDict carrying the original question, the `ResearchPlan`, a list of `SubQueryFinding` objects, and the final `FinalReport`.

The one non-obvious decision: **the researcher fan-out lives inside `research_node` via `asyncio.gather`, not as separate graph branches.** The planner returns 3–7 sub-queries dynamically; modeling that as N conditional edges in the graph would add topology complexity for zero behavioral gain. The parallelism is just concurrent async calls. LangGraph earns its keep on the outer structure — clean state transitions, and a clear extension point for v2 features like retry-on-plan-failure or conditional routing.

### The Three Stages in Detail

**Planner.** A single Anthropic call using `tool_choice={"type": "tool", "name": "submit_research_plan"}` — forced tool use guarantees structured output. The tool's JSON Schema encodes the 3–7 bound and the priority enum; invalid output raises `PlannerError` immediately rather than silently degrading.

**Researcher.** Each researcher makes a single Anthropic call that combines two tools: `web_search_20250305` (server-side, up to 5 uses per call) and `submit_finding` (client-side, for structured output). The model searches, reads results, then calls `submit_finding` with a `SubQueryFinding` containing a summary, key facts, and sources. We assign stable UUIDs to each `Source` and rewrite the model's URL-based citations into `citation_ids: list[UUID]`. Guardrails: max 5 web-search iterations and a 100k input-token budget; either breach raises `ResearcherError`.

**Synthesizer.** A streaming Anthropic call that sees the original question plus all findings. Sources from all researchers are URL-deduplicated into a master list before the call; the model writes `[n]` inline citations; the parser translates `[n]` back into stable `Source.id` UUIDs. Tokens arrive as `SynthesisToken` SSE events in real time; the accumulated markdown is parsed into the structured `FinalReport` after the stream closes.

### SSE Streaming and the Event Contract

Every event is a JSON-serialized member of a Pydantic discriminated union (`ResearchEvent`) that round-trips through `ResearchEventAdapter`. The full event set:

| Event | Fires when |
|---|---|
| `plan_ready` | Planner returns |
| `researcher_started` | Each researcher begins |
| `researcher_progress` | Each server-side web-search use |
| `researcher_complete` | Each researcher finishes (success or degraded) |
| `synthesis_token` | Each token from the synthesizer stream |
| `report_complete` | Terminal success |
| `error` | Any failure, scoped or terminal |
| `cost_update` | After every Anthropic API response |

Ordering invariants are asserted in `tests/test_sse_contract.py`: `plan_ready` precedes every `researcher_started`; every `researcher_started` has a matching `researcher_complete`; `synthesis_token`s arrive only after all `researcher_complete`s; `report_complete` is terminal; `cost_update.cumulative_usd` is monotonically non-decreasing.

### Reconnect Continuity

`InMemoryReportStore` keeps a per-report `deque(maxlen=50)` ring buffer. A client reconnecting mid-stream replays all buffered events, then picks up live events via a newly registered `asyncio.Queue`. The queue is registered before the buffer is snapshotted — in two consecutive synchronous statements — so the asyncio single-threaded loop guarantees no event can slip between them.

### Error Handling

Failures have two scopes:

- **Terminal** (planner or synthesizer failure): emit `ErrorEvent`, close the report. The UI marks status as `"error"`.
- **Non-terminal** (one researcher fails): `research_node` catches `ResearcherError`, emits a scoped `ErrorEvent`, and constructs a degraded `SubQueryFinding` with `summary="Research failed: …"` and empty facts/sources. The synthesizer still runs and explicitly acknowledges the coverage gap in the report. The UI marks that one agent red but the overall run continues to completion.

---

## BYOK and Cost Design

I wanted this project to be demonstrable without burning API budget every time a visitor loads it.

**For everyone:** a static demo gallery with three pre-recorded real runs (quantum supremacy, the 2008 financial crisis, transformer model history). Each recording is a JSON file in `frontend/public/demos/` committed to the repo. A client-side replayer (`lib/replay.ts`) scales the original event timestamps to approximately 20 seconds total, with per-stage dwell and a readable synthesis cadence. No backend is involved; no Supabase auth calls happen.

**For visitors with their own API key:** they save an Anthropic or OpenAI key in Settings (write-only — the key is encrypted server-side with Fernet and stored per-user in Supabase; it is never returned to the client). When they submit a run, the backend resolves their stored credential and uses it. My server-side `ANTHROPIC_API_KEY` is intentionally absent in production; every live run is on the visitor's key. My monthly hosting bill for the backend is the Render free tier: $0.

**The tradeoff:** Render's free tier spins down after inactivity. The first request after a cold start takes 30–60 seconds to respond. I surface this in the UI with a notice shown while the request is pending, so visitors know to wait rather than retry.

A global Tavily cap (`TAVILY_GLOBAL_MONTHLY_CAP`, default 1000 searches/month) is tracked per run in the `reports` table and checked before each run. When the cap is reached, runs that use the client-side Tavily path degrade gracefully to model-knowledge-only rather than failing hard.

---

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, async throughout, Pydantic v2 |
| Orchestration | LangGraph (StateGraph, 3-node chain) |
| LLM | Anthropic SDK directly — `AnthropicClient` and `OpenAICompatClient` behind an `LLMClient` Protocol |
| Web search | Anthropic server-side `web_search_20250305`; client-side Tavily for non-Anthropic providers |
| Packaging | `uv` + `pyproject.toml` |
| Frontend | Next.js 16, TypeScript strict, Tailwind v4, shadcn/ui |
| Auth + persistence | Supabase (Postgres for credential storage and run metadata; GoTrue for auth) |
| Hosting | Vercel (frontend), Render free tier (backend) |

No LangChain, no LiteLLM, no generic LLM abstraction beyond the `LLMClient` Protocol I wrote. The Anthropic and OpenAI SDKs are called directly.

---

## What I Learned

**Citations break if you use list indices.** My first synthesizer draft numbered sources `[1]`, `[2]`, … and passed those indices to the researcher agents. The moment the synthesizer deduplicated sources across findings, every index shifted. The fix: assign a stable `UUID` to each `Source` at researcher time, use those UUIDs in `KeyFact.citation_ids`, deduplicate by URL before the synthesis call, and translate the model's `[n]` shorthand back into UUIDs in the parser. The UUID scheme is now load-bearing throughout the type system.

**Partial researcher failure is the normal case, not an edge case.** Real web searches fail or return thin results. Treating a single researcher error as a fatal pipeline error would make the whole system brittle. The solution is to define a degraded `SubQueryFinding` as a valid output: the synthesizer is explicitly told to acknowledge coverage gaps, and the UI marks the one failed agent without killing the overall run. This distinction — terminal vs. non-terminal error scope — had to be a first-class design decision, not an afterthought.

**The in-memory ring buffer forces single-instance deployment.** Because events are buffered in a Python dict keyed by report ID, two instances would not share state. This is a known, intentional constraint for v1: the `ReportStore` Protocol has a clear swap point for a Supabase-backed implementation, and the buffer's `maxlen=50` is a deliberate ceiling that prevents memory growth on long-running servers. Naming the constraint explicitly in the architecture doc meant I stopped being surprised by it.

**`asyncio.gather` inside a LangGraph node works cleanly — but document it.** Future readers of the graph definition will see three nodes and assume researchers are sequential. The actual parallelism is invisible at the graph level. The right answer was not to restructure the graph but to document the decision explicitly in `ARCHITECTURE.md` with the reasoning. Code clarity and graph readability are sometimes in tension; you have to choose which surface to optimize and then explain the other.

**Forced tool use is the right pattern for structured planner output.** Using `tool_choice={"type": "tool", "name": "submit_research_plan"}` means the model must return valid JSON conforming to the tool's schema, or the API returns an error. Compared to prompting for JSON and parsing the response, this eliminates an entire class of output-format bugs and makes the schema the single source of truth.

---

## Where This Goes Next

ARA v1 searches the open web. The highest-leverage next step is grounding it in **peer-reviewed literature** — a dedicated scholarly-research agent that runs alongside the web researcher and draws on open academic APIs, so a claim can cite a 2024 paper instead of a blog post. The integrations I would prioritize, in order:

- **OpenAlex** — an open catalog of ~250M scholarly works with full citation graphs, authors, and venues. The broadest free index, and the natural backbone for academic search.
- **Semantic Scholar** — AI-generated abstracts, TLDRs, and "influential citation" signals; ideal for ranking which papers on a topic actually matter rather than just which exist.
- **arXiv** — preprints across CS, physics, math, and quantitative biology, for surfacing cutting-edge work months before formal publication.
- **PubMed / NCBI E-utilities** — the authoritative biomedical index, where general web search is least trustworthy and the stakes are highest.
- **Crossref** — DOI resolution and publisher metadata to canonicalize and deduplicate citations across all of the above.

Two product features fall out of this naturally:

- **Citation export** — emit a report's sources as BibTeX/RIS so results drop straight into Zotero, Mendeley, or a manuscript's bibliography.
- **Source-quality signals** — show publication date, venue, and citation count beside each source, so readers can weigh evidence rather than trust it flat.

The current design already anticipates this. Each scholarly API is just another tool the researcher agent can call — the `LLMClient` Protocol and tool-dispatch loop do not care whether a search hits the web or OpenAlex — and because every source already carries a stable UUID, academic and web references coexist in one deduplicated citation list with no schema changes.

---

## Source and Live Demo

Source: [https://github.com/ShriramJana/autonomous-research-assistant](https://github.com/ShriramJana/autonomous-research-assistant)

Live: [https://autonomous-research-assistant-tawny.vercel.app](https://autonomous-research-assistant-tawny.vercel.app)
