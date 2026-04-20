"""Research pipeline agents: planner, researcher, synthesizer."""

from typing import Any, cast

from anthropic.types import Message


class AgentError(RuntimeError):
    """Base class for agent-layer failures."""


class PlannerError(AgentError):
    """Planner failed to produce a valid ResearchPlan."""


class ResearcherError(AgentError):
    """Researcher failed to produce a finding within budget."""


class SynthesizerError(AgentError):
    """Synthesizer failed to produce a final report."""


def extract_tool_use(response: Message, tool_name: str) -> dict[str, Any] | None:
    """Return the input of the first tool_use block matching `tool_name`, or None."""
    for block in response.content:
        if block.type == "tool_use" and block.name == tool_name:
            return cast(dict[str, Any], block.input)
    return None


__all__ = [
    "AgentError",
    "PlannerError",
    "ResearcherError",
    "SynthesizerError",
    "extract_tool_use",
]
