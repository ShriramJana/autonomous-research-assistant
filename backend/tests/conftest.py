"""Shared pytest fixtures — fakes for the Anthropic client surface."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from ara.db import ReportsRepo


def make_usage(input_tokens: int = 10, output_tokens: int = 5) -> MagicMock:
    u = MagicMock()
    u.input_tokens = input_tokens
    u.output_tokens = output_tokens
    return u


class FakeTextStream:
    """Mimics Anthropic's `stream.text_stream` async iterator."""

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def __aiter__(self) -> AsyncIterator[str]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[str]:
        for t in self._tokens:
            yield t


class FakeStream:
    """Mimics Anthropic's `messages.stream()` async context manager."""

    def __init__(
        self,
        *,
        tokens: list[str] | None = None,
        events: list[Any] | None = None,
        final_content: list[Any] | None = None,
        input_tokens: int = 10,
        output_tokens: int = 5,
        stop_reason: str = "end_turn",
    ) -> None:
        self.text_stream = FakeTextStream(tokens or [])
        self._events = events or []
        self._final_content = final_content or []
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._stop_reason = stop_reason

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._event_gen()

    async def _event_gen(self) -> AsyncIterator[Any]:
        for e in self._events:
            yield e

    async def __aenter__(self) -> FakeStream:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_final_message(self) -> MagicMock:
        msg = MagicMock()
        msg.usage = make_usage(self._input_tokens, self._output_tokens)
        msg.content = self._final_content
        msg.stop_reason = self._stop_reason
        return msg


def make_fake_anthropic(
    *,
    create_return: Any = None,
    stream_return: FakeStream | None = None,
) -> MagicMock:
    fake = MagicMock()
    fake.messages = MagicMock()
    fake.messages.create = AsyncMock(return_value=create_return)
    if stream_return is not None:
        fake.messages.stream = MagicMock(return_value=stream_return)
    return fake


# --- Postgres-dependent skip marker (Task 6) ----------------------------------


def _has_db() -> bool:
    return bool(os.environ.get("SUPABASE_DB_URL"))


requires_db = pytest.mark.skipif(not _has_db(), reason="SUPABASE_DB_URL not set")


# --- Shared asyncpg pool fixture (lifted here so multiple test files can use it)


@pytest.fixture
async def db_pool() -> AsyncIterator[object]:
    if not _has_db():
        pytest.skip("SUPABASE_DB_URL not set")
    import asyncpg as _asyncpg

    pool = await _asyncpg.create_pool(
        os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2
    )
    try:
        yield pool
    finally:
        await pool.close()


# --- ReportsRepo over both backends (SQLite always; Postgres under requires_db)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=requires_db)])
async def any_repo(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ReportsRepo]:
    if request.param == "sqlite":
        from ara.db.sqlite import SqliteReportsRepo

        sqlite_repo = await SqliteReportsRepo.open(str(tmp_path / "ara.db"))
        try:
            yield sqlite_repo
        finally:
            await sqlite_repo.close()
        return
    import asyncpg as _asyncpg

    from ara.db.postgres import PostgresReportsRepo

    pool = await _asyncpg.create_pool(os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2)
    assert pool is not None
    try:
        yield PostgresReportsRepo(pool)
    finally:
        await pool.close()


async def new_repo_user(repo: ReportsRepo) -> UUID:
    """A fresh user id; on Postgres also an `auth.users` row (FK target)."""
    uid = uuid4()
    pool = getattr(repo, "pool", None)
    if pool is not None:
        async with pool.acquire() as conn:
            await conn.execute(
                """insert into auth.users (id, instance_id, aud, role, email,
                   encrypted_password, email_confirmed_at, created_at, updated_at)
                   values ($1, '00000000-0000-0000-0000-000000000000', 'authenticated',
                   'authenticated', $2, '', now(), now(), now())""",
                uid, f"{uid}@test.local",
            )
    return uid


async def drop_repo_user(repo: ReportsRepo, uid: UUID) -> None:
    """Remove a user made by `new_repo_user` (cascades reports + credentials)."""
    pool = getattr(repo, "pool", None)
    if pool is not None:
        async with pool.acquire() as conn:
            await conn.execute("delete from auth.users where id = $1", uid)
