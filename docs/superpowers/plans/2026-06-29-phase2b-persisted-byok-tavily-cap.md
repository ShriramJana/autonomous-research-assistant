# Phase 2b — Persisted BYOK + Tavily Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move provider credentials into encrypted per-user Supabase storage managed from Settings; every run uses the user's single *active* saved credential; add a global monthly Tavily search cap that degrades OpenAI runs to offline when exhausted.

**Architecture:** A new `user_credentials` table (one row per user) holds Fernet-encrypted keys + a `active_provider` selector. `crypto.py` encrypts/decrypts; `credentials.py` is the asyncpg store; a pure `resolve_overrides` maps the active credential → the same `RuntimeOverrides` 2a already consumes. `create_research` resolves from storage instead of headers/body. Tavily searches are counted per run (threaded callback) and stored on `reports.tavily_searches`; the cap sums them monthly and forces web search off for OpenAI runs when reached. Frontend Settings manages credentials; the run form drops all provider/key fields.

**Tech Stack:** Python 3.11 / FastAPI / Pydantic v2 / asyncpg / LangGraph / `cryptography` (Fernet, already present) backend; Next.js 15 / TypeScript strict / Tailwind frontend; Supabase Postgres.

## Global Constraints

- **Reuse 2a's engine unchanged:** `build_client`, `AnthropicClient`/`OpenAICompatClient`, the researcher Tavily loop, and `RuntimeOverrides(provider, base_url)`. Only the *source* of provider config changes (request → storage).
- **Saved-only, single active provider:** `active_provider ∈ {'free','anthropic','openai'}`. The run form has no provider/key fields. The `X-Anthropic-Key` / `X-Provider-Key` headers and `CreateResearchRequest`'s `provider`/`base_url`/`model` fields are **removed**.
- **Encryption:** app-level Fernet; secret in `ARA_ENCRYPTION_KEY` (root `.env`); ciphertext stored in Supabase. No new dependency. Credential endpoints return **503** when the key is unset.
- **Keys are never returned to the client.** `GET /api/credentials` echoes only configured-booleans + non-secret `base_url`/`model`.
- **Tavily cap is global only**, default `1000`/month; when reached, OpenAI+search runs **degrade to offline** (force `web_search_enabled=False`), never blocked. Anthropic runs unaffected.
- **Decrypt failure** at run start → clear 4xx ("re-save your key"), run not started.
- **Tooling gates pass on every commit:** `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`; frontend `npm run lint && npx tsc --noEmit && npm test && npm run build`. DB-dependent tests use the existing `requires_db` marker (`tests/conftest.py`) and the pool fixture pattern in `tests/test_supabase_store.py`.
- **Conventional Commits, NO `Co-Authored-By:` lines.** Commit per task.
- **Migrations** are idempotent SQL in `backend/migrations/`, applied manually (Supabase SQL editor / psql) — same as `001_initial.sql`.

## File map

**Created:**
- `backend/migrations/002_credentials.sql` — `user_credentials` table + `reports.tavily_searches` column + RLS.
- `backend/src/ara/crypto.py` — Fernet encrypt/decrypt + errors.
- `backend/src/ara/credentials.py` — `CredentialRecord`, store fns, `check_tavily_cap`, `TavilyCapStatus`, `CredentialError`.
- `backend/src/ara/runtime/resolver.py` — pure `resolve_overrides(...)`.
- `backend/tests/test_crypto.py`, `test_credentials.py`, `test_resolver.py`, `test_credentials_api.py`
- `frontend/lib/credentials.ts` — typed client for the credential endpoints.

**Modified:**
- `backend/src/ara/config.py` — `ara_encryption_key`, `tavily_global_monthly_cap`.
- `backend/src/ara/storage/base.py`, `storage/memory.py`, `storage/supabase.py` — `close(..., tavily_searches=0)`.
- `backend/src/ara/runtime/orchestrator.py` — count Tavily searches, store on close.
- `backend/src/ara/graph/dag.py` — thread `on_tavily_search`.
- `backend/src/ara/agents/researcher.py` — accept + call `on_tavily_search`.
- `backend/src/ara/api/routes.py` — credential endpoints, quota extension, `create_research` rework, request-model changes.
- `backend/tests/test_orchestrator.py`, `test_researcher.py`, `test_api.py` — adapt.
- `frontend/app/settings/page.tsx` — server-backed credential UI + active radio + tavily notice.
- `frontend/components/research-form.tsx` — remove provider fields.
- `frontend/lib/api.ts` — drop `X-Anthropic-Key` header + provider options in `createResearch`.
- `frontend/lib/api-key.ts` — deleted (localStorage retired).

---

## Task 1: Encryption module + settings + migration

**Files:**
- Create: `backend/migrations/002_credentials.sql`, `backend/src/ara/crypto.py`, `backend/tests/test_crypto.py`
- Modify: `backend/src/ara/config.py:17-21,43-45`
- Test: `backend/tests/test_crypto.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces:
  - `encrypt_secret(plaintext: str, *, key: str) -> str`
  - `decrypt_secret(token: str, *, key: str) -> str` (raises `CredentialDecryptError`)
  - `class CredentialDecryptError(Exception)`
  - `generate_key() -> str` (helper for ops/tests)
  - `Settings.ara_encryption_key: str = ""`, `Settings.tavily_global_monthly_cap: int = 1000`

- [ ] **Step 1: Write the failing crypto test** — create `backend/tests/test_crypto.py`:

```python
from __future__ import annotations

import pytest

from ara.crypto import (
    CredentialDecryptError,
    decrypt_secret,
    encrypt_secret,
    generate_key,
)

KEY = "tF8m4Q7nQ4t0r6m2yq3uVtR1pXzJ0aB2cD4eF6gH8I="  # a valid 32-byte urlsafe-b64 Fernet key


def test_round_trip() -> None:
    token = encrypt_secret("sk-secret-123", key=KEY)
    assert token != "sk-secret-123"
    assert decrypt_secret(token, key=KEY) == "sk-secret-123"


def test_decrypt_tampered_raises() -> None:
    token = encrypt_secret("x", key=KEY)
    with pytest.raises(CredentialDecryptError):
        decrypt_secret(token + "garbage", key=KEY)


def test_decrypt_wrong_key_raises() -> None:
    token = encrypt_secret("x", key=KEY)
    other = generate_key()
    with pytest.raises(CredentialDecryptError):
        decrypt_secret(token, key=other)


