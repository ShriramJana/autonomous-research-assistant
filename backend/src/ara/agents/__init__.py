"""Research pipeline agents: planner, researcher, synthesizer."""

from collections.abc import Awaitable, Callable
from typing import Any

from ara.llm.client import CompletionResult
from ara.models.events import ResearchEvent

EventEmitter = Callable[[ResearchEvent], Awaitable[None]]


class AgentError(RuntimeError):
    """Base class for agent-layer failures."""


class PlannerError(AgentError):
    """Planner failed to produce a valid ResearchPlan."""


class ResearcherError(AgentError):
    """Researcher failed to produce a finding within budget."""


class SynthesizerError(AgentError):
    """Synthesizer failed to produce a final report."""


def extract_tool_use(result: CompletionResult, tool_name: str) -> dict[str, Any] | None:
    """Return the input of the first client-side tool_use matching `tool_name`, or None."""
    for tu in result.tool_uses:
        if tu.name == tool_name:
            return tu.input
    return None


__all__ = [
    "AgentError",
    "EventEmitter",
    "PlannerError",
    "ResearcherError",
    "SynthesizerError",
    "extract_tool_use",
]
