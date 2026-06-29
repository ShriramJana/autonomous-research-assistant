"""Tests for credentials.py — encrypted credential store + Tavily cap accounting.

Pure-logic tests run always; DB-gated tests skip when SUPABASE_DB_URL is absent.
"""

from __future__ import annotations

from uuid import uuid4

import asyncpg
import pytest

from ara.config import Settings
from ara.credentials import (
    CredentialError,
    CredentialRecord,
    TavilyCapStatus,
    check_tavily_cap,
    clear_anthropic,
    get_credentials,
    set_active,
    upsert_anthropic,
    upsert_openai,
)
from tests.conftest import requires_db

# ---------------------------------------------------------------------------
# Pure-logic tests (always run)
# ---------------------------------------------------------------------------


def test_tavily_cap_reached_property() -> None:
    assert TavilyCapStatus(used=1000, cap=1000).reached is True
    assert TavilyCapStatus(used=1001, cap=1000).reached is True
    assert TavilyCapStatus(used=999, cap=1000).reached is False


def test_credential_record_is_frozen() -> None:
    rec = CredentialRecord(
        active_provider="free",
        anthropic_key_ciphertext=None,
        openai_key_ciphertext=None,
        openai_base_url=None,
        openai_model=None,
    )
    assert rec.active_provider == "free"


# ---------------------------------------------------------------------------
# DB-gated store tests (skip when SUPABASE_DB_URL is absent)
# ---------------------------------------------------------------------------


@requires_db
@pytest.mark.asyncio
async def test_upsert_and_active_flow(db_pool: asyncpg.Pool) -> None:
    uid = uuid4()
    await upsert_anthropic(uid, db_pool, ciphertext="ct-a")
    rec = await get_credentials(uid, db_pool)
    assert rec is not None and rec.anthropic_key_ciphertext == "ct-a"
    await set_active(uid, db_pool, provider="anthropic")
    rec2 = await get_credentials(uid, db_pool)
    assert rec2 is not None and rec2.active_provider == "anthropic"
    with pytest.raises(CredentialError):
        await set_active(uid, db_pool, provider="openai")
    await clear_anthropic(uid, db_pool)
    rec3 = await get_credentials(uid, db_pool)
    assert rec3 is not None and rec3.active_provider == "free"


@requires_db
@pytest.mark.asyncio
async def test_upsert_openai(db_pool: asyncpg.Pool) -> None:
    uid = uuid4()
    await upsert_openai(
        uid, db_pool,
        ciphertext="ct-openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
    )
    rec = await get_credentials(uid, db_pool)
    assert rec is not None
    assert rec.openai_key_ciphertext == "ct-openai"
    assert rec.openai_base_url == "https://api.openai.com/v1"
    assert rec.openai_model == "gpt-4o"


@requires_db
@pytest.mark.asyncio
async def test_check_tavily_cap(db_pool: asyncpg.Pool) -> None:
    settings = Settings()
    status = await check_tavily_cap(db_pool, settings)
    assert isinstance(status.used, int)
    assert status.cap == settings.tavily_global_monthly_cap
    assert isinstance(status.reached, bool)