def test_generate_key_is_usable() -> None:
    k = generate_key()
    assert decrypt_secret(encrypt_secret("y", key=k), key=k) == "y"
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_crypto.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.crypto`).

- [ ] **Step 3: Implement `crypto.py`**

```python
"""App-level symmetric encryption for stored provider credentials.

Fernet (AES-128-CBC + HMAC) with a server-held key from `ARA_ENCRYPTION_KEY`.
Ciphertext is stored in Supabase; plaintext keys never leave the backend.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CredentialDecryptError(Exception):
    """Stored ciphertext could not be decrypted (tampered or wrong/rotated key)."""


def generate_key() -> str:
    """Return a fresh urlsafe-base64 Fernet key (for ops / tests)."""
    return Fernet.generate_key().decode("ascii")


def encrypt_secret(plaintext: str, *, key: str) -> str:
    token = Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(token: str, *, key: str) -> str:
    try:
        return Fernet(key.encode("ascii")).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CredentialDecryptError(str(exc)) from exc
```

- [ ] **Step 4: Run crypto test — verify pass**

Run: `cd backend && uv run pytest tests/test_crypto.py -q`
Expected: PASS.

- [ ] **Step 5: Add the settings fields** — in `backend/src/ara/config.py`, after the Tavily key (line ~21) and in the free-tier block (line ~45):

```python
    # Tavily (server-provided client-side search for non-Anthropic providers)
    tavily_api_key: str = Field(default="")
    tavily_global_monthly_cap: int = 1000
```

```python
    # Credential storage (Fernet key for encrypting saved provider keys)
    ara_encryption_key: str = Field(default="")
```

- [ ] **Step 6: Add a settings defaults test** — append to `backend/tests/test_config.py`:

```python
def test_settings_2b_defaults() -> None:
    from ara.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.ara_encryption_key == ""
    assert s.tavily_global_monthly_cap == 1000
```

- [ ] **Step 7: Create the migration** — `backend/migrations/002_credentials.sql`:

```sql
-- Phase 2b: encrypted per-user provider credentials + Tavily usage accounting.
-- Idempotent. Apply via Supabase SQL editor or psql, like 001_initial.sql.

create table if not exists user_credentials (
  user_id                   uuid primary key references auth.users(id) on delete cascade,
  active_provider           text not null default 'free'
                              check (active_provider in ('free','anthropic','openai')),
  anthropic_key_ciphertext  text,
  openai_key_ciphertext     text,
  openai_base_url           text,
  openai_model              text,
  updated_at                timestamptz not null default now()
);

alter table reports
  add column if not exists tavily_searches int not null default 0;

alter table user_credentials enable row level security;

drop policy if exists user_credentials_own on user_credentials;
create policy user_credentials_own on user_credentials
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

- [ ] **Step 8: Run gates**

Run: `cd backend && uv run pytest tests/test_crypto.py tests/test_config.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd backend && git add -A
git commit -m "feat(crypto): Fernet credential encryption + 2b settings + migration 002"
```

---

## Task 2: Credential store (`credentials.py`)

**Files:**
- Create: `backend/src/ara/credentials.py`, `backend/tests/test_credentials.py`

**Interfaces:**
- Consumes: nothing new (asyncpg pool).
- Produces:
  - `@dataclass(frozen=True) class CredentialRecord: active_provider: str; anthropic_key_ciphertext: str | None; openai_key_ciphertext: str | None; openai_base_url: str | None; openai_model: str | None`
  - `@dataclass(frozen=True) class TavilyCapStatus: used: int; cap: int` with `@property reached -> bool`
  - `class CredentialError(Exception)`
  - `async def get_credentials(user_id: UUID, pool) -> CredentialRecord | None`
  - `async def upsert_anthropic(user_id: UUID, pool, *, ciphertext: str) -> None`
  - `async def upsert_openai(user_id: UUID, pool, *, ciphertext: str, base_url: str, model: str) -> None`
  - `async def clear_anthropic(user_id: UUID, pool) -> None`
  - `async def clear_openai(user_id: UUID, pool) -> None`
  - `async def set_active(user_id: UUID, pool, *, provider: str) -> None` (raises `CredentialError` if not configured)
  - `async def check_tavily_cap(pool, settings: Settings) -> TavilyCapStatus`

- [ ] **Step 1: Write the failing pure-logic test** (the DB fns are covered by a `requires_db` test in Step 5; the `reached` property and `CredentialError` are pure) — create `backend/tests/test_credentials.py`:

```python
from __future__ import annotations

from ara.credentials import CredentialRecord, TavilyCapStatus


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
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_credentials.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.credentials`).

- [ ] **Step 3: Implement `credentials.py`**

```python
"""Encrypted per-user provider credentials + Tavily usage accounting.

asyncpg-backed (style of `quota.py`). The store returns ciphertext +
non-secret metadata; decryption happens in the resolver, never here.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import asyncpg

from ara.config import Settings


class CredentialError(Exception):
    """Domain error — e.g. activating a provider that isn't configured."""


@dataclass(frozen=True)
class CredentialRecord:
    active_provider: str
    anthropic_key_ciphertext: str | None
    openai_key_ciphertext: str | None
    openai_base_url: str | None
    openai_model: str | None


@dataclass(frozen=True)
class TavilyCapStatus:
    used: int
    cap: int

    @property
    def reached(self) -> bool:
        return self.used >= self.cap


async def get_credentials(user_id: UUID, pool: asyncpg.Pool) -> CredentialRecord | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "select * from user_credentials where user_id = $1", user_id
        )
    if row is None:
        return None
    return CredentialRecord(
        active_provider=row["active_provider"],
        anthropic_key_ciphertext=row["anthropic_key_ciphertext"],
        openai_key_ciphertext=row["openai_key_ciphertext"],
        openai_base_url=row["openai_base_url"],
        openai_model=row["openai_model"],
    )


async def upsert_anthropic(user_id: UUID, pool: asyncpg.Pool, *, ciphertext: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials (user_id, anthropic_key_ciphertext, updated_at)
            values ($1, $2, now())
            on conflict (user_id) do update
              set anthropic_key_ciphertext = excluded.anthropic_key_ciphertext,
                  updated_at = now()
            """,
            user_id, ciphertext,
        )


async def upsert_openai(
    user_id: UUID, pool: asyncpg.Pool, *, ciphertext: str, base_url: str, model: str
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials
              (user_id, openai_key_ciphertext, openai_base_url, openai_model, updated_at)
            values ($1, $2, $3, $4, now())
            on conflict (user_id) do update
              set openai_key_ciphertext = excluded.openai_key_ciphertext,
                  openai_base_url = excluded.openai_base_url,
                  openai_model = excluded.openai_model,
                  updated_at = now()
            """,
            user_id, ciphertext, base_url, model,
        )


async def clear_anthropic(user_id: UUID, pool: asyncpg.Pool) -> None:
    await _clear(user_id, pool, columns=["anthropic_key_ciphertext"], provider="anthropic")


async def clear_openai(user_id: UUID, pool: asyncpg.Pool) -> None:
    await _clear(
        user_id, pool,
        columns=["openai_key_ciphertext", "openai_base_url", "openai_model"],
        provider="openai",
    )


