"""LangGraph state shape.

`plan`, `findings`, `report` are populated in order by the three nodes.
Accessing `state["plan"]` in the research node is safe: if the plan node
didn't run to completion, the graph wouldn't reach research.
"""

from __future__ import annotations

from typing import NotRequired, TypedDict
from uuid import UUID

from ara.models.research import FinalReport, ResearchPlan, SubQueryFinding


class GraphState(TypedDict):
    report_id: UUID
    question: str
    plan: NotRequired[ResearchPlan]
    findings: NotRequired[list[SubQueryFinding]]
    report: NotRequired[FinalReport]
