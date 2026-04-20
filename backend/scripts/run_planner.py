"""Ad-hoc planner runner for manual evaluation.

    uv run python scripts/run_planner.py "your question here"

Loads Settings from the root .env, runs the planner, prints the plan as
indented JSON. Exits non-zero on PlannerError.
"""

from __future__ import annotations

import asyncio
import json
import sys

from ara.agents import PlannerError
from ara.agents.planner import plan_research
from ara.config import get_settings
from ara.llm.client import LLMClient


async def _main(question: str) -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; populate .env first.", file=sys.stderr)
        return 2

    llm = LLMClient.from_settings(settings)
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
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: run_planner.py <question>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(sys.argv[1])))