async def _clear(
    user_id: UUID, pool: asyncpg.Pool, *, columns: list[str], provider: str
) -> None:
    sets = ", ".join(f"{c} = null" for c in columns)
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            update user_credentials
            set {sets},
                active_provider = case when active_provider = $2 then 'free'
                                       else active_provider end,
                updated_at = now()
            where user_id = $1
            """,
            user_id, provider,
        )


async def set_active(user_id: UUID, pool: asyncpg.Pool, *, provider: str) -> None:
    if provider == "free":
        await _force_active(user_id, pool, provider="free")
        return
    rec = await get_credentials(user_id, pool)
    configured = rec is not None and (
        (provider == "anthropic" and rec.anthropic_key_ciphertext is not None)
        or (provider == "openai" and rec.openai_key_ciphertext is not None)
    )
    if not configured:
        raise CredentialError(f"{provider} is not configured")
    await _force_active(user_id, pool, provider=provider)


async def _force_active(user_id: UUID, pool: asyncpg.Pool, *, provider: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            insert into user_credentials (user_id, active_provider, updated_at)
            values ($1, $2, now())
            on conflict (user_id) do update
              set active_provider = excluded.active_provider, updated_at = now()
            """,
            user_id, provider,
        )


async def check_tavily_cap(pool: asyncpg.Pool, settings: Settings) -> TavilyCapStatus:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select coalesce(sum(tavily_searches), 0)::int as n from reports
            where created_at >= date_trunc('month', now())
            """,
        )
    used = row["n"] if row else 0
    return TavilyCapStatus(used=used, cap=settings.tavily_global_monthly_cap)
```

- [ ] **Step 4: Run pure test — verify pass**

Run: `cd backend && uv run pytest tests/test_credentials.py -q`
Expected: PASS.

- [ ] **Step 5: Add DB-gated store tests** — append to `backend/tests/test_credentials.py`, following the pool fixture pattern in `tests/test_supabase_store.py` (read it first to reuse its `db_pool` fixture / `requires_db` import). The tests must, against a real DB: upsert+get an Anthropic key; upsert+get an OpenAI config; `set_active('anthropic')` succeeds only when configured (else `CredentialError`); `clear_anthropic` resets `active_provider` to `'free'` when it was active; `check_tavily_cap` sums the current month. Use the existing `requires_db` marker so they skip without `SUPABASE_DB_URL`. Example shape (adapt to the file's fixture):

```python
import pytest
from uuid import uuid4
from ara.config import Settings
from ara.credentials import (
    CredentialError, check_tavily_cap, clear_anthropic, get_credentials,
    set_active, upsert_anthropic, upsert_openai,
)
from tests.conftest import requires_db


@requires_db
async def test_upsert_and_active_flow(db_pool) -> None:  # db_pool from test_supabase_store pattern
    uid = uuid4()
    await upsert_anthropic(uid, db_pool, ciphertext="ct-a")
    rec = await get_credentials(uid, db_pool)
    assert rec is not None and rec.anthropic_key_ciphertext == "ct-a"
    await set_active(uid, db_pool, provider="anthropic")
    assert (await get_credentials(uid, db_pool)).active_provider == "anthropic"
    with pytest.raises(CredentialError):
        await set_active(uid, db_pool, provider="openai")
    await clear_anthropic(uid, db_pool)
    assert (await get_credentials(uid, db_pool)).active_provider == "free"
```

(If `test_supabase_store.py` has no reusable `db_pool` fixture, lift its pool-creation into `conftest.py` as a fixture and use it in both files — note that as a small refactor in your report.)

- [ ] **Step 6: Run gates**

Run: `cd backend && uv run pytest tests/test_credentials.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS (DB tests skip if no `SUPABASE_DB_URL`).

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A
git commit -m "feat(credentials): encrypted credential store + Tavily cap accounting"
```

---

## Task 3: `tavily_searches` on `ReportStore.close` + both impls

**Files:**
- Modify: `backend/src/ara/storage/base.py:43-53`, `storage/memory.py:36-39,82-100`, `storage/supabase.py:116-139`
- Test: `backend/tests/test_orchestrator.py` (memory store, via Task 4) / `test_supabase_store.py` (DB-gated)

**Interfaces:**
- Produces: `ReportStore.close(..., tavily_searches: int = 0)`; `InMemoryReportStore` exposes the value on `get_state(...).tavily_searches`.

- [ ] **Step 1: Write the failing memory-store test** — append to `backend/tests/test_storage.py` (uses `InMemoryReportStore`):

```python
async def test_close_records_tavily_searches() -> None:
    from uuid import uuid4
    from ara.storage.memory import InMemoryReportStore

    store = InMemoryReportStore()
    rid, owner = uuid4(), uuid4()
    await store.create(rid, "q", owner_id=owner, depth="quick", browse_web=False, used_byok=False)
    await store.close(rid, status="completed", tavily_searches=7)
    state = store.get_state(rid)
    assert state is not None
    assert state.tavily_searches == 7
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_storage.py::test_close_records_tavily_searches -q`
Expected: FAIL (`close() got an unexpected keyword argument 'tavily_searches'`).

- [ ] **Step 3: Update the Protocol** — `storage/base.py`, add the param to `close`:

```python
    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
        tavily_searches: int = 0,
    ) -> None:
        ...
```

- [ ] **Step 4: Update `InMemoryReportStore`** — add `tavily_searches: int = 0` to `_ReportState` (after `error_message`) and set it in `close`:

```python
@dataclass
class _ReportState:
    # ... existing fields ...
    error_message: str | None = None
    tavily_searches: int = 0
```

```python
    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
        tavily_searches: int = 0,
    ) -> None:
        state = self._reports.get(report_id)
        if state is None or state.closed:
            return
        state.closed = True
        state.status = status
        state.cost_usd = cost_usd
        state.report_payload = report_payload
        state.error_message = error_message
        state.tavily_searches = tavily_searches
        for q in list(state.live_queues):
            await q.put(None)
```

- [ ] **Step 5: Update `SupabaseReportStore.close`** — add the param and persist the column:

```python
    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
        tavily_searches: int = 0,
    ) -> None:
        payload_json = report_payload.model_dump_json() if report_payload else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update reports
                set status = $2, cost_usd = $3, report_payload = $4::jsonb,
                    error_message = $5, tavily_searches = $6, completed_at = now()
                where id = $1
                """,
                report_id, status, cost_usd, payload_json, error_message, tavily_searches,
            )
        subs = self._subs.get(report_id)
        if subs is None or subs.closed:
            return
        subs.closed = True
        for q in list(subs.queues):
            await q.put(None)
