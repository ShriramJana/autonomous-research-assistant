"""Ad-hoc planner runner for manual evaluation.

    uv run python scripts/run_planner.py "your question here"

Loads Settings from the root .env, runs the planner, prints the plan as
indented JSON and a per-model token/cost summary. Exits non-zero on
PlannerError.

The $/MTok rates below are approximate list prices for the Claude 4.x
tier; tweak `PRICING` if they change. Real cost accounting should live in
the LLMClient observability hook once the UI is wired up.
"""

from __future__ import annotations

import asyncio
import json
import sys

from ara.agents import PlannerError
from ara.agents.planner import plan_research
from ara.config import get_settings
from ara.llm.client import LLMClient

# Approximate $/MTok (input, output). Update if Anthropic pricing changes.
PRICING: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-7": (15.0, 75.0),
}


def _estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate


async def _main(question: str) -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; populate .env first.", file=sys.stderr)
        return 2

    usage: list[tuple[str, int, int]] = []
    llm = LLMClient(
        api_key=settings.anthropic_api_key,
        on_api_call=lambda model, inp, out: usage.append((model, inp, out)),
    )

    try:
        plan = await plan_research(
            question=question,
            llm=llm,
            model=settings.claude_planner_model,
        )
    except PlannerError as exc:
        print(f"PlannerError: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(plan.model_dump(mode="json"), indent=2))

    print("\n--- usage ---", file=sys.stderr)
    total_cost = 0.0
    for model, inp, out in usage:
        cost = _estimate_cost_usd(model, inp, out)
        total_cost += cost
        print(
            f"{model:30s} in={inp:>6d}  out={out:>5d}  ≈ ${cost:.6f}",
            file=sys.stderr,
        )
    print(f"{'TOTAL':30s} {'':<6}   {'':<5}   ≈ ${total_cost:.6f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: run_planner.py <question>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(sys.argv[1])))
