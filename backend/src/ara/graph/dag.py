"""Build the compiled LangGraph: plan → research (fan-out) → synthesize.

Researcher fan-out happens *inside* `research_node` via `asyncio.gather`
rather than as N LangGraph branches. That keeps the graph topology simple
(the user-facing model is a 3-node chain) while still giving us true
parallelism. The tradeoff — one non-obvious thing in this system — is
documented in ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from ara.agents import EventEmitter, PlannerError, ResearcherError, SynthesizerError
from ara.agents.planner import plan_research
from ara.agents.researcher import research_sub_query
from ara.agents.synthesizer import synthesize_report
from ara.config import Settings
from ara.graph.state import GraphState
from ara.llm.client import LLMClient
from ara.models.events import (
    ErrorEvent,
    PlanReady,
    ReportComplete,
    ResearcherComplete,
)
from ara.models.research import SubQuery, SubQueryFinding
from ara.options import ResearchOptions, options_for_depth


@dataclass(frozen=True)
class GraphModels:
    planner: str
    researcher: str
    synthesizer: str


def build_graph(
    *,
    llm: LLMClient,
    emit: EventEmitter,
    settings: Settings,
    models: GraphModels,
    options: ResearchOptions | None = None,
) -> Any:
    """Return a compiled LangGraph bound to `llm`, `emit`, the per-run
    `models`, and per-run `options`. Settings is still consulted for
    engineering internals (researcher token budget).
    """
    opts = options if options is not None else options_for_depth("standard")

    async def plan_node(state: GraphState) -> dict[str, Any]:
        try:
            plan = await plan_research(
                question=state["question"],
                llm=llm,
                model=models.planner,
                max_sub_queries=opts.max_sub_queries,
            )
        except PlannerError as exc:
            await emit(ErrorEvent(stage="plan", message=str(exc)))
            raise
        plan = plan.model_copy(update={"web_search_enabled": opts.web_search_enabled})
        await emit(PlanReady(plan=plan))
        return {"plan": plan}

    async def research_node(state: GraphState) -> dict[str, Any]:
        plan = state["plan"]

        async def run_one(sq: SubQuery) -> SubQueryFinding:
            finding: SubQueryFinding
            try:
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
            except ResearcherError as exc:
                await emit(
                    ErrorEvent(stage="research", message=str(exc), sub_query_id=sq.id)
                )
                finding = SubQueryFinding(
                    sub_query_id=sq.id,
                    summary=f"Research failed: {exc}",
                    key_facts=[],
                    sources=[],
                )
            await emit(ResearcherComplete(sub_query_id=sq.id, finding=finding))
            return finding

        findings = await asyncio.gather(*(run_one(sq) for sq in plan.sub_queries))
        return {"findings": list(findings)}

    async def synthesize_node(state: GraphState) -> dict[str, Any]:
        try:
            report = await synthesize_report(
                report_id=state["report_id"],
                original_question=state["question"],
                findings=state["findings"],
                llm=llm,
                model=models.synthesizer,
                emit=emit,
            )
        except SynthesizerError as exc:
            await emit(ErrorEvent(stage="synthesis", message=str(exc)))
            raise
        report = report.model_copy(update={"web_search_enabled": opts.web_search_enabled})
        await emit(ReportComplete(report=report))
        return {"report": report}

    g: StateGraph[GraphState] = StateGraph(GraphState)
    g.add_node("plan", plan_node)
    g.add_node("research", research_node)
    g.add_node("synthesize", synthesize_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()