```

- [ ] **Step 6: Run gates**

Run: `cd backend && uv run pytest tests/test_storage.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd backend && git add -A
git commit -m "feat(storage): persist tavily_searches on report close"
```

---

## Task 4: Count Tavily searches end-to-end

Thread an `on_tavily_search` callback from the orchestrator through the graph into the researcher's Tavily loop, and store the total on close.

**Files:**
- Modify: `backend/src/ara/agents/researcher.py:155-168,186-196,245-322`, `graph/dag.py:42-101`, `runtime/orchestrator.py:45-96`
- Test: `backend/tests/test_researcher.py`, `backend/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `store.close(..., tavily_searches=...)` (Task 3).
- Produces:
  - `research_sub_query(..., on_tavily_search: OnTavilySearch | None = None)` where `OnTavilySearch = Callable[[], Awaitable[None]]` (define in `researcher.py`).
  - `build_graph(..., on_tavily_search: OnTavilySearch | None = None)`.

- [ ] **Step 1: Write the failing researcher test** — append to `backend/tests/test_researcher.py` (reuses `_ScriptedLLM`, `_tu`, `_result`, `_make_emit` already in the file):

```python
async def test_tavily_loop_invokes_on_tavily_search(monkeypatch: Any) -> None:
    from ara.agents import researcher as researcher_mod

    async def fake_tavily(query: str, *, api_key: str | None, max_results: int = 5) -> list[Any]:
        return []

    monkeypatch.setattr(researcher_mod, "tavily_search", fake_tavily)

    counter = {"n": 0}

    async def on_search() -> None:
        counter["n"] += 1

    sq = SubQuery(question="q", rationale="r", priority=Priority.MEDIUM)
    llm = _ScriptedLLM(
        [
            _result(tool_uses=[_tu("web_search", {"query": "a"}), _tu("web_search", {"query": "b"})]),
            _result(
                tool_uses=[
                    _tu(
                        SUBMIT_FINDING_TOOL_NAME,
                        {
                            "summary": "s",
                            "key_facts": [{"statement": "x", "source_urls": ["https://a.com"]}],
                            "sources": [{"url": "https://a.com", "title": "A"}],
                        },
                    )
                ]
            ),
        ]
    )
    emit, _ = _make_emit()
    await research_sub_query(
        sub_query=sq, llm=llm, model="gpt-4o", emit=emit,
        tavily_api_key="k", on_tavily_search=on_search,
    )
    assert counter["n"] == 2  # one per web_search call
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_researcher.py::test_tavily_loop_invokes_on_tavily_search -q`
Expected: FAIL (`research_sub_query() got an unexpected keyword argument 'on_tavily_search'`).

- [ ] **Step 3: Thread the callback in `researcher.py`** — add the type alias near the top imports:

```python
from collections.abc import Awaitable, Callable

OnTavilySearch = Callable[[], Awaitable[None]]
```

Add `on_tavily_search: OnTavilySearch | None = None` to `research_sub_query`'s signature (after `tavily_api_key`) and pass it into the `_research_with_tavily(...)` call:

```python
    if web_search_enabled and not llm.supports_server_side_search:
        return await _research_with_tavily(
            sub_query=sub_query,
            llm=llm,
            model=model,
            emit=emit,
            max_iterations=max_iterations,
            input_token_budget=input_token_budget,
            max_tokens=max_tokens,
            tavily_api_key=tavily_api_key,
            on_tavily_search=on_tavily_search,
        )
```

Add the param to `_research_with_tavily` (after `tavily_api_key`) and invoke it once per search, right before the `tavily_search` call:

```python
async def _research_with_tavily(
    *,
    sub_query: SubQuery,
    llm: LLMClient,
    model: str,
    emit: EventEmitter,
    max_iterations: int,
    input_token_budget: int,
    max_tokens: int,
    tavily_api_key: str | None,
    on_tavily_search: OnTavilySearch | None = None,
) -> SubQueryFinding:
    ...
        for tu in searches:
            query = tu.input.get("query", "") if isinstance(tu.input, dict) else ""
            await emit(
                ResearcherProgress(
                    sub_query_id=sub_query.id,
                    tool_call=f"{WEB_SEARCH_CLIENT_TOOL_NAME}({query!r})",
                )
            )
            if on_tavily_search is not None:
                await on_tavily_search()
            rows = await tavily_search(query, api_key=tavily_api_key)
            messages.append(
                {"role": "tool", "tool_call_id": tu.id, "content": format_search_results(rows)}
            )
```

- [ ] **Step 4: Run researcher test — verify pass**

Run: `cd backend && uv run pytest tests/test_researcher.py::test_tavily_loop_invokes_on_tavily_search -q`
Expected: PASS.

- [ ] **Step 5: Thread through `build_graph`** — `graph/dag.py`: add `on_tavily_search: OnTavilySearch | None = None` to `build_graph`'s signature (import the type: `from ara.agents.researcher import OnTavilySearch`) and pass it into the `research_sub_query(...)` call in `run_one`:

```python
                finding = await research_sub_query(
                    sub_query=sq,
                    llm=llm,
                    model=models.researcher,
                    emit=emit,
                    max_iterations=opts.max_iterations,
                    input_token_budget=settings.ara_researcher_input_token_budget,
                    web_search_enabled=opts.web_search_enabled,
                    tavily_api_key=settings.tavily_api_key,
                    on_tavily_search=on_tavily_search,
                )
```

- [ ] **Step 6: Count + store in the orchestrator** — `runtime/orchestrator.py`: add a counter and callback, pass to `build_graph`, and store on close. Add after `cumulative_usd = 0.0`:

```python
    cumulative_usd = 0.0
    tavily_searches = 0
    final_report: ReportEnvelope | None = None
```

Add the callback near `on_api_call`:

```python
    async def on_tavily_search() -> None:
        nonlocal tavily_searches
        tavily_searches += 1
```

Pass it to `build_graph`:

```python
    graph = build_graph(
        llm=llm, emit=emit, settings=settings, models=models,
        options=overrides.options, on_tavily_search=on_tavily_search,
    )
```

Persist on close:

```python
    finally:
        await store.close(
            report_id,
            status=status,
            cost_usd=cumulative_usd,
            report_payload=final_report,
            error_message=error_message,
            tavily_searches=tavily_searches,
        )
```

- [ ] **Step 7: Write the failing orchestrator test** — append to `backend/tests/test_orchestrator.py`. It patches `research_sub_query` with a fake that calls `on_tavily_search` twice, then asserts the stored count:

