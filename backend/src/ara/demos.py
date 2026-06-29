# backend/src/ara/demos.py
"""Pure builders that turn captured events into the static demo JSON shape.

Kept free of I/O and the Anthropic SDK so they can be unit-tested without a
key. The recorder script (scripts/record_run.py) supplies the captured
events; these functions only reshape them.
"""

from __future__ import annotations

from typing import Any

from ara.models.events import ResearchEvent


def build_demo_payload(
    *,
    slug: str,
    title: str,
    question: str,
    model: str,
    created_at: str,
    events: list[tuple[float, ResearchEvent]],
) -> dict[str, Any]:
    """Reshape (offset_seconds, event) pairs into the on-disk demo file.

    `t_ms` is the integer-millisecond offset from the start of the run, used
    by the frontend to pace replay. `event` is the exact SSE wire object
    (model_dump(mode="json")), so it round-trips through the frontend's
    JSON.parse without translation.
    """
    return {
        "slug": slug,
        "title": title,
        "question": question,
        "model": model,
        "created_at": created_at,
        "events": [
            {"t_ms": round(offset * 1000), "event": event.model_dump(mode="json")}
            for offset, event in events
        ],
    }


def build_manifest(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize demo payloads into the manifest the gallery lists."""
    return [
        {
            "slug": p["slug"],
            "title": p["title"],
            "question": p["question"],
            "model": p["model"],
            "created_at": p["created_at"],
            "n_events": len(p["events"]),
        }
        for p in payloads
    ]
