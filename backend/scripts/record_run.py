# backend/scripts/record_run.py
"""Record a real ARA run to a static demo JSON for the client-side gallery.

    uv run python scripts/record_run.py "your question" --slug my-demo --title "My demo"

Runs the full pipeline with the server ANTHROPIC_API_KEY (costs a few cents),
captures every SSE event with timing, and writes
frontend/public/demos/<slug>.json, then rebuilds frontend/public/demos/manifest.json
from every *.json in that directory. Replay is then 100% client-side and free.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ara.config import get_settings
from ara.demos import build_demo_payload, build_manifest
from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import Depth, options_for_depth
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides

_DEMOS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demos"


class _RecordingStore:
    """Full-capture ReportStore for recording — no ring-buffer cap."""

    def __init__(self) -> None:
        self.events: list[tuple[float, ResearchEvent]] = []
        self.question: str = ""
        self._t0: float | None = None

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        self._t0 = time.monotonic()
        self.question = question

    async def get_question(self, report_id: UUID) -> str | None:
        return self.question

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        offset = 0.0 if self._t0 is None else time.monotonic() - self._t0
        self.events.append((offset, event))

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        if status == "error":
            print(f"run closed with error: {error_message}", file=sys.stderr)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        # Required by the ReportStore Protocol; unused during recording.
        return
        yield  # pragma: no cover — makes this an async generator


async def _main(question: str, slug: str, title: str, depth: Depth) -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; populate .env first.", file=sys.stderr)
        return 2

    store = _RecordingStore()
    overrides = RuntimeOverrides(
        api_key=settings.anthropic_api_key,
        planner_model=settings.claude_planner_model,
        researcher_model=settings.claude_researcher_model,
        synthesizer_model=settings.claude_synthesizer_model,
        options=options_for_depth(depth),
    )

    await run_report(
        report_id=uuid4(),
        question=question,
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=uuid4(),
    )

    payload = build_demo_payload(
        slug=slug,
        title=title,
        question=question,
        model=settings.claude_synthesizer_model,
        created_at=datetime.now(UTC).isoformat(),
        events=store.events,
    )

    _DEMOS_DIR.mkdir(parents=True, exist_ok=True)
    (_DEMOS_DIR / f"{slug}.json").write_text(json.dumps(payload, indent=2))

    payloads = [
        json.loads(p.read_text())
        for p in sorted(_DEMOS_DIR.glob("*.json"))
        if p.name != "manifest.json"
    ]
    (_DEMOS_DIR / "manifest.json").write_text(
        json.dumps(build_manifest(payloads), indent=2)
    )

    print(f"wrote {slug}.json ({len(store.events)} events) + manifest.json")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record an ARA run to demo JSON.")
    parser.add_argument("question")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--depth", choices=["quick", "standard", "deep"], default="standard"
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(_main(args.question, args.slug, args.title, args.depth))
    )
