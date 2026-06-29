# backend/tests/test_demos.py
"""Tests for the pure demo-payload builders (no API key needed)."""

from __future__ import annotations

from ara.demos import build_demo_payload, build_manifest
from ara.models.events import PlanReady, SynthesisToken
from ara.models.research import Priority, ResearchPlan, SubQuery


def _sample_events() -> list[tuple[float, object]]:
    plan = ResearchPlan(
        original_question="What is quantum supremacy?",
        sub_queries=[
            SubQuery(
                question="Define quantum supremacy",
                rationale="Establish the core definition.",
                priority=Priority.HIGH,
            ),
            SubQuery(
                question="Notable demonstrations",
                rationale="Ground it in real experiments.",
                priority=Priority.MEDIUM,
            ),
            SubQuery(
                question="Criticisms of the claims",
                rationale="Balance the picture with skepticism.",
                priority=Priority.LOW,
            ),
        ],
        web_search_enabled=True,
    )
    return [
        (0.0, PlanReady(plan=plan)),
        (0.5, SynthesisToken(token="Quantum ")),
        (0.75, SynthesisToken(token="supremacy")),
    ]


def test_build_demo_payload_shape() -> None:
    payload = build_demo_payload(
        slug="sample-quantum",
        title="Quantum supremacy",
        question="What is quantum supremacy?",
        model="claude-sonnet-4-5",
        created_at="2026-06-28T00:00:00Z",
        events=_sample_events(),
    )
    assert payload["slug"] == "sample-quantum"
    assert payload["question"] == "What is quantum supremacy?"
    assert len(payload["events"]) == 3
    first = payload["events"][0]
    assert first["t_ms"] == 0
    assert first["event"]["type"] == "plan_ready"
    # Timing offsets are integer milliseconds derived from the float seconds.
    assert payload["events"][1]["t_ms"] == 500
    assert payload["events"][2]["t_ms"] == 750


def test_build_manifest_entry_summarizes() -> None:
    payload = build_demo_payload(
        slug="sample-quantum",
        title="Quantum supremacy",
        question="What is quantum supremacy?",
        model="claude-sonnet-4-5",
        created_at="2026-06-28T00:00:00Z",
        events=_sample_events(),
    )
    manifest = build_manifest([payload])
    assert manifest == [
        {
            "slug": "sample-quantum",
            "title": "Quantum supremacy",
            "question": "What is quantum supremacy?",
            "model": "claude-sonnet-4-5",
            "created_at": "2026-06-28T00:00:00Z",
            "n_events": 3,
            "summary": "",
            "n_sources": 0,
            "n_sub_queries": 3,
            "cost_usd": 0.0,
        }
    ]


def _enriched_payload() -> dict[str, object]:
    """A payload (already in on-disk dict shape) with a report + cost event."""
    long_summary = (
        "Quantum supremacy is the milestone at which a programmable quantum "
        "device solves a problem no classical computer can solve in any feasible "
        "amount of time, a threshold first claimed by Google in 2019."
    )
    return {
        "slug": "q",
        "title": "Q",
        "question": "What is quantum supremacy?",
        "model": "claude-sonnet-4-5",
        "created_at": "2026-06-28T00:00:00Z",
        "events": [
            {
                "t_ms": 0,
                "event": {
                    "type": "plan_ready",
                    "plan": {
                        "original_question": "What is quantum supremacy?",
                        "web_search_enabled": True,
                        "sub_queries": [
                            {"id": "1", "question": "a", "rationale": "a", "priority": 3},
                            {"id": "2", "question": "b", "rationale": "b", "priority": 2},
                        ],
                    },
                },
            },
            {
                "t_ms": 100,
                "event": {
                    "type": "report_complete",
                    "report": {
                        "report_id": "00000000-0000-0000-0000-000000000000",
                        "original_question": "What is quantum supremacy?",
                        "web_search_enabled": True,
                        "executive_summary": long_summary,
                        "sections": [],
                        "citations": [
                            {"id": "a", "url": "https://example.com/1", "title": "One"},
                            {"id": "b", "url": "https://example.com/2", "title": "Two"},
                            {"id": "c", "url": "https://example.com/3", "title": "Three"},
                        ],
                    },
                },
            },
            {
                "t_ms": 120,
                "event": {
                    "type": "cost_update",
                    "model": "claude-sonnet-4-5",
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cumulative_usd": 0.0492,
                },
            },
        ],
    }


def test_build_manifest_enriches_from_report_and_cost() -> None:
    entry = build_manifest([_enriched_payload()])[0]
    assert entry["n_sub_queries"] == 2
    assert entry["n_sources"] == 3
    assert entry["cost_usd"] == 0.0492
    # Summary is trimmed to <= ~160 chars on a word boundary with an ellipsis.
    assert entry["summary"].endswith("…")
    assert len(entry["summary"]) <= 161
    assert entry["summary"].startswith("Quantum supremacy is the milestone")


def test_build_manifest_source_fallback_counts_finding_urls() -> None:
    payload = {
        "slug": "s", "title": "S", "question": "q", "model": "m",
        "created_at": "t",
        "events": [
            {"t_ms": 0, "event": {
                "type": "researcher_complete", "sub_query_id": "1",
                "finding": {"sub_query_id": "1", "summary": "x", "key_facts": [],
                            "sources": [
                                {"id": "a", "url": "https://e.com/1", "title": "1"},
                                {"id": "b", "url": "https://e.com/1", "title": "dup"},
                                {"id": "c", "url": "https://e.com/2", "title": "2"},
                            ]}}},
        ],
    }
    entry = build_manifest([payload])[0]
    # No report_complete → fall back to distinct source URLs across findings.
    assert entry["n_sources"] == 2
