"""Orchestrator — the single entry point for running a report end-to-end."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from ara.agents import PlannerError, SynthesizerError
from ara.config import Settings
from ara.graph.dag import GraphModels, build_graph
from ara.llm.client import LLMClient
from ara.llm.factory import build_client
from ara.models.events import CostUpdate, ReportComplete, ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import _DEPTH_PRESETS, Depth, ResearchOptions
from ara.pricing import estimate_cost_usd, model_is_priced
from ara.runtime.overrides import RuntimeOverrides
from ara.storage.base import ReportStore


async def run_report(
    *,
    report_id: UUID,
    question: str,
    store: ReportStore,
    settings: Settings,
    overrides: RuntimeOverrides,
    owner_id: UUID,
    llm: LLMClient | None = None,
) -> None:
    """Run the full ARA pipeline for one report.

    `overrides` carries per-request key + models + options.
    `owner_id` is the Supabase user that owns this report.
    `llm` is injectable for tests; production callers should omit it.
    """
    await store.create(
        report_id,
        question,
        owner_id=owner_id,
        depth=_depth_for(overrides.options),
        browse_web=overrides.options.web_search_enabled,
        used_byok=_is_byok(overrides.api_key, settings),
    )
    cumulative_usd = 0.0
    final_report: ReportEnvelope | None = None

    async def emit(event: ResearchEvent) -> None:
        nonlocal final_report
        await store.put_event(report_id, event)
        if isinstance(event, ReportComplete):
            final_report = event.report

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

    if llm is None:
        llm = build_client(overrides, on_api_call=on_api_call)

    models = GraphModels(
        planner=overrides.planner_model,
        researcher=overrides.researcher_model,
        synthesizer=overrides.synthesizer_model,
    )
    graph = build_graph(
        llm=llm, emit=emit, settings=settings, models=models, options=overrides.options
    )

    status: Literal["completed", "error"] = "completed"
    error_message: str | None = None
    try:
        await graph.ainvoke({"report_id": report_id, "question": question})
    except (PlannerError, SynthesizerError) as exc:
        status = "error"
        error_message = str(exc)
    except Exception as exc:  # pragma: no cover — defense-in-depth
        status = "error"
        error_message = f"Unexpected: {exc!r}"
    finally:
        await store.close(
            report_id,
            status=status,
            cost_usd=cumulative_usd,
            report_payload=final_report,
            error_message=error_message,
        )


def _depth_for(options: ResearchOptions) -> Depth:
    """Reverse-lookup helper — recover the depth label from a ResearchOptions.

    The orchestrator is given options, but the report row stores the
    label. Compare against known presets.
    """
    for label, preset in _DEPTH_PRESETS.items():
        if (
            options.max_sub_queries == preset.max_sub_queries
            and options.max_iterations == preset.max_iterations
        ):
            return label
    return "standard"


def _is_byok(api_key: str, settings: Settings) -> bool:
    """A run is BYOK if it's NOT using the server's free-tier key."""
    return api_key != settings.anthropic_api_key
