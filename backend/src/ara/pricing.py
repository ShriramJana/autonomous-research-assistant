"""Rough cost estimation for Anthropic model calls.

Single source of truth for $/MTok rates used both by the scripts CLI and
the orchestrator's live CostUpdate events. Update when Anthropic pricing
changes; unknown model ids silently fall back to zero cost rather than
crashing.
"""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-haiku-4-5": (0.80, 4.0),
}


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
