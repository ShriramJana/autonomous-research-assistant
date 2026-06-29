"""Tests for credential management endpoints and storage-resolved create_research.

These tests use the same async-client harness as test_api.py.
- For DB-gated operations (upsert/delete, true round-trips) we use `requires_db`.
- For resolution tests we patch `ara.api.routes.get_credentials` to return a
  CredentialRecord so no DB is needed.
- For encryption-key-absent tests we override Settings directly.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from ara.auth import User, get_current_user, get_optional_user
from ara.config import Settings, get_settings
from ara.credentials import CredentialRecord, TavilyCapStatus
from ara.crypto import encrypt_secret, generate_key
from ara.main import create_app
from ara.quota import QuotaOk

_TEST_USER = User(id=uuid4(), email="test@example.com")

# Mark that requires a live DB (env SUPABASE_DB_URL set)
requires_db = pytest.mark.skipif(
    not __import__("os").environ.get("SUPABASE_DB_URL"),
    reason="requires SUPABASE_DB_URL",
)


# ---------------------------------------------------------------------------
# Harness helpers
# ---------------------------------------------------------------------------


async def _async_client(
    encryption_key: str | None = None,
) -> httpx.AsyncClient:
    """Build an AsyncClient with auth bypassed and a sentinel db_pool."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: _TEST_USER
    app.state.db_pool = object()

    if encryption_key is not None:
        settings_with_key = Settings(ara_encryption_key=encryption_key)
        app.dependency_overrides[get_settings] = lambda: settings_with_key

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# 503 when ARA_ENCRYPTION_KEY is unset
# ---------------------------------------------------------------------------


