"""Planner agent — decomposes a research question into 3-7 sub-queries.

Uses Anthropic tool-use with `tool_choice` pinned to a single
`submit_research_plan` tool to force structured output.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ara.agents import PlannerError, extract_tool_use
from ara.llm.client import LLMClient, ToolSpec
from ara.models.research import ResearchPlan, SubQuery

PLANNER_TOOL_NAME = "submit_research_plan"

PLANNER_SYSTEM_PROMPT = """\
You are the Planner stage of an autonomous research assistant.

Given a research question from the user, decompose it into 3 to 7 sub-queries \
that, when answered individually, will collectively produce a thorough, \
well-sourced answer to the original question.

Design principles for a good decomposition:
- Cover the question from complementary angles: definitions / background, \
  current state-of-the-art, comparisons, risks / criticisms, concrete \
  examples or case studies.
- Each sub-query should be answerable by one focused web-search session.
- Avoid redundancy — no two sub-queries should return overlapping material.
- Assign priority: 3 (high) for foundational queries the final report \
  depends on, 2 (medium) for substantive supporting questions, 1 (low) for \
  nice-to-have context.

You MUST call the `submit_research_plan` tool with your decomposition. \
Do not respond with plain text.
"""

PLANNER_TOOL: ToolSpec = {
    "name": PLANNER_TOOL_NAME,
    "description": (
        "Submit the decomposition of the research question into 3 to 7 "
        "actionable sub-queries. Each sub-query must include a rationale "
        "and a priority (1=low, 2=medium, 3=high)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sub_queries": {
                "type": "array",
                "minItems": 3,
                "maxItems": 7,
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The sub-question to research.",
                        },
                        "rationale": {
                            "type": "string",
                            "description": (
                                "Why this sub-query matters to the overall question."
                            ),
                        },
                        "priority": {
                            "type": "integer",
                            "enum": [1, 2, 3],
                            "description": "1=low, 2=medium, 3=high.",
                        },
                    },
                    "required": ["question", "rationale", "priority"],
                },
            }
        },
        "required": ["sub_queries"],
    },
}


async def plan_research(
    *,
    question: str,
    llm: LLMClient,
    model: str,
    max_tokens: int = 2048,
) -> ResearchPlan:
    """Run the planner and return a validated `ResearchPlan`.

    Raises `PlannerError` if the model returns no tool call or malformed data.
    """
    response = await llm.complete_with_tools(
        model=model,
        messages=[{"role": "user", "content": question}],
        tools=[PLANNER_TOOL],
        tool_choice={"type": "tool", "name": PLANNER_TOOL_NAME},
        system=PLANNER_SYSTEM_PROMPT,
        max_tokens=max_tokens,
    )

    tool_input = extract_tool_use(response, PLANNER_TOOL_NAME)
    if tool_input is None:
        raise PlannerError(
            f"Planner did not invoke {PLANNER_TOOL_NAME!r} "
            f"(stop_reason={response.stop_reason!r})"
        )

    raw_sub_queries: Any = tool_input.get("sub_queries", [])
    if not isinstance(raw_sub_queries, list):
        raise PlannerError(f"`sub_queries` is not a list: {type(raw_sub_queries).__name__}")

    try:
        sub_queries = [SubQuery(**sq) for sq in raw_sub_queries]
        return ResearchPlan(original_question=question, sub_queries=sub_queries)
    except ValidationError as exc:
        raise PlannerError(f"Planner output failed validation: {exc}") from exc
