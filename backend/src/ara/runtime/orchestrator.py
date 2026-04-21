"""Orchestrator — the single entry point for running a report end-to-end.

Wires a fresh `LLMClient` (with per-report cost hook) to a fresh compiled
graph, awaits the pipeline, and guarantees the report is closed even if
a terminal stage raises. Stage-scoped errors have already been emitted
by the time they bubble up here, so we swallow them silently.
"""

from __future__ import annotations

from uuid import UUID

from ara.agents import PlannerError, SynthesizerError
from ara.config import Settings
from ara.graph.dag import build_graph
from ara.llm.client import LLMClient
from ara.models.events import CostUpdate, ResearchEvent
from ara.options import ResearchOptions, options_for_depth
from ara.pricing import estimate_cost_usd
from ara.storage.base import ReportStore


async def run_report(
    *,
    report_id: UUID,
    question: str,
    store: ReportStore,
    settings: Settings,
    options: ResearchOptions | None = None,
    llm: LLMClient | None = None,
) -> None:
    """Run the full ARA pipeline for one report.

    `llm` is injectable for tests; production callers should omit it and
    let the orchestrator build the default client with the cost hook.

    `options` controls depth (sub-query count, web_search iteration cap)
    and the web_search toggle. Defaults to standard / web-search-on, which
    matches the behaviour before this knob existed.
    """
    if options is None:
        options = options_for_depth("standard")
    await store.create(report_id, question)
    cumulative_usd = 0.0

    async def emit(event: ResearchEvent) -> None:
        await store.put_event(report_id, event)

    async def on_api_call(model: str, input_tokens: int, output_tokens: int) -> None:
        nonlocal cumulative_usd
        cumulative_usd += estimate_cost_usd(model, input_tokens, output_tokens)
        await emit(
            CostUpdate(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cumulative_usd=cumulative_usd,
            )
        )

    if llm is None:
        llm = LLMClient(api_key=settings.anthropic_api_key, on_api_call=on_api_call)

    graph = build_graph(llm=llm, emit=emit, settings=settings, options=options)

    try:
        await graph.ainvoke({"report_id": report_id, "question": question})
    except (PlannerError, SynthesizerError):
        # Stage-scoped ErrorEvent already emitted by the failing node.
        pass
    finally:
        await store.close(report_id)
