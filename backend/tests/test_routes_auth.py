"""POST /research auth requirement + reports access matrix smoke."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ara.main import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_post_research_requires_auth(client: TestClient) -> None:
    r = client.post("/api/research", json={"question": "hi"})
    assert r.status_code == 401


def test_me_requires_auth(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 401


def test_quota_requires_auth(client: TestClient) -> None:
    r = client.get("/api/quota")
    assert r.status_code == 401


def test_reports_list_requires_auth(client: TestClient) -> None:
    r = client.get("/api/reports")
    assert r.status_code == 401


def test_stream_unknown_report_no_auth(client: TestClient) -> None:
    # Public path entry — no auth header. We expect either 503 (no DB)
    # or a non-200 response. The goal: this MUST NOT silently return events.
    r = client.get(f"/api/research/{uuid4()}/stream")
    assert r.status_code in (401, 403, 404, 503)


def test_gallery_public(client: TestClient) -> None:
    # Gallery is public; without DB it 503s. Either way, no 401.
    r = client.get("/api/gallery")
    assert r.status_code != 401


def test_config_public(client: TestClient) -> None:
    r = client.get("/api/config")
    assert r.status_code == 200