```python
async def test_pipeline_records_tavily_search_count() -> None:
    from ara.storage.memory import InMemoryReportStore

    store = InMemoryReportStore()
    report_id = uuid4()
    plan = _plan_with_n(1)
    settings = _settings()

    async def fake_plan(**kwargs: Any) -> ResearchPlan:
        return plan

    async def fake_research(
        *, sub_query: SubQuery, emit: Any, on_tavily_search: Any = None, **kwargs: Any
    ) -> SubQueryFinding:
        if on_tavily_search is not None:
            await on_tavily_search()
            await on_tavily_search()
        src = _source("https://x.com", "x")
        return SubQueryFinding(
            sub_query_id=sub_query.id, summary="s",
            key_facts=[KeyFact(statement="f", citation_ids=[src.id])], sources=[src],
        )

    async def fake_synth(*, emit: Any, **kwargs: Any) -> FinalReport:
        return _fake_final_report(kwargs["report_id"], kwargs["original_question"])

    with (
        patch("ara.graph.dag.plan_research", fake_plan),
        patch("ara.graph.dag.research_sub_query", fake_research),
        patch("ara.graph.dag.synthesize_report", fake_synth),
    ):
        await run_report(
            report_id=report_id, question="top", store=store, settings=settings,
            overrides=_overrides(settings), owner_id=uuid4(),
        )

    state = store.get_state(report_id)
    assert state is not None
    assert state.tavily_searches == 2
```

- [ ] **Step 8: Run gates**

Run: `cd backend && uv run pytest tests/test_researcher.py tests/test_orchestrator.py -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
cd backend && git add -A
git commit -m "feat(runtime): count Tavily searches per run and persist on close"
```

---

## Task 5: Pure credential resolver

Map a `CredentialRecord` (+ decrypt) to the `RuntimeOverrides` 2a consumes, or `None` for the free-tier path. Pure and fully unit-testable (no DB).

**Files:**
- Create: `backend/src/ara/runtime/resolver.py`, `backend/tests/test_resolver.py`

**Interfaces:**
- Consumes: `CredentialRecord` (Task 2), `decrypt_secret`/`CredentialDecryptError` (Task 1), `RuntimeOverrides`, `options_for_depth`, `Settings`.
- Produces: `resolve_overrides(record: CredentialRecord | None, *, settings: Settings, depth: Depth, browse_web: bool, tavily_capped: bool) -> RuntimeOverrides | None` (raises `CredentialError` for a selected-but-unconfigured provider; `CredentialDecryptError` propagates).

- [ ] **Step 1: Write the failing resolver test** — create `backend/tests/test_resolver.py`:

```python
from __future__ import annotations

import pytest

from ara.config import Settings
from ara.credentials import CredentialError, CredentialRecord
from ara.crypto import CredentialDecryptError, encrypt_secret
from ara.runtime.resolver import resolve_overrides

KEY = "tF8m4Q7nQ4t0r6m2yq3uVtR1pXzJ0aB2cD4eF6gH8I="


def _settings() -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.ara_encryption_key = KEY
    s.claude_planner_model = "p"
    s.claude_researcher_model = "r"
    s.claude_synthesizer_model = "syn"
    return s


def _rec(**kw: object) -> CredentialRecord:
    base: dict[str, object] = {
        "active_provider": "free",
        "anthropic_key_ciphertext": None,
        "openai_key_ciphertext": None,
        "openai_base_url": None,
        "openai_model": None,
    }
    base.update(kw)
    return CredentialRecord(**base)  # type: ignore[arg-type]


def test_none_record_is_free_tier() -> None:
    assert resolve_overrides(None, settings=_settings(), depth="standard",
                             browse_web=True, tavily_capped=False) is None


def test_active_free_is_free_tier() -> None:
    assert resolve_overrides(_rec(active_provider="free"), settings=_settings(),
                             depth="standard", browse_web=True, tavily_capped=False) is None


def test_anthropic_uses_per_role_models_and_decrypted_key() -> None:
    s = _settings()
    rec = _rec(active_provider="anthropic", anthropic_key_ciphertext=encrypt_secret("sk-ant", key=KEY))
    ov = resolve_overrides(rec, settings=s, depth="deep", browse_web=True, tavily_capped=False)
    assert ov is not None
    assert ov.provider == "anthropic"
    assert ov.api_key == "sk-ant"
    assert (ov.planner_model, ov.researcher_model, ov.synthesizer_model) == ("p", "r", "syn")
    assert ov.options.web_search_enabled is True


def test_openai_uses_single_model_and_base_url() -> None:
    s = _settings()
    rec = _rec(
        active_provider="openai",
        openai_key_ciphertext=encrypt_secret("sk-oai", key=KEY),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    ov = resolve_overrides(rec, settings=s, depth="standard", browse_web=True, tavily_capped=False)
    assert ov is not None
    assert ov.provider == "openai"
    assert ov.base_url == "https://api.openai.com/v1"
    assert ov.api_key == "sk-oai"
    assert ov.planner_model == ov.researcher_model == ov.synthesizer_model == "gpt-4o"


def test_openai_tavily_capped_forces_search_off() -> None:
    s = _settings()
    rec = _rec(
        active_provider="openai",
        openai_key_ciphertext=encrypt_secret("sk-oai", key=KEY),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    ov = resolve_overrides(rec, settings=s, depth="standard", browse_web=True, tavily_capped=True)
    assert ov is not None
    assert ov.options.web_search_enabled is False


def test_active_but_unconfigured_raises() -> None:
    with pytest.raises(CredentialError):
        resolve_overrides(_rec(active_provider="openai"), settings=_settings(),
                          depth="standard", browse_web=True, tavily_capped=False)


def test_decrypt_failure_propagates() -> None:
    rec = _rec(active_provider="anthropic", anthropic_key_ciphertext="not-a-valid-token")
    with pytest.raises(CredentialDecryptError):
        resolve_overrides(rec, settings=_settings(), depth="standard",
                          browse_web=True, tavily_capped=False)
```

- [ ] **Step 2: Run it — verify it fails**

Run: `cd backend && uv run pytest tests/test_resolver.py -q`
Expected: FAIL (`ModuleNotFoundError: ara.runtime.resolver`).

- [ ] **Step 3: Implement `resolver.py`**

```python
"""Map a stored credential to the RuntimeOverrides the engine consumes.

Pure and synchronous. Returns None to signal the free-tier path (the caller
runs the existing quota + Haiku block). Decryption errors propagate so the
API layer can return a clear 4xx.
"""

from __future__ import annotations

from ara.config import Settings
from ara.credentials import CredentialError, CredentialRecord
from ara.crypto import decrypt_secret
from ara.options import Depth, options_for_depth
from ara.runtime.overrides import RuntimeOverrides


def resolve_overrides(
    record: CredentialRecord | None,
    *,
    settings: Settings,
    depth: Depth,
    browse_web: bool,
    tavily_capped: bool,
) -> RuntimeOverrides | None:
    if record is None or record.active_provider == "free":
        return None

    if record.active_provider == "anthropic":
        if record.anthropic_key_ciphertext is None:
            raise CredentialError("anthropic is active but not configured")
        api_key = decrypt_secret(record.anthropic_key_ciphertext, key=settings.ara_encryption_key)
        return RuntimeOverrides(
            api_key=api_key,
            planner_model=settings.claude_planner_model,
            researcher_model=settings.claude_researcher_model,
            synthesizer_model=settings.claude_synthesizer_model,
            options=options_for_depth(depth, web_search_enabled=browse_web),
        )

    if record.active_provider == "openai":
        if record.openai_key_ciphertext is None or not record.openai_base_url or not record.openai_model:
            raise CredentialError("openai is active but not fully configured")
        api_key = decrypt_secret(record.openai_key_ciphertext, key=settings.ara_encryption_key)
        web = browse_web and not tavily_capped
        return RuntimeOverrides(
            api_key=api_key,
            planner_model=record.openai_model,
            researcher_model=record.openai_model,
            synthesizer_model=record.openai_model,
            options=options_for_depth(depth, web_search_enabled=web),
            provider="openai",
            base_url=record.openai_base_url,
        )

    raise CredentialError(f"unknown active_provider {record.active_provider!r}")
```

