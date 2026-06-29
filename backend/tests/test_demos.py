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
        }
    ]
