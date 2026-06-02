"""Tests for the FastAPI surface.

Uses `httpx.AsyncClient` with `ASGITransport` rather than `TestClient`:
TestClient runs the app via a thread-based anyio portal, which interacts
badly with LangGraph 1.x's internal scheduling (the pipeline hangs after
the first node). AsyncClient runs the app in the test's own event loop,
which matches how it behaves under real uvicorn.

Agents are monkey-patched at their DAG import sites so the pipeline
completes without hitting Anthropic.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import httpx

from ara.auth import User, get_current_user, get_optional_user
from ara.main import create_app
from ara.models.research import (
    FinalReport,
    KeyFact,
    Priority,
    ReportSection,
    ResearchPlan,
    Source,
    SubQuery,
    SubQueryFinding,
)

_TEST_USER = User(id=uuid4(), email="test@example.com")
_BYOK_HEADER = {"X-Anthropic-Key": "test-byok-key"}


async def _bypass_access(
    _pool: Any, _report_id: Any, _user: Any, _share_token: Any
) -> dict[str, Any]:
    return {"owner_id": _TEST_USER.id, "is_sample": False, "share_token": None}


def _plan(n: int = 3) -> ResearchPlan:
    return ResearchPlan(
        original_question="q",
        sub_queries=[
            SubQuery(question=f"q{i}", rationale="r", priority=Priority.MEDIUM) for i in range(n)
        ],
    )


def _source(url: str = "https://example.com", title: str = "Ex") -> Source:
    return Source.model_validate({"url": url, "title": title})


def _fakes() -> tuple[Any, Any, Any]:
    async def fake_plan(**k: Any) -> ResearchPlan:
        return _plan()

    async def fake_research(*, sub_query: SubQuery, emit: Any, **k: Any) -> SubQueryFinding:
        src = _source(f"https://{sub_query.question}.com", sub_query.question)
        return SubQueryFinding(
            sub_query_id=sub_query.id,
            summary="s",
            key_facts=[KeyFact(statement="f", citation_ids=[src.id])],
            sources=[src],
        )

    async def fake_synth(**k: Any) -> FinalReport:
        src = _source()
        return FinalReport(
            report_id=k["report_id"],
            original_question=k["original_question"],
            executive_summary="Exec.",
            sections=[ReportSection(heading="H", content="C [1].", citation_ids=[src.id])],
            citations=[src],
        )

    return fake_plan, fake_research, fake_synth


async def _async_client() -> httpx.AsyncClient:
    app = create_app()
    # Bypass Supabase auth in tests by force-injecting a stable fake user.
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: _TEST_USER
    # POST /research calls _pool_or_503 before branching on BYOK. Set a
    # truthy sentinel pool so the gate passes; the BYOK path then never
    # actually uses the pool (no quota check).
    app.state.db_pool = object()
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_post_research_rejects_empty_question() -> None:
    async with await _async_client() as client:
        resp = await client.post(
            "/api/research", json={"question": ""}, headers=_BYOK_HEADER
        )
    assert resp.status_code == 422


async def test_get_config_returns_sanitized_settings() -> None:
    async with await _async_client() as client:
        resp = await client.get("/api/config")
    assert resp.status_code == 200
    body = resp.json()

    # Models — must mirror Settings defaults.
    assert set(body["models"].keys()) == {"planner", "researcher", "synthesizer"}
    assert isinstance(body["models"]["planner"], str)
    assert body["models"]["planner"]  # non-empty

    # Depth presets — must match the three locked levels.
    presets = body["depth_presets"]
    assert set(presets.keys()) == {"quick", "standard", "deep"}
    assert presets["quick"] == {"max_sub_queries": 3, "max_iterations": 2}
    assert presets["standard"] == {"max_sub_queries": 5, "max_iterations": 3}
    assert presets["deep"] == {"max_sub_queries": 7, "max_iterations": 5}

    # Sensitive and infra fields must NOT leak through.
    forbidden = {"anthropic_api_key", "ara_host", "ara_port", "ara_cors_origins"}
    flat_body = set(body.keys()) | set(body["models"].keys())
    assert flat_body.isdisjoint(forbidden)


async def test_post_research_returns_report_id() -> None:
    fake_plan, fake_research, fake_synth = _fakes()
    with (
        patch("ara.graph.dag.plan_research", fake_plan),
        patch("ara.graph.dag.research_sub_query", fake_research),
        patch("ara.graph.dag.synthesize_report", fake_synth),
    ):
        async with await _async_client() as client:
            resp = await client.post(
                "/api/research",
                json={"question": "what is rag?"},
                headers=_BYOK_HEADER,
            )

    assert resp.status_code == 200
    body = resp.json()
    assert "report_id" in body
    UUID(body["report_id"])  # must round-trip as a UUID


def _parse_sse_lines(text: str) -> list[dict[str, Any]]:
    """Parse raw SSE text into a list of {type, event, ...data} dicts."""
    events: list[dict[str, Any]] = []
    current_event: str | None = None
    for line in text.splitlines():
        if not line:
            current_event = None
            continue
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data = json.loads(line[len("data:") :].strip())
            events.append({"event": current_event, **data})
    return events


async def test_stream_delivers_plan_ready_and_report_complete() -> None:
    fake_plan, fake_research, fake_synth = _fakes()

    with (
        patch("ara.graph.dag.plan_research", fake_plan),
        patch("ara.graph.dag.research_sub_query", fake_research),
        patch("ara.graph.dag.synthesize_report", fake_synth),
        # Streaming route's access check expects a real DB row; stub it
        # so the in-memory store path can be exercised.
        patch("ara.api.routes._require_report_access", _bypass_access),
    ):
        async with await _async_client() as client:
            resp = await client.post(
                "/api/research", json={"question": "q"}, headers=_BYOK_HEADER
            )
            report_id = resp.json()["report_id"]

            async with client.stream(
                "GET", f"/api/research/{report_id}/stream"
            ) as stream:
                chunks = [chunk async for chunk in stream.aiter_text()]

    raw = "".join(chunks)
    events = _parse_sse_lines(raw)
    event_types = {e.get("type") for e in events}
    assert "plan_ready" in event_types
    assert "researcher_complete" in event_types
    assert "report_complete" in event_types