async def test_put_anthropic_key_503_without_encryption_key() -> None:
    """PUT /api/credentials/anthropic → 503 when ARA_ENCRYPTION_KEY is not set."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_settings] = lambda: Settings(ara_encryption_key="")
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/credentials/anthropic",
            json={"key": "sk-ant-test"},
        )
    assert resp.status_code == 503
    assert "ARA_ENCRYPTION_KEY" in resp.json()["detail"]


async def test_put_openai_config_503_without_encryption_key() -> None:
    """PUT /api/credentials/openai → 503 when ARA_ENCRYPTION_KEY is not set."""
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_settings] = lambda: Settings(ara_encryption_key="")
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            "/api/credentials/openai",
            json={
                "key": "sk-test",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4o",
            },
        )
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /api/credentials returns correct structure
# ---------------------------------------------------------------------------


async def test_get_credentials_no_record_returns_free_defaults() -> None:
    """GET /api/credentials when user has no stored creds → free defaults."""
    async with await _async_client() as client:
        with patch(
            "ara.api.routes.get_credentials",
            new=AsyncMock(return_value=None),
        ):
            resp = await client.get("/api/credentials")

    assert resp.status_code == 200
    body = resp.json()
    assert body["active_provider"] == "free"
    assert body["anthropic_configured"] is False
    assert body["openai"]["configured"] is False
    assert body["openai"]["base_url"] is None
    assert body["openai"]["model"] is None


async def test_get_credentials_anthropic_configured() -> None:
    """GET /api/credentials reflects a stored anthropic key (ciphertext NOT returned)."""
    enc_key = generate_key()
    fake_rec = CredentialRecord(
        active_provider="anthropic",
        anthropic_key_ciphertext=encrypt_secret("sk-ant-real", key=enc_key),
        openai_key_ciphertext=None,
        openai_base_url=None,
        openai_model=None,
    )
    async with await _async_client() as client:
        with patch(
            "ara.api.routes.get_credentials",
            new=AsyncMock(return_value=fake_rec),
        ):
            resp = await client.get("/api/credentials")

    assert resp.status_code == 200
    body = resp.json()
    # key must NOT be present anywhere in the response
    assert "sk-ant-real" not in resp.text
    assert "ciphertext" not in resp.text
    assert body["active_provider"] == "anthropic"
    assert body["anthropic_configured"] is True
    assert body["openai"]["configured"] is False


async def test_get_credentials_openai_configured() -> None:
    """GET /api/credentials shows openai metadata but NOT the stored key."""
    enc_key = generate_key()
    fake_rec = CredentialRecord(
        active_provider="openai",
        anthropic_key_ciphertext=None,
        openai_key_ciphertext=encrypt_secret("sk-openai-real", key=enc_key),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    async with await _async_client() as client:
        with patch(
            "ara.api.routes.get_credentials",
            new=AsyncMock(return_value=fake_rec),
        ):
            resp = await client.get("/api/credentials")

    assert resp.status_code == 200
    body = resp.json()
    assert "sk-openai-real" not in resp.text
    assert body["openai"]["configured"] is True
    assert body["openai"]["base_url"] == "https://api.openai.com/v1"
    assert body["openai"]["model"] == "gpt-4o"


# ---------------------------------------------------------------------------
# GET /api/quota includes Tavily fields
# ---------------------------------------------------------------------------


async def test_get_quota_includes_tavily_fields() -> None:
    """GET /api/quota response now includes tavily_used, tavily_cap, tavily_cap_reached."""
    fake_quota = QuotaOk(used=1, limit=3, global_spend_usd=0.10, global_cap_usd=20.0)
    fake_tavily = TavilyCapStatus(used=5, cap=1000)

    async with await _async_client() as client:
        with (
            patch("ara.api.routes.check_free_tier", new=AsyncMock(return_value=fake_quota)),
            patch("ara.api.routes.check_tavily_cap", new=AsyncMock(return_value=fake_tavily)),
        ):
            resp = await client.get("/api/quota")

    assert resp.status_code == 200
    body = resp.json()
    assert "tavily_used" in body
    assert "tavily_cap" in body
    assert "tavily_cap_reached" in body
    assert body["tavily_used"] == 5
    assert body["tavily_cap"] == 1000
    assert body["tavily_cap_reached"] is False


# ---------------------------------------------------------------------------
# create_research — storage-resolved BYOK
# ---------------------------------------------------------------------------


async def test_create_research_with_openai_active_builds_correct_overrides() -> None:
    """POST /api/research uses stored OpenAI creds (not a header)."""
    enc_key = generate_key()
    fake_rec = CredentialRecord(
        active_provider="openai",
        anthropic_key_ciphertext=None,
        openai_key_ciphertext=encrypt_secret("sk-openai-stored", key=enc_key),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    fake_tavily = TavilyCapStatus(used=0, cap=1000)

    captured: dict[str, Any] = {}
    done = asyncio.Event()

    async def fake_run_report(**kwargs: Any) -> None:
        captured["overrides"] = kwargs["overrides"]
        done.set()

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: _TEST_USER
    app.dependency_overrides[get_settings] = lambda: Settings(ara_encryption_key=enc_key)
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    with (
        patch("ara.api.routes.get_credentials", new=AsyncMock(return_value=fake_rec)),
        patch("ara.api.routes.check_tavily_cap", new=AsyncMock(return_value=fake_tavily)),
        patch("ara.api.routes.run_report", fake_run_report),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/research",
                json={"question": "q", "depth": "standard", "browse_web": True},
            )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    assert resp.status_code == 200
    ov = captured["overrides"]
    assert ov.provider == "openai"
    assert ov.base_url == "https://api.openai.com/v1"
    assert ov.api_key == "sk-openai-stored"
    assert ov.planner_model == ov.researcher_model == ov.synthesizer_model == "gpt-4o"


async def test_create_research_with_anthropic_active_builds_correct_overrides() -> None:
    """POST /api/research uses stored Anthropic creds (no X-Anthropic-Key header)."""
    enc_key = generate_key()
    fake_rec = CredentialRecord(
        active_provider="anthropic",
        anthropic_key_ciphertext=encrypt_secret("sk-ant-stored", key=enc_key),
        openai_key_ciphertext=None,
        openai_base_url=None,
        openai_model=None,
    )

    captured: dict[str, Any] = {}
    done = asyncio.Event()

    async def fake_run_report(**kwargs: Any) -> None:
        captured["overrides"] = kwargs["overrides"]
        done.set()

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: _TEST_USER
    app.dependency_overrides[get_settings] = lambda: Settings(ara_encryption_key=enc_key)
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    with (
        patch("ara.api.routes.get_credentials", new=AsyncMock(return_value=fake_rec)),
        patch("ara.api.routes.run_report", fake_run_report),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/research",
                json={"question": "q"},
            )
        await asyncio.wait_for(done.wait(), timeout=2.0)

    assert resp.status_code == 200
    ov = captured["overrides"]
    assert ov.api_key == "sk-ant-stored"
    assert ov.provider in (None, "anthropic")  # default is anthropic/None


async def test_create_research_corrupt_ciphertext_returns_400() -> None:
    """POST /api/research when stored ciphertext is corrupt → 400."""
    enc_key = generate_key()
    bad_key = generate_key()  # different key → decrypt failure

    fake_rec = CredentialRecord(
        active_provider="anthropic",
        # Encrypted with bad_key but resolver will try enc_key → CredentialDecryptError
        anthropic_key_ciphertext=encrypt_secret("sk-ant-stored", key=bad_key),
        openai_key_ciphertext=None,
        openai_base_url=None,
        openai_model=None,
    )

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_settings] = lambda: Settings(ara_encryption_key=enc_key)
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    with patch("ara.api.routes.get_credentials", new=AsyncMock(return_value=fake_rec)):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/research",
                json={"question": "q"},
            )

    assert resp.status_code == 400
    assert "credential" in resp.json()["detail"].lower()


async def test_create_research_free_tier_path_unchanged() -> None:
    """POST /api/research with no stored creds → free-tier Haiku path."""
    fake_quota = QuotaOk(used=1, limit=3, global_spend_usd=0.10, global_cap_usd=20.0)

    captured: dict[str, Any] = {}
    done = asyncio.Event()

    async def fake_run_report(**kwargs: Any) -> None:
        captured["overrides"] = kwargs["overrides"]
        done.set()

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _TEST_USER
    app.dependency_overrides[get_optional_user] = lambda: _TEST_USER
    # Provide a server-side anthropic_api_key so free tier is available
    app.dependency_overrides[get_settings] = lambda: Settings(
        anthropic_api_key="sk-ant-free-tier",
        ara_encryption_key="",
    )
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    with (
        patch("ara.api.routes.get_credentials", new=AsyncMock(return_value=None)),
        patch("ara.api.routes.check_free_tier", new=AsyncMock(return_value=fake_quota)),
        patch("ara.api.routes.run_report", fake_run_report),
    ):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/research", json={"question": "q"})
        await asyncio.wait_for(done.wait(), timeout=2.0)

    assert resp.status_code == 200
    ov = captured["overrides"]
    # Free tier uses Haiku
    assert "haiku" in ov.planner_model.lower()


# ---------------------------------------------------------------------------
# Endpoint auth guards (unauthenticated → 401)
# ---------------------------------------------------------------------------


async def test_credential_endpoints_require_auth() -> None:
    """Credential endpoints must reject unauthenticated requests."""
    app = create_app()

    async def raise_401() -> User:
        raise HTTPException(status_code=401, detail="Not authenticated")

    app.dependency_overrides[get_current_user] = raise_401
    app.state.db_pool = object()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp_get = await client.get("/api/credentials")
        assert resp_get.status_code == 401

        resp_put_ant = await client.put(
            "/api/credentials/anthropic", json={"key": "sk"}
        )
        assert resp_put_ant.status_code == 401

        resp_put_oai = await client.put(
            "/api/credentials/openai",
            json={"key": "sk", "base_url": "https://x", "model": "m"},
        )
        assert resp_put_oai.status_code == 401

        resp_active = await client.put(
            "/api/credentials/active", json={"provider": "free"}
        )
        assert resp_active.status_code == 401
