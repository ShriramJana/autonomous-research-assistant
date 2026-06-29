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


def _truncate_summary(text: str, *, limit: int = 160) -> str:
    """Trim to <= limit chars on a word boundary, adding an ellipsis."""
    text = text.strip()
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0].rstrip()
    return f"{clipped}…"


def _event_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Derive the gallery-card fields from a payload's captured events.

    Reads the wire-shape event dicts (the `event` value produced by
    model_dump). Pure — no I/O.
    """
    summary = ""
    n_sources = 0
    n_sub_queries = 0
    cost_usd = 0.0
    started = 0
    seen_urls: set[str] = set()
    for item in events:
        ev = item["event"]
        etype = ev["type"]
        if etype == "plan_ready":
            n_sub_queries = len(ev["plan"]["sub_queries"])
        elif etype == "researcher_started":
            started += 1
        elif etype == "researcher_complete":
            for src in ev["finding"].get("sources", []):
                seen_urls.add(src["url"])
        elif etype == "report_complete":
            report = ev["report"]
            summary = _truncate_summary(report.get("executive_summary", ""))
            n_sources = len(report.get("citations", []))
        elif etype == "cost_update":
            cost_usd = ev["cumulative_usd"]
    if n_sub_queries == 0:
        n_sub_queries = started
    if n_sources == 0:
        n_sources = len(seen_urls)
    return {
        "summary": summary,
        "n_sources": n_sources,
        "n_sub_queries": n_sub_queries,
        "cost_usd": cost_usd,
    }


def build_manifest(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize demo payloads into the manifest the gallery lists."""
    out: list[dict[str, Any]] = []
    for p in payloads:
        entry: dict[str, Any] = {
            "slug": p["slug"],
            "title": p["title"],
            "question": p["question"],
            "model": p["model"],
            "created_at": p["created_at"],
            "n_events": len(p["events"]),
        }
        entry.update(_event_summary(p["events"]))
        out.append(entry)
    return out