- [ ] **Step 4: Run resolver test — verify pass**

Run: `cd backend && uv run pytest tests/test_resolver.py -q`
Expected: PASS.

- [ ] **Step 5: Run gates + commit**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS.

```bash
cd backend && git add -A
git commit -m "feat(runtime): pure credential->overrides resolver"
```

---

## Task 6: API — credential endpoints, quota extension, `create_research` rework

**Files:**
- Modify: `backend/src/ara/api/routes.py` (request models `:40-46`; `QuotaResponse` `:97-102`; `get_quota` `:200-217`; `create_research` `:332-416`; add credential endpoints)
- Test: `backend/tests/test_credentials_api.py` (create), `backend/tests/test_api.py` (adapt)

**Interfaces:**
- Consumes: `get_credentials`, `upsert_anthropic`, `upsert_openai`, `clear_anthropic`, `clear_openai`, `set_active`, `check_tavily_cap`, `CredentialError`, `TavilyCapStatus` (Task 2); `resolve_overrides` (Task 5); `encrypt_secret`, `decrypt_secret`, `CredentialDecryptError` (Task 1).
- Produces: `GET/PUT/DELETE /api/credentials*`, extended `GET /api/quota`, reworked `POST /api/research`.

- [ ] **Step 1: Study the test harness** — read `tests/test_api.py` for its async-client fixture, auth override, and `run_report` patching (the same harness Task 7 of Phase 2a used). New tests mirror it. Most credential endpoints touch the DB, so use `requires_db` for those; the 503-without-encryption-key and the `create_research` resolution can be tested by patching `get_credentials`/`run_report` where possible.

- [ ] **Step 2: Write failing API tests** — create `backend/tests/test_credentials_api.py`. Intent (translate to the file harness in `test_api.py`):

```python
# 1. PUT /api/credentials/anthropic with ARA_ENCRYPTION_KEY unset → 503.
# 2. With key set: PUT anthropic {key} → 204/200; GET /api/credentials →
#    {anthropic_configured: true, active_provider: "free", openai:{configured:false}};
#    the stored ciphertext is NOT the plaintext and never appears in any response body.
# 3. PUT /api/credentials/active {provider:"anthropic"} → 200; GET shows active_provider "anthropic".
# 4. PUT active {provider:"openai"} when openai not configured → 400.
# 5. create_research with active=openai (configured) records overrides.provider == "openai"
#    (capture via patched run_report) — key resolved from storage, NOT a header.
# 6. create_research with a corrupt anthropic ciphertext (active=anthropic) → 4xx.
# 7. GET /api/quota includes tavily_used/tavily_cap/tavily_cap_reached.
```

Write these as concrete tests against the harness (patch `ara.api.routes.get_credentials` to return a `CredentialRecord` for the resolution tests so they need no DB; use `requires_db` for the true store round-trips).

- [ ] **Step 3: Run them — verify they fail**

Run: `cd backend && uv run pytest tests/test_credentials_api.py -q`
Expected: FAIL (endpoints/fields absent).

- [ ] **Step 4: Add request/response models** — in `routes.py`, replace `CreateResearchRequest` and extend `QuotaResponse`, and add credential models:

```python
class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Depth = "standard"
    browse_web: bool = True


class AnthropicKeyRequest(BaseModel):
    key: str = Field(min_length=1)


class OpenAIConfigRequest(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    key: str = Field(min_length=1)


class ActiveProviderRequest(BaseModel):
    provider: Literal["free", "anthropic", "openai"]


class OpenAIConfigStatus(BaseModel):
    configured: bool
    base_url: str | None
    model: str | None


class CredentialsResponse(BaseModel):
    active_provider: Literal["free", "anthropic", "openai"]
    anthropic_configured: bool
    openai: OpenAIConfigStatus


class QuotaResponse(BaseModel):
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float
    circuit_breaker_tripped: bool
    tavily_used: int
    tavily_cap: int
    tavily_cap_reached: bool
```

- [ ] **Step 5: Add a 503 helper + the credential endpoints** — in `routes.py`:

