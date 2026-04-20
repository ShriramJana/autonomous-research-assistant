"""Unit tests for the planner agent.

Mocks the LLMClient completely — the planner's job is to turn a tool_use
response into a validated ResearchPlan, so that's what we check.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ara.agents import PlannerError
from ara.agents.planner import PLANNER_TOOL_NAME, plan_research
from ara.models.research import Priority, ResearchPlan
from tests.conftest import make_usage


def _mock_tool_use_response(tool_name: str, tool_input: dict[str, Any]) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input

    response = MagicMock()
    response.content = [block]
    response.stop_reason = "tool_use"
    response.usage = make_usage()
    return response


def _mock_no_tool_response() -> MagicMock:
    block = MagicMock()
    block.type = "text"
    response = MagicMock()
    response.content = [block]
    response.stop_reason = "end_turn"
    response.usage = make_usage()
    return response


async def test_planner_returns_validated_plan() -> None:
    response = _mock_tool_use_response(
        PLANNER_TOOL_NAME,
        {
            "sub_queries": [
                {"question": "What is RAG?", "rationale": "Foundations.", "priority": 3},
                {"question": "RAG vs fine-tuning?", "rationale": "Compare.", "priority": 2},
                {"question": "Open-source RAG stacks", "rationale": "Tools.", "priority": 1},
            ]
        },
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)

    plan = await plan_research(question="How should I pick RAG vs fine-tuning?", llm=llm, model="m")

    assert isinstance(plan, ResearchPlan)
    assert len(plan.sub_queries) == 3
    assert plan.sub_queries[0].priority == Priority.HIGH
    assert plan.original_question == "How should I pick RAG vs fine-tuning?"


async def test_planner_forces_tool_choice() -> None:
    response = _mock_tool_use_response(
        PLANNER_TOOL_NAME,
        {
            "sub_queries": [
                {"question": "q1", "rationale": "r1", "priority": 2},
                {"question": "q2", "rationale": "r2", "priority": 2},
                {"question": "q3", "rationale": "r3", "priority": 2},
            ]
        },
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)

    await plan_research(question="q?", llm=llm, model="m")

    kwargs = llm.complete_with_tools.await_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": PLANNER_TOOL_NAME}
    assert kwargs["tools"][0]["name"] == PLANNER_TOOL_NAME


async def test_planner_raises_when_tool_not_called() -> None:
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=_mock_no_tool_response())

    with pytest.raises(PlannerError, match="did not invoke"):
        await plan_research(question="q?", llm=llm, model="m")


async def test_planner_raises_on_too_few_sub_queries() -> None:
    response = _mock_tool_use_response(
        PLANNER_TOOL_NAME,
        {"sub_queries": [{"question": "q", "rationale": "r", "priority": 2}]},
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)

    with pytest.raises(PlannerError, match="validation"):
        await plan_research(question="q?", llm=llm, model="m")


async def test_planner_raises_on_invalid_priority() -> None:
    response = _mock_tool_use_response(
        PLANNER_TOOL_NAME,
        {
            "sub_queries": [
                {"question": "q1", "rationale": "r1", "priority": 99},
                {"question": "q2", "rationale": "r2", "priority": 2},
                {"question": "q3", "rationale": "r3", "priority": 2},
            ]
        },
    )
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)

    with pytest.raises(PlannerError, match="validation"):
        await plan_research(question="q?", llm=llm, model="m")


async def test_planner_raises_when_sub_queries_not_a_list() -> None:
    response = _mock_tool_use_response(PLANNER_TOOL_NAME, {"sub_queries": "nope"})
    llm = MagicMock()
    llm.complete_with_tools = AsyncMock(return_value=response)

    with pytest.raises(PlannerError, match="not a list"):
        await plan_research(question="q?", llm=llm, model="m")
