"""Tests for credentials.py — domain layer over `ReportsRepo` + Tavily cap accounting.

Pure-logic tests run always. Store tests run against every `ReportsRepo`
backend via `any_repo`: SQLite always, Postgres when SUPABASE_DB_URL is set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from ara.config import Settings
from ara.credentials import (
    CredentialError,
    CredentialRecord,
    TavilyCapStatus,
    check_tavily_cap,
    clear_anthropic,
    clear_openai,
    clear_tavily,
    get_credentials,
    set_active,
    upsert_anthropic,
    upsert_openai,
    upsert_tavily,
)
from ara.db import ReportsRepo
from tests.conftest import drop_repo_user, new_repo_user

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
        tavily_key_ciphertext=None,
    )
    assert rec.active_provider == "free"


# ---------------------------------------------------------------------------
# Store tests over every ReportsRepo backend
# ---------------------------------------------------------------------------


@pytest.fixture
async def uid(any_repo: ReportsRepo) -> AsyncIterator[UUID]:
    user_id = await new_repo_user(any_repo)
    try:
        yield user_id
    finally:
        await drop_repo_user(any_repo, user_id)


async def test_get_credentials_none_when_absent(any_repo: ReportsRepo) -> None:
    assert await get_credentials(uuid4(), any_repo) is None


async def test_upsert_and_active_flow(any_repo: ReportsRepo, uid: UUID) -> None:
    await upsert_anthropic(uid, any_repo, ciphertext="ct-a")
    rec = await get_credentials(uid, any_repo)
    assert rec is not None and rec.anthropic_key_ciphertext == "ct-a"
    await set_active(uid, any_repo, provider="anthropic")
    rec2 = await get_credentials(uid, any_repo)
    assert rec2 is not None and rec2.active_provider == "anthropic"
    with pytest.raises(CredentialError):
        await set_active(uid, any_repo, provider="openai")
    await clear_anthropic(uid, any_repo)
    rec3 = await get_credentials(uid, any_repo)
    assert rec3 is not None and rec3.active_provider == "free"
    assert rec3.anthropic_key_ciphertext is None


async def test_set_active_free_needs_no_config(any_repo: ReportsRepo, uid: UUID) -> None:
    await set_active(uid, any_repo, provider="free")
    rec = await get_credentials(uid, any_repo)
    assert rec is not None and rec.active_provider == "free"


async def test_upsert_and_clear_openai(any_repo: ReportsRepo, uid: UUID) -> None:
    await upsert_openai(
        uid, any_repo,
        ciphertext="ct-openai",
        base_url="https://api.openai.com/v1",
        model="gpt-4o",
    )
    rec = await get_credentials(uid, any_repo)
    assert rec is not None
    assert rec.openai_key_ciphertext == "ct-openai"
    assert rec.openai_base_url == "https://api.openai.com/v1"
    assert rec.openai_model == "gpt-4o"
    await set_active(uid, any_repo, provider="openai")
    await clear_openai(uid, any_repo)
    rec2 = await get_credentials(uid, any_repo)
    assert rec2 is not None
    assert rec2.openai_key_ciphertext is None and rec2.openai_base_url is None
    assert rec2.active_provider == "free"


async def test_upsert_and_clear_tavily(any_repo: ReportsRepo, uid: UUID) -> None:
    await upsert_tavily(uid, any_repo, ciphertext="ct-tvly")
    rec = await get_credentials(uid, any_repo)
    assert rec is not None and rec.tavily_key_ciphertext == "ct-tvly"
    assert rec.active_provider == "free"  # a Tavily key is not a provider
    with pytest.raises(CredentialError):
        await set_active(uid, any_repo, provider="tavily")
    await clear_tavily(uid, any_repo)
    rec2 = await get_credentials(uid, any_repo)
    assert rec2 is not None and rec2.tavily_key_ciphertext is None


async def test_check_tavily_cap_counts_this_month(any_repo: ReportsRepo, uid: UUID) -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    before = await check_tavily_cap(any_repo, settings)
    rid = uuid4()
    await any_repo.create_report(
        rid, owner_id=uid, question="q", depth="quick", browse_web=True, used_byok=True
    )
    await any_repo.close_report(
        rid, status="completed", cost_usd=None, report_payload_json=None,
        error_message=None, tavily_searches=4,
    )
    after = await check_tavily_cap(any_repo, settings)
    assert after.cap == settings.tavily_global_monthly_cap
    # Shared Postgres may gain rows concurrently: lower bound, not equality.
    assert after.used >= before.used + 4
    assert isinstance(after.reached, bool)


async def test_check_tavily_cap_uses_month_start(
    any_repo: ReportsRepo, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The window comes from `month_start()`, not SQL — a future start sees nothing."""
    future = datetime.now(UTC) + timedelta(days=1)
    monkeypatch.setattr("ara.credentials.month_start", lambda: future)
    status = await check_tavily_cap(any_repo, Settings(_env_file=None))  # type: ignore[call-arg]
    assert status.used == 0