```python
def _encryption_key_or_503(settings: Settings) -> str:
    if not settings.ara_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="Credential storage not configured (set ARA_ENCRYPTION_KEY)",
        )
    return settings.ara_encryption_key


@router.get("/credentials", response_model=CredentialsResponse)
async def get_credentials_route(
    request: Request,
    user: User = Depends(get_current_user),
) -> CredentialsResponse:
    pool = _pool_or_503(request)
    rec = await get_credentials(user.id, pool)
    if rec is None:
        return CredentialsResponse(
            active_provider="free",
            anthropic_configured=False,
            openai=OpenAIConfigStatus(configured=False, base_url=None, model=None),
        )
    return CredentialsResponse(
        active_provider=rec.active_provider,  # type: ignore[arg-type]
        anthropic_configured=rec.anthropic_key_ciphertext is not None,
        openai=OpenAIConfigStatus(
            configured=rec.openai_key_ciphertext is not None,
            base_url=rec.openai_base_url,
            model=rec.openai_model,
        ),
    )


@router.put("/credentials/anthropic", status_code=204)
async def put_anthropic_key(
    req: AnthropicKeyRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    pool = _pool_or_503(request)
    key = _encryption_key_or_503(settings)
    await upsert_anthropic(user.id, pool, ciphertext=encrypt_secret(req.key, key=key))


@router.delete("/credentials/anthropic", status_code=204)
async def delete_anthropic_key(
    request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    await clear_anthropic(user.id, pool)


@router.put("/credentials/openai", status_code=204)
async def put_openai_config(
    req: OpenAIConfigRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    pool = _pool_or_503(request)
    key = _encryption_key_or_503(settings)
    await upsert_openai(
        user.id, pool,
        ciphertext=encrypt_secret(req.key, key=key),
        base_url=req.base_url, model=req.model,
    )


@router.delete("/credentials/openai", status_code=204)
async def delete_openai_config(
    request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    await clear_openai(user.id, pool)


@router.put("/credentials/active", status_code=204)
async def put_active_provider(
    req: ActiveProviderRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    pool = _pool_or_503(request)
    try:
        await set_active(user.id, pool, provider=req.provider)
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Add imports at the top of `routes.py`:

```python
from ara.credentials import (
    CredentialError, check_tavily_cap, clear_anthropic, clear_openai,
    get_credentials, set_active, upsert_anthropic, upsert_openai,
)
from ara.crypto import CredentialDecryptError, encrypt_secret
from ara.runtime.resolver import resolve_overrides
```

(Remove the `Header` import usage for the two retired headers if no longer used elsewhere; keep `Header` import only if still referenced.)

- [ ] **Step 6: Extend `get_quota`** — add the Tavily fields:

```python
@router.get("/quota", response_model=QuotaResponse)
async def get_quota(
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> QuotaResponse:
    pool = _pool_or_503(request)
    status_ = await check_free_tier(user.id, pool, settings)
    tavily = await check_tavily_cap(pool, settings)
    return QuotaResponse(
        used=status_.used,
        limit=status_.limit,
        global_spend_usd=status_.global_spend_usd,
        global_cap_usd=status_.global_cap_usd,
        circuit_breaker_tripped=(
            isinstance(status_, QuotaDenial)
            and status_.reason == "free_tier_global_cap_reached"
        ),
        tavily_used=tavily.used,
        tavily_cap=tavily.cap,
        tavily_cap_reached=tavily.reached,
    )
```

- [ ] **Step 7: Rework `create_research`** — replace the whole handler signature + body (remove the two header params and the provider/body branches; resolve from storage):

```python
@router.post("/research", response_model=CreateResearchResponse)
async def create_research(
    req: CreateResearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> CreateResearchResponse:
    pool = _pool_or_503(request)
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks

    record = await get_credentials(user.id, pool)

    tavily_capped = False
    if record is not None and record.active_provider == "openai" and req.browse_web:
        tavily_capped = (await check_tavily_cap(pool, settings)).reached

    try:
        overrides = resolve_overrides(
            record, settings=settings, depth=req.depth,
            browse_web=req.browse_web, tavily_capped=tavily_capped,
        )
    except CredentialDecryptError:
        raise HTTPException(
            status_code=400,
            detail="Saved credential could not be read — please re-save it in Settings",
        ) from None
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if overrides is None:
        # Free-tier path (unchanged behavior).
        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=503,
                detail="Free tier disabled (server has no ANTHROPIC_API_KEY)",
            )
        quota = await check_free_tier(user.id, pool, settings)
        if isinstance(quota, QuotaDenial):
            return JSONResponse(  # type: ignore[return-value]
                status_code=402,
                content={
                    "error": quota.reason,
                    "message": (
                        "Free-tier monthly limit reached"
                        if quota.reason == "free_tier_exhausted"
                        else "Free tier capped site-wide for this month"
                    ),
                    "used": quota.used,
                    "limit": quota.limit,
                    "global_spend_usd": quota.global_spend_usd,
                    "global_cap_usd": quota.global_cap_usd,
                },
            )
        overrides = RuntimeOverrides(
            api_key=settings.anthropic_api_key,
            planner_model=FREE_TIER_MODEL,
            researcher_model=FREE_TIER_MODEL,
            synthesizer_model=FREE_TIER_MODEL,
            options=options_for_depth("quick", web_search_enabled=False),
        )

    report_id = uuid4()
    task = asyncio.create_task(
        run_report(
            report_id=report_id,
            question=req.question,
            store=store,
            settings=settings,
            overrides=overrides,
            owner_id=user.id,
        )
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return CreateResearchResponse(report_id=report_id)
```

- [ ] **Step 8: Fix any now-broken existing `test_api.py` tests** — the Phase 2a tests that sent `provider`/`base_url`/`model` in the body or `X-Anthropic-Key`/`X-Provider-Key` headers no longer apply. Update/remove them: BYOK is now exercised via stored credentials (patch `ara.api.routes.get_credentials`). Keep the free-tier and quota tests (active=free path). Ensure the suite reflects the new contract.

- [ ] **Step 9: Run gates**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src`
Expected: PASS (DB-gated tests skip without `SUPABASE_DB_URL`).

- [ ] **Step 10: Commit**

```bash
cd backend && git add -A
git commit -m "feat(api): credential endpoints + storage-resolved runs + Tavily cap surface"
```

---

## Task 7: Frontend — Settings credential management

**Files:**
- Create: `frontend/lib/credentials.ts`
- Modify: `frontend/app/settings/page.tsx`, `frontend/lib/api.ts:1-31`
- Delete: `frontend/lib/api-key.ts`

**Interfaces:**
- Consumes: backend credential endpoints (Task 6).
- Produces: `lib/credentials.ts` typed client — `getCredentials()`, `putAnthropicKey(key)`, `deleteAnthropicKey()`, `putOpenAIConfig({baseUrl, model, key})`, `deleteOpenAIConfig()`, `setActiveProvider(provider)`.

- [ ] **Step 1: Create `lib/credentials.ts`**

```typescript
"use client";

import { apiDelete, apiGet, apiPost } from "@/lib/api";

export type ActiveProvider = "free" | "anthropic" | "openai";

export interface CredentialsState {
  active_provider: ActiveProvider;
  anthropic_configured: boolean;
  openai: { configured: boolean; base_url: string | null; model: string | null };
}

export const getCredentials = () => apiGet<CredentialsState>("/api/credentials");

export const putAnthropicKey = (key: string) =>
  apiPut("/api/credentials/anthropic", { key });
export const deleteAnthropicKey = () => apiDelete("/api/credentials/anthropic");

export const putOpenAIConfig = (cfg: { baseUrl: string; model: string; key: string }) =>
  apiPut("/api/credentials/openai", {
    base_url: cfg.baseUrl,
    model: cfg.model,
    key: cfg.key,
  });
export const deleteOpenAIConfig = () => apiDelete("/api/credentials/openai");

export const setActiveProvider = (provider: ActiveProvider) =>
  apiPut("/api/credentials/active", { provider });
```

- [ ] **Step 2: Add `apiPut` to `lib/api.ts`** (the endpoints use PUT) and **remove the `X-Anthropic-Key` header + `getStoredApiKey` import**:

```typescript
import { createSupabaseBrowser } from "@/lib/supabase/client";
// (delete the `import { getStoredApiKey } from "@/lib/api-key";` line)
```

In `authedFetch`, delete the `const key = getStoredApiKey(); if (key) headers.set("X-Anthropic-Key", key);` block. Add a PUT helper next to `apiPost`:

```typescript
export async function apiPut(path: string, body: unknown): Promise<void> {
  const res = await authedFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) await throwOrJson(res);
}
```

- [ ] **Step 3: Rework the Settings page** — in `frontend/app/settings/page.tsx`, replace the localStorage Anthropic section (lines ~133-176) and remove the `lib/api-key` import. Add credential state loaded from `getCredentials()`, with: an Anthropic-key write-only input (Save → `putAnthropicKey`; Clear → `deleteAnthropicKey`); an OpenAI section (base_url/model/key write-only inputs; Save → `putOpenAIConfig`; Clear → `deleteOpenAIConfig`, echoing stored base_url/model when configured); and an **active-provider radio** (`free` / `anthropic` / `openai`, each selectable only when configured) → `setActiveProvider`. After each mutation, re-fetch `getCredentials()`. Show a Tavily notice when `/api/quota`'s `tavily_cap_reached` is true. Match the existing card/section styling. Key inputs are never pre-filled from the server.

(Full JSX is long; follow the existing section markup. The key behaviors above are the contract — keep inputs `value`+`onChange` controlled, password-type for secrets, and disable Save when the relevant inputs are empty.)

- [ ] **Step 4: Delete `frontend/lib/api-key.ts`** and confirm no other file imports it:

```bash
cd frontend && grep -rn "api-key" app components lib hooks || echo "no references"
rm lib/api-key.ts
```

(If the grep finds references other than the ones you've edited — e.g. `research-form.tsx` — those are handled in Task 8; if Task 8 isn't done yet, leave the file until Task 8 and note it. Prefer doing this deletion as the last step after Task 8 if references remain.)

- [ ] **Step 5: Gates**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build`
Expected: PASS (no new lint errors; build OK).

- [ ] **Step 6: Commit**

```bash
cd frontend && git add -A
git commit -m "feat(settings): server-backed encrypted credential management + active provider"
```

---

## Task 8: Frontend — run-form simplification

**Files:**
- Modify: `frontend/components/research-form.tsx`, `frontend/lib/api.ts:73-104`

**Interfaces:**
- Consumes: `getCredentials()` (Task 7) for the free-tier lock.
- Produces: `createResearch(question, {depth, browseWeb})` (provider options removed).

- [ ] **Step 1: Revert `createResearch`** in `lib/api.ts` to the pre-2a body (drop provider/base_url/model/providerKey and the extra-headers logic; `apiPost`'s third arg can stay but is unused here):

```typescript
export interface CreateResearchOptions {
  depth?: Depth;
  browseWeb?: boolean;
}

export async function createResearch(
  question: string,
  options: CreateResearchOptions = {},
): Promise<CreateResearchResponse> {
  const body: Record<string, unknown> = { question };
  if (options.depth) body.depth = options.depth;
  if (typeof options.browseWeb === "boolean") body.browse_web = options.browseWeb;
  return apiPost<CreateResearchResponse>("/api/research", body);
}
```

- [ ] **Step 2: Remove provider UI from `research-form.tsx`** — delete the `provider`/`baseUrl`/`providerModel`/`providerKey` state, the provider toggle button, the conditional OpenAI inputs block, and the provider args in the `createResearch(...)` call (back to `{ depth, browseWeb }`). Restore the submit `disabled` expression to `!question.trim() || submitting || freeBlocked`.

- [ ] **Step 3: Re-key the free-tier lock on active provider** — the form currently derives `freeTier` from `hasStoredApiKey()` (localStorage, now removed). Replace that with the server credential state: fetch `getCredentials()` on mount and set `freeTier = creds.active_provider === "free"`. The depth/browse locks and the "free reports used" copy continue to key off `freeTier`. Remove the `hasStoredApiKey` / `lib/api-key` import.

```tsx
import { getCredentials } from "@/lib/credentials";
// ...
const [activeProvider, setActiveProvider] = useState<"free" | "anthropic" | "openai">("free");
useEffect(() => {
  getCredentials().then((c) => setActiveProvider(c.active_provider)).catch(() => setActiveProvider("free"));
}, []);
const freeTier = activeProvider === "free";
```

- [ ] **Step 4: Delete `lib/api-key.ts` if not already removed in Task 7** and re-grep:

```bash
cd frontend && grep -rn "api-key\|hasStoredApiKey\|getStoredApiKey" app components lib hooks || echo "clean"
```

Expected: `clean`.

- [ ] **Step 5: Gates**

Run: `cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd frontend && git add -A
git commit -m "feat(run-form): drop per-request provider fields; lock keys off active provider"
```

---

## Final verification

- [ ] **Backend gate:** `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src` → green (DB tests skip without `SUPABASE_DB_URL`).
- [ ] **Frontend gate:** `cd frontend && npm run lint && npx tsc --noEmit && npm test && npm run build` → green.
- [ ] **Apply the migration** in Supabase (SQL editor / psql): run `backend/migrations/002_credentials.sql`. Generate a Fernet key (`cd backend && uv run python -c "from ara.crypto import generate_key; print(generate_key())"`) and set `ARA_ENCRYPTION_KEY` (and optionally `TAVILY_GLOBAL_MONTHLY_CAP`) in the root `.env`.
- [ ] **Manual smoke (needs DB + keys):** save an OpenAI config in Settings, set it active, run a report (no keys typed at run time); confirm researcher progress + cost meter. Save an Anthropic key, set active, run → server-side search path. Set active=free → free tier. Force the Tavily cap low and confirm OpenAI runs degrade to offline.
- [ ] **Update `CLAUDE.md`:** mark Phase 2b DONE; note `ARA_ENCRYPTION_KEY` + `TAVILY_GLOBAL_MONTHLY_CAP` env vars and that migration 002 must be applied; Phase 3 (deploy) is next.

---

## Self-review notes (author)

- **Spec coverage:** A (migration/schema) → Task 1; B (Fernet) → Task 1; C (credential store) → Task 2; D (resolution) → Task 5 + Task 6; E (Tavily count+enforce) → Tasks 3, 4, 6; F (endpoints) → Task 6; G (settings) → Task 1; H (frontend) → Tasks 7, 8. Non-goals respected (no rotation automation, single slot per provider, global-only cap, no user Tavily keys).
- **Type consistency:** `CredentialRecord`, `TavilyCapStatus.reached`, `resolve_overrides(...) -> RuntimeOverrides | None`, `on_tavily_search`/`OnTavilySearch`, `close(..., tavily_searches=)` are used identically across tasks and tests. `active_provider` literal set `{'free','anthropic','openai'}` consistent in DB check, Pydantic models, resolver, and frontend.
- **DB-gated tests** use the existing `requires_db` marker; pure logic (crypto, resolver, tavily counter, memory store, cap property) is fully unit-tested without a DB.
- **Behavior change** (retiring headers/body provider fields) is contained to Task 6 + Tasks 7-8; the 2a engine is reused unchanged.
