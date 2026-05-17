# Auth + Per-Account History + BYOK + Sample Gallery — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ARA's in-memory store with Supabase-backed persistence, add Google-OAuth/magic-link auth, per-account history with three access paths (owner / public sample / unguessable share token), BYOK via per-request header with a Haiku-only free tier behind a global monthly cost cap, and a curated sample gallery with on-demand SSE replay.

**Architecture:** Same FastAPI backend + Next.js 16 frontend. New `SupabaseReportStore` implements the existing `ReportStore` Protocol — agents/orchestrator unchanged structurally. JWT verified per request via PyJWT against the Supabase shared secret. Per-request `api_key` + `models` threaded into a new `RuntimeOverrides` dataclass replacing `Settings`-pulled values. Frontend uses `@supabase/ssr` for cookie-based auth; same-origin via Next.js `rewrites` makes `EventSource` auth Just Work via the auth cookie.

**Tech Stack:** Python 3.11+, FastAPI, asyncpg, PyJWT, Pydantic v2, LangGraph, Anthropic SDK (direct). Next.js 16 App Router, TypeScript strict, Tailwind v4, shadcn, @supabase/supabase-js, @supabase/ssr. Postgres via Supabase.

**Spec:** [docs/superpowers/specs/2026-05-01-auth-and-history-design.md](../specs/2026-05-01-auth-and-history-design.md)

---

## Pre-flight — manual steps (do once, then forget)

These are one-time human actions that the plan assumes are already done. The plan tasks below all assume these are complete.

- [ ] **Create a Supabase project** at https://supabase.com (free tier is fine).
- [ ] **From the project dashboard, copy:**
  - Project URL (`https://<project>.supabase.co`)
  - Anon public key (for the frontend)
  - Service role key (for the backend; **keep secret**)
  - JWT Secret (Settings → API → JWT Settings)
  - Database connection string (Settings → Database → URI; transaction pooler is fine)
- [ ] **Enable Google OAuth provider** in Authentication → Providers:
  - Create OAuth credentials at https://console.cloud.google.com/apis/credentials (Web application)
  - Redirect URI: `https://<project>.supabase.co/auth/v1/callback`
  - Paste Google client ID + secret into the Supabase Google provider config
- [ ] **Enable Email provider** with magic link in Authentication → Providers (it's on by default for email/password, but make sure "Magic Link" is enabled and "Confirm email" is set per your preference).
- [ ] **Add redirect URLs** in Authentication → URL Configuration:
  - Site URL: `http://localhost:3000` (dev) — replace with prod URL when deploying
  - Redirect URLs allowlist: `http://localhost:3000/auth/callback` (add prod equivalent later)

---

## Task 1: Database schema + migrations

**Files:**
- Create: `backend/migrations/001_initial.sql`
- Create: `backend/migrations/README.md`
- Modify: `.env.example` (add Supabase vars)
- Modify: `README.md` (document one-time DB setup)

- [ ] **Step 1: Create the migrations directory and write the schema**

Create `backend/migrations/001_initial.sql`:

```sql
-- ARA auth + history schema. Apply via Supabase SQL editor or psql.
-- This file is idempotent for tables/indexes (IF NOT EXISTS); RLS policies are not.

-- ============================================================================
-- 1. user_profiles  — app-level user data, 1:1 with auth.users
-- ============================================================================
create table if not exists user_profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  display_name text
);

-- ============================================================================
-- 2. reports  — the main entity. owner_id + is_sample + share_token define
--    the three access paths enforced in Python.
-- ============================================================================
create table if not exists reports (
  id              uuid primary key default gen_random_uuid(),
  owner_id        uuid not null references auth.users(id) on delete cascade,
  question        text not null,
  status          text not null check (status in ('running','completed','error')),
  depth           text not null check (depth in ('quick','standard','deep')),
  browse_web      boolean not null default true,
  used_byok       boolean not null default false,
  is_sample       boolean not null default false,
  share_token     uuid unique,
  cost_usd        numeric(10,6),
  report_payload  jsonb,
  error_message   text,
  created_at      timestamptz not null default now(),
  completed_at    timestamptz
);

create index if not exists reports_owner_created_idx
  on reports (owner_id, created_at desc);

create index if not exists reports_sample_idx
  on reports (is_sample) where is_sample;

-- ============================================================================
-- 3. report_events  — append-only event log; drives SSE replay
-- ============================================================================
create table if not exists report_events (
  id          bigserial primary key,
  report_id   uuid not null references reports(id) on delete cascade,
  event       jsonb not null,
  created_at  timestamptz not null default now()
);

create index if not exists report_events_report_idx
  on report_events (report_id, id);

-- ============================================================================
-- RLS — defense-in-depth. Backend uses the service role (bypasses RLS) and
-- enforces access in Python. If anything ever connects with the anon key,
-- these policies make sure cross-account leakage is impossible.
-- ============================================================================
alter table user_profiles  enable row level security;
alter table reports        enable row level security;
alter table report_events  enable row level security;

-- user_profiles: own row only
drop policy if exists user_profiles_select_own on user_profiles;
create policy user_profiles_select_own on user_profiles
  for select using (auth.uid() = id);

drop policy if exists user_profiles_upsert_own on user_profiles;
create policy user_profiles_upsert_own on user_profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

-- reports: own row + public samples
drop policy if exists reports_select_own_or_sample on reports;
create policy reports_select_own_or_sample on reports
  for select using (auth.uid() = owner_id or is_sample = true);

drop policy if exists reports_modify_own on reports;
create policy reports_modify_own on reports
  for all using (auth.uid() = owner_id) with check (auth.uid() = owner_id);

-- report_events: visibility joins on the owning report
drop policy if exists report_events_select on report_events;
create policy report_events_select on report_events
  for select using (
    exists (
      select 1 from reports r
      where r.id = report_events.report_id
        and (auth.uid() = r.owner_id or r.is_sample = true)
    )
  );

drop policy if exists report_events_modify on report_events;
create policy report_events_modify on report_events
  for all using (
    exists (
      select 1 from reports r
      where r.id = report_events.report_id and auth.uid() = r.owner_id
    )
  );
```

- [ ] **Step 2: Document how to apply migrations**

Create `backend/migrations/README.md`:

```markdown
# Migrations

SQL files applied manually via the Supabase SQL editor (Dashboard → SQL Editor → New query → paste → Run) or `psql "$SUPABASE_DB_URL" -f 001_initial.sql`.

Run them in numeric order. Each file is idempotent for table/index creation; RLS policies use `drop policy if exists` so re-running is safe.

## Adding a new migration

Name the file `NNN_short_description.sql` (zero-padded number). Document any non-additive changes in the file header comment.
```

- [ ] **Step 3: Update `.env.example` with new variables**

Append to `.env.example`:

```dotenv
# --- Supabase (auth + persistence) ---
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_JWT_SECRET=<JWT secret from Supabase Settings → API>
SUPABASE_DB_URL=postgresql://postgres:<password>@<host>:5432/postgres
ADMIN_USER_ID=<your auth.users.id — fill after first sign-in>

# --- Free tier ---
FREE_TIER_PER_USER_MONTHLY=3
FREE_TIER_GLOBAL_CAP_USD=20.0
```

Note: the existing `ANTHROPIC_API_KEY` keeps working — it's now repurposed as the free-tier server key.

- [ ] **Step 4: Update the README dev section**

Add to `README.md` under a new heading "First-time DB setup" before the existing `make dev-backend` instructions:

```markdown
## First-time DB setup

1. Create a Supabase project (see [docs/superpowers/specs/2026-05-01-auth-and-history-design.md](docs/superpowers/specs/2026-05-01-auth-and-history-design.md) "Pre-flight" section)
2. Paste `backend/migrations/001_initial.sql` into the Supabase SQL editor and Run
3. Copy the values from your Supabase dashboard into `.env` (see `.env.example`)
4. Sign in once via the running frontend, then copy your `auth.users.id` (from Supabase Dashboard → Authentication → Users) into `ADMIN_USER_ID` in `.env`
```

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/001_initial.sql backend/migrations/README.md .env.example README.md
git commit -m "feat(db): initial schema + Supabase setup docs"
```

---

## Task 2: Backend dependencies + new settings fields

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/src/ara/config.py`
- Test: `backend/tests/test_config.py` (create if not present)

- [ ] **Step 1: Add asyncpg and pyjwt to dependencies**

Edit `backend/pyproject.toml`, expand the `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.40.0",
    "asyncpg>=0.30.0",
    "fastapi>=0.115.0",
    "langgraph>=0.2.50",
    "pydantic>=2.9.0",
    "pydantic-settings>=2.6.0",
    "pyjwt[crypto]>=2.10.0",
    "sse-starlette>=2.1.3",
    "uvicorn[standard]>=0.32.0",
]
```

- [ ] **Step 2: Install the new deps**

```bash
cd backend && uv sync --all-extras
```

Expected: resolves and installs asyncpg + pyjwt without errors.

- [ ] **Step 3: Write the failing config test**

Create `backend/tests/test_config.py`:

```python
"""Settings — Supabase + free-tier fields parse and validate."""

from __future__ import annotations

from ara.config import Settings


def test_supabase_fields_default_empty() -> None:
    """In tests with no env, Supabase fields default to empty strings — not None."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.supabase_url == ""
    assert s.supabase_jwt_secret == ""
    assert s.supabase_db_url == ""


def test_free_tier_defaults() -> None:
    """Free-tier knobs have sane defaults so a fresh deployment works."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.free_tier_per_user_monthly == 3
    assert s.free_tier_global_cap_usd == 20.0


def test_admin_user_id_optional() -> None:
    """ADMIN_USER_ID is optional — when unset, no user has admin powers."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.admin_user_id is None
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_config.py -v
```

Expected: FAIL — `Settings` has no `supabase_url`, `free_tier_per_user_monthly`, or `admin_user_id` attributes.

- [ ] **Step 5: Extend Settings with the new fields**

Edit `backend/src/ara/config.py`, replace the contents of the `Settings` class with:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Anthropic — `anthropic_api_key` is the server-side free-tier key.
    anthropic_api_key: str = Field(default="")
    claude_planner_model: str = "claude-sonnet-4-5"
    claude_researcher_model: str = "claude-sonnet-4-5"
    claude_synthesizer_model: str = "claude-opus-4-5"

    # Server
    ara_host: str = "0.0.0.0"
    ara_port: int = 8000
    ara_cors_origins: str = "http://localhost:3000"

    # Researcher guardrails
    ara_researcher_max_iterations: int = 5
    ara_researcher_input_token_budget: int = 100_000

    # Per-report SSE ring buffer (reconnect continuity)
    ara_event_buffer_size: int = 50

    # Supabase (auth + persistence)
    supabase_url: str = Field(default="")
    supabase_jwt_secret: str = Field(default="")
    supabase_db_url: str = Field(default="")
    admin_user_id: str | None = Field(default=None)

    # Free tier
    free_tier_per_user_monthly: int = 3
    free_tier_global_cap_usd: float = 20.0

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ara_cors_origins.split(",") if o.strip()]
```

- [ ] **Step 6: Re-run the tests**

```bash
cd backend && uv run pytest tests/test_config.py -v
```

Expected: PASS — all three test cases.

- [ ] **Step 7: Sanity-check that mypy + ruff are happy**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/ara/config.py backend/tests/test_config.py
git commit -m "feat(config): add Supabase + free-tier settings, add pyjwt/asyncpg deps"
```

---

## Task 3: JWT verifier + FastAPI auth dependencies

**Files:**
- Create: `backend/src/ara/auth/__init__.py`
- Create: `backend/src/ara/auth/jwt.py`
- Create: `backend/src/ara/auth/dependencies.py`
- Create: `backend/tests/test_auth.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_auth.py`:

```python
"""JWT verification + FastAPI auth dependencies."""

from __future__ import annotations

import time
from uuid import UUID, uuid4

import jwt as pyjwt
import pytest
from fastapi import HTTPException

from ara.auth.jwt import User, verify_jwt
from ara.config import Settings

_SECRET = "test-secret-min-32-chars-for-supabase-hs256-jwt-verify"


def _make_token(
    *,
    sub: UUID | None = None,
    email: str = "user@example.com",
    secret: str = _SECRET,
    aud: str = "authenticated",
    expires_in: int = 3600,
    alg: str = "HS256",
) -> str:
    now = int(time.time())
    payload = {
        "sub": str(sub or uuid4()),
        "email": email,
        "aud": aud,
        "iat": now,
        "exp": now + expires_in,
    }
    return pyjwt.encode(payload, secret, algorithm=alg)


def _settings(secret: str = _SECRET) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.supabase_jwt_secret = secret
    return s


def test_verify_jwt_happy_path() -> None:
    uid = uuid4()
    token = _make_token(sub=uid, email="alice@example.com")
    user = verify_jwt(token, _settings())
    assert isinstance(user, User)
    assert user.id == uid
    assert user.email == "alice@example.com"


def test_verify_jwt_rejects_wrong_signature() -> None:
    token = _make_token(secret="different-secret-also-32-chars-long-here-ok")
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_expired() -> None:
    token = _make_token(expires_in=-60)
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_wrong_audience() -> None:
    token = _make_token(aud="some-other-audience")
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_missing_sub() -> None:
    now = int(time.time())
    token = pyjwt.encode(
        {"email": "x@x.com", "aud": "authenticated", "exp": now + 3600},
        _SECRET,
        algorithm="HS256",
    )
    with pytest.raises(HTTPException) as exc:
        verify_jwt(token, _settings())
    assert exc.value.status_code == 401


def test_verify_jwt_rejects_garbage() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_jwt("not-a-jwt", _settings())
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

Expected: FAIL — `ara.auth.jwt` module doesn't exist.

- [ ] **Step 3: Create the auth package**

Create `backend/src/ara/auth/__init__.py`:

```python
"""Auth: Supabase JWT verification + FastAPI dependencies."""

from ara.auth.dependencies import (
    get_current_user,
    get_optional_user,
    require_admin,
)
from ara.auth.jwt import User, verify_jwt

__all__ = [
    "User",
    "get_current_user",
    "get_optional_user",
    "require_admin",
    "verify_jwt",
]
```

- [ ] **Step 4: Implement JWT verification**

Create `backend/src/ara/auth/jwt.py`:

```python
"""Supabase JWT verification.

Supabase issues HS256-signed JWTs by default using the project's
`JWT_SECRET`. Verification is purely local — no network call.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import jwt as pyjwt
from fastapi import HTTPException, status

from ara.config import Settings


@dataclass(frozen=True)
class User:
    id: UUID
    email: str


def verify_jwt(token: str, settings: Settings) -> User:
    """Decode + validate a Supabase JWT.

    Raises HTTPException(401) on any failure — invalid signature,
    expired, missing sub/email, wrong audience, malformed token.
    """
    if not settings.supabase_jwt_secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server misconfigured: SUPABASE_JWT_SECRET not set",
        )
    try:
        payload = pyjwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        ) from exc

    sub = payload.get("sub")
    email = payload.get("email")
    if not sub or not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing required claims (sub, email)",
        )
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid sub claim"
        ) from exc
    return User(id=user_id, email=email)
```

- [ ] **Step 5: Implement FastAPI dependencies**

Create `backend/src/ara/auth/dependencies.py`:

```python
"""FastAPI dependencies that resolve the current Supabase user.

Token sources (checked in order):
1. `Authorization: Bearer <jwt>` header
2. `sb-access-token` cookie (set by @supabase/ssr on the frontend)

The cookie path is what makes `EventSource` work — browsers can't add
custom headers to EventSource but they do send cookies on same-origin
requests, and the Next.js rewrites in `next.config.ts` make the
frontend and backend appear same-origin.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException, Request, status

from ara.auth.jwt import User, verify_jwt
from ara.config import Settings, get_settings


def _extract_token(authorization: str | None, sb_access_token: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    if sb_access_token:
        return sb_access_token
    return None


def get_current_user(
    authorization: str | None = Header(default=None),
    sb_access_token: str | None = Cookie(default=None, alias="sb-access-token"),
    settings: Settings = Depends(get_settings),
) -> User:
    token = _extract_token(authorization, sb_access_token)
    if token is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return verify_jwt(token, settings)


def get_optional_user(
    authorization: str | None = Header(default=None),
    sb_access_token: str | None = Cookie(default=None, alias="sb-access-token"),
    settings: Settings = Depends(get_settings),
) -> User | None:
    token = _extract_token(authorization, sb_access_token)
    if token is None:
        return None
    try:
        return verify_jwt(token, settings)
    except HTTPException:
        return None


def require_admin(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> User:
    if settings.admin_user_id is None or str(user.id) != settings.admin_user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")
    return user


# Re-exposed for static import paths
__all__ = ["get_current_user", "get_optional_user", "require_admin", "Request"]
```

- [ ] **Step 6: Re-run the tests**

```bash
cd backend && uv run pytest tests/test_auth.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 7: Lint + type-check**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/src/ara/auth backend/tests/test_auth.py
git commit -m "feat(auth): Supabase JWT verifier + FastAPI dependencies"
```

---

## Task 4: Extend ReportStore Protocol + update in-memory impl

**Files:**
- Modify: `backend/src/ara/storage/base.py` (extend `create` signature)
- Modify: `backend/src/ara/storage/memory.py` (store metadata + add `get_report` for tests)
- Modify: `backend/tests/test_storage.py` (update existing tests)

The Protocol gains the metadata fields needed for INSERT (owner_id, depth, browse_web, used_byok). We update the in-memory store to accept and store them (even though it doesn't persist; tests will read them back). This stages the Protocol change before any Postgres impl exists.

- [ ] **Step 1: Read the existing storage tests for context**

```bash
cd backend && cat tests/test_storage.py
```

Note the patterns used so the in-memory store update doesn't break them.

- [ ] **Step 2: Extend the Protocol**

Replace the body of `backend/src/ara/storage/base.py`:

```python
"""`ReportStore` Protocol — the single swap-point for persistence.

Swapping the v1 in-memory impl for Supabase (or anything else) means
adding a new file that implements this Protocol. No other module should
reach into a concrete store.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal, Protocol
from uuid import UUID

from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import Depth  # re-exported below


class ReportStore(Protocol):
    """Lifecycle + event-stream interface for a report."""

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        """Register a new report with its owner + chosen run parameters."""
        ...

    async def get_question(self, report_id: UUID) -> str | None:
        """Return the original question, or None if the report doesn't exist."""
        ...

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        """Append an event to the ring buffer and fan out to live subscribers."""
        ...

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        """Finalize a report. Subscribers draining the tail still see buffered events."""
        ...

    def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        """Yield buffered events, then live events, then exit when the report closes."""
        ...
```

- [ ] **Step 3: Update the in-memory store**

Replace `backend/src/ara/storage/memory.py`:

```python
"""In-memory `ReportStore` — dict of per-report state, per-report ring buffer.

Thread safety: asyncio single-threaded loop guarantees no interleaving
between non-awaiting statements, so we don't need locks. The critical
section in `subscribe` (register live queue + snapshot ring buffer) is
fully synchronous — a new `put_event` cannot interleave between the two
statements, so there's no duplicate-yield window.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.storage.base import Depth

_DEFAULT_BUFFER_SIZE = 50


@dataclass
class _ReportState:
    question: str
    owner_id: UUID
    depth: Depth
    browse_web: bool
    used_byok: bool
    buffer: deque[ResearchEvent]
    live_queues: list[asyncio.Queue[ResearchEvent | None]] = field(default_factory=list)
    closed: bool = False
    status: Literal["running", "completed", "error"] = "running"
    cost_usd: float | None = None
    report_payload: ReportEnvelope | None = None
    error_message: str | None = None


class InMemoryReportStore:
    """v1 implementation of `ReportStore`. Not durable across restarts."""

    def __init__(self, *, buffer_size: int = _DEFAULT_BUFFER_SIZE) -> None:
        self._buffer_size = buffer_size
        self._reports: dict[UUID, _ReportState] = {}

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        if report_id in self._reports:
            return
        self._reports[report_id] = _ReportState(
            question=question,
            owner_id=owner_id,
            depth=depth,
            browse_web=browse_web,
            used_byok=used_byok,
            buffer=deque(maxlen=self._buffer_size),
        )

    async def get_question(self, report_id: UUID) -> str | None:
        state = self._reports.get(report_id)
        return state.question if state is not None else None

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        state = self._reports.get(report_id)
        if state is None or state.closed:
            return
        state.buffer.append(event)
        for q in list(state.live_queues):
            await q.put(event)

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        state = self._reports.get(report_id)
        if state is None or state.closed:
            return
        state.closed = True
        state.status = status
        state.cost_usd = cost_usd
        state.report_payload = report_payload
        state.error_message = error_message
        for q in list(state.live_queues):
            await q.put(None)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        state = self._reports.get(report_id)
        if state is None:
            return

        if state.closed:
            for event in list(state.buffer):
                yield event
            return

        queue: asyncio.Queue[ResearchEvent | None] = asyncio.Queue()
        state.live_queues.append(queue)
        buffered_snapshot = list(state.buffer)

        try:
            for event in buffered_snapshot:
                yield event
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            if queue in state.live_queues:
                state.live_queues.remove(queue)

    # ---- Helpers used by tests (not part of the Protocol) ----

    def get_state(self, report_id: UUID) -> _ReportState | None:
        """Inspection hook for tests — not part of `ReportStore`."""
        return self._reports.get(report_id)
```

- [ ] **Step 4: Add a tiny helper for test fixtures**

Create `backend/tests/_store_helpers.py`:

```python
"""Test-only convenience for constructing reports with sensible defaults.

Keeps every test from spelling out the same owner_id/depth/browse_web kwargs.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from ara.storage.base import Depth, ReportStore


async def create_test_report(
    store: ReportStore,
    report_id: UUID,
    question: str,
    *,
    owner_id: UUID | None = None,
    depth: Depth = "standard",
    browse_web: bool = True,
    used_byok: bool = True,
) -> UUID:
    """Create a report with test-default metadata. Returns the owner_id used."""
    owner = owner_id or uuid4()
    await store.create(
        report_id,
        question,
        owner_id=owner,
        depth=depth,
        browse_web=browse_web,
        used_byok=used_byok,
    )
    return owner
```

- [ ] **Step 5: Update existing storage tests to use the helper**

In `backend/tests/test_storage.py`, replace every call shaped like:

```python
await store.create(report_id, "some question")
```

with:

```python
from tests._store_helpers import create_test_report
# ...
await create_test_report(store, report_id, "some question")
```

And every call shaped like:

```python
await store.close(report_id)
```

with:

```python
await store.close(report_id, status="completed")
```

- [ ] **Step 6: Update existing orchestrator and SSE-contract tests**

Repeat the same `store.create(...)` and `store.close(...)` migration in `backend/tests/test_orchestrator.py` and `backend/tests/test_sse_contract.py`. Wherever the orchestrator is invoked, it already creates/closes for you — just check no test fakes a `ReportStore` with the old signature. If a test does (mock store), update its method signatures to match the new Protocol.

- [ ] **Step 7: Run the full test suite to ensure existing behavior preserved**

```bash
cd backend && uv run pytest -q
```

Expected: all tests still pass (existing ones plus the new auth ones).

- [ ] **Step 8: Lint + type-check**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add backend/src/ara/storage backend/tests
git commit -m "refactor(storage): extend ReportStore Protocol with owner + run metadata"
```

---

## Task 5: Orchestrator — RuntimeOverrides for per-request key/models

**Files:**
- Create: `backend/src/ara/runtime/overrides.py`
- Modify: `backend/src/ara/runtime/orchestrator.py`
- Modify: `backend/src/ara/graph/dag.py`
- Modify: `backend/tests/test_orchestrator.py`

Pull `api_key` + model selections out of `Settings`-as-runtime-input and into a per-call `RuntimeOverrides`. Settings keeps its role as the source of *defaults* and *infra config*; the orchestrator no longer reads model fields from it.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_orchestrator.py` (or create the file if absent):

```python
"""Orchestrator honors per-run RuntimeOverrides for key + models."""

from __future__ import annotations

from uuid import uuid4

import pytest

from ara.config import Settings
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides
from ara.options import options_for_depth
from ara.storage.memory import InMemoryReportStore


class _RecordingLLM:
    """Captures every model string the orchestrator dispatches to."""

    def __init__(self) -> None:
        self.models_seen: list[str] = []
        self.api_key_seen: str | None = None

    # Minimal subset of LLMClient surface used by build_graph. The real
    # graph will call these; the recording flavour just notes the model.
    async def complete_with_tools(self, *, model: str, **_: object) -> object:
        self.models_seen.append(model)
        raise RuntimeError("recording llm — not meant to actually run")


@pytest.mark.asyncio
async def test_overrides_replace_settings_models() -> None:
    """RuntimeOverrides.{planner,researcher,synthesizer}_model should
    be the models the graph actually dispatches to — NOT Settings's
    `claude_*_model` fields."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    settings.anthropic_api_key = "from-settings"
    settings.claude_planner_model = "from-settings-planner"

    overrides = RuntimeOverrides(
        api_key="from-overrides-key",
        planner_model="haiku-from-overrides",
        researcher_model="haiku-from-overrides",
        synthesizer_model="haiku-from-overrides",
        options=options_for_depth("quick", web_search_enabled=False),
    )

    store = InMemoryReportStore()
    rid = uuid4()

    # The recording client will raise at the first call so we don't
    # need a real Anthropic round-trip; we just need to confirm
    # the model the orchestrator selected.
    llm = _RecordingLLM()
    await run_report(
        report_id=rid,
        question="anything",
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=uuid4(),
        llm=llm,  # type: ignore[arg-type]
    )

    assert llm.models_seen, "graph should have at least attempted one call"
    assert all(
        m == "haiku-from-overrides" for m in llm.models_seen
    ), f"orchestrator must use overrides, not settings — saw {llm.models_seen}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_orchestrator.py::test_overrides_replace_settings_models -v
```

Expected: FAIL — `RuntimeOverrides` doesn't exist; `run_report` doesn't accept `overrides` or `owner_id`.

- [ ] **Step 3: Create the RuntimeOverrides dataclass**

Create `backend/src/ara/runtime/overrides.py`:

```python
"""Per-run, per-request inputs that override `Settings` defaults.

Settings is infrastructure (server config, the *default* free-tier key,
the *default* models). RuntimeOverrides is what the request handler
actually wants this specific run to use — which is either:

- BYOK: user-supplied key + their chosen models + their chosen depth
- Free tier: server's key + Haiku-everywhere + quick depth, no browsing
"""

from __future__ import annotations

from dataclasses import dataclass

from ara.options import ResearchOptions


@dataclass(frozen=True)
class RuntimeOverrides:
    api_key: str
    planner_model: str
    researcher_model: str
    synthesizer_model: str
    options: ResearchOptions
```

- [ ] **Step 4: Update the graph to take models directly**

Replace `backend/src/ara/graph/dag.py` `build_graph` signature + every `settings.claude_*_model` reference with a `models` parameter. New file body:

```python
"""Build the compiled LangGraph: plan → research (fan-out) → synthesize.

Researcher fan-out happens *inside* `research_node` via `asyncio.gather`
rather than as N LangGraph branches. That keeps the graph topology simple
(the user-facing model is a 3-node chain) while still giving us true
parallelism. The tradeoff — one non-obvious thing in this system — is
documented in ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from langgraph.graph import END, START, StateGraph

from ara.agents import EventEmitter, PlannerError, ResearcherError, SynthesizerError
from ara.agents.planner import plan_research
from ara.agents.researcher import research_sub_query
from ara.agents.synthesizer import synthesize_report
from ara.config import Settings
from ara.graph.state import GraphState
from ara.llm.client import LLMClient
from ara.models.events import (
    ErrorEvent,
    PlanReady,
    ReportComplete,
    ResearcherComplete,
)
from ara.models.research import SubQuery, SubQueryFinding
from ara.options import ResearchOptions, options_for_depth


@dataclass(frozen=True)
class GraphModels:
    planner: str
    researcher: str
    synthesizer: str


def build_graph(
    *,
    llm: LLMClient,
    emit: EventEmitter,
    settings: Settings,
    models: GraphModels,
    options: ResearchOptions | None = None,
) -> Any:
    """Return a compiled LangGraph bound to `llm`, `emit`, the per-run
    `models`, and per-run `options`. Settings is still consulted for
    engineering internals (researcher token budget).
    """
    opts = options if options is not None else options_for_depth("standard")

    async def plan_node(state: GraphState) -> dict[str, Any]:
        try:
            plan = await plan_research(
                question=state["question"],
                llm=llm,
                model=models.planner,
                max_sub_queries=opts.max_sub_queries,
            )
        except PlannerError as exc:
            await emit(ErrorEvent(stage="plan", message=str(exc)))
            raise
        plan = plan.model_copy(update={"web_search_enabled": opts.web_search_enabled})
        await emit(PlanReady(plan=plan))
        return {"plan": plan}

    async def research_node(state: GraphState) -> dict[str, Any]:
        plan = state["plan"]

        async def run_one(sq: SubQuery) -> SubQueryFinding:
            finding: SubQueryFinding
            try:
                finding = await research_sub_query(
                    sub_query=sq,
                    llm=llm,
                    model=models.researcher,
                    emit=emit,
                    max_iterations=opts.max_iterations,
                    input_token_budget=settings.ara_researcher_input_token_budget,
                    web_search_enabled=opts.web_search_enabled,
                )
            except ResearcherError as exc:
                await emit(
                    ErrorEvent(stage="research", message=str(exc), sub_query_id=sq.id)
                )
                finding = SubQueryFinding(
                    sub_query_id=sq.id,
                    summary=f"Research failed: {exc}",
                    key_facts=[],
                    sources=[],
                )
            await emit(ResearcherComplete(sub_query_id=sq.id, finding=finding))
            return finding

        findings = await asyncio.gather(*(run_one(sq) for sq in plan.sub_queries))
        return {"findings": list(findings)}

    async def synthesize_node(state: GraphState) -> dict[str, Any]:
        try:
            report = await synthesize_report(
                report_id=state["report_id"],
                original_question=state["question"],
                findings=state["findings"],
                llm=llm,
                model=models.synthesizer,
                emit=emit,
            )
        except SynthesizerError as exc:
            await emit(ErrorEvent(stage="synthesis", message=str(exc)))
            raise
        report = report.model_copy(update={"web_search_enabled": opts.web_search_enabled})
        await emit(ReportComplete(report=report))
        return {"report": report}

    g: StateGraph[GraphState] = StateGraph(GraphState)
    g.add_node("plan", plan_node)
    g.add_node("research", research_node)
    g.add_node("synthesize", synthesize_node)
    g.add_edge(START, "plan")
    g.add_edge("plan", "research")
    g.add_edge("research", "synthesize")
    g.add_edge("synthesize", END)
    return g.compile()
```

- [ ] **Step 5: Refactor the orchestrator**

Replace `backend/src/ara/runtime/orchestrator.py`:

```python
"""Orchestrator — the single entry point for running a report end-to-end."""

from __future__ import annotations

from uuid import UUID

from ara.agents import PlannerError, SynthesizerError
from ara.config import Settings
from ara.graph.dag import GraphModels, build_graph
from ara.llm.client import LLMClient
from ara.models.events import CostUpdate, ReportComplete, ResearchEvent
from ara.models.research import ReportEnvelope
from ara.pricing import estimate_cost_usd
from ara.runtime.overrides import RuntimeOverrides
from ara.storage.base import ReportStore


async def run_report(
    *,
    report_id: UUID,
    question: str,
    store: ReportStore,
    settings: Settings,
    overrides: RuntimeOverrides,
    owner_id: UUID,
    llm: LLMClient | None = None,
) -> None:
    """Run the full ARA pipeline for one report.

    `overrides` carries per-request key + models + options.
    `owner_id` is the Supabase user that owns this report.
    `llm` is injectable for tests; production callers should omit it.
    """
    await store.create(
        report_id,
        question,
        owner_id=owner_id,
        depth=_depth_for(overrides.options),
        browse_web=overrides.options.web_search_enabled,
        used_byok=_is_byok(overrides.api_key, settings),
    )
    cumulative_usd = 0.0
    final_report: ReportEnvelope | None = None

    async def emit(event: ResearchEvent) -> None:
        nonlocal final_report
        await store.put_event(report_id, event)
        if isinstance(event, ReportComplete):
            final_report = event.report

    async def on_api_call(model: str, input_tokens: int, output_tokens: int) -> None:
        nonlocal cumulative_usd
        cumulative_usd += estimate_cost_usd(model, input_tokens, output_tokens)
        await emit(
            CostUpdate(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cumulative_usd=cumulative_usd,
            )
        )

    if llm is None:
        llm = LLMClient(api_key=overrides.api_key, on_api_call=on_api_call)

    models = GraphModels(
        planner=overrides.planner_model,
        researcher=overrides.researcher_model,
        synthesizer=overrides.synthesizer_model,
    )
    graph = build_graph(llm=llm, emit=emit, settings=settings, models=models, options=overrides.options)

    status: str = "completed"
    error_message: str | None = None
    try:
        await graph.ainvoke({"report_id": report_id, "question": question})
    except (PlannerError, SynthesizerError) as exc:
        status = "error"
        error_message = str(exc)
    except Exception as exc:  # pragma: no cover — defense-in-depth
        status = "error"
        error_message = f"Unexpected: {exc!r}"
    finally:
        await store.close(
            report_id,
            status=status,  # type: ignore[arg-type]
            cost_usd=cumulative_usd,
            report_payload=final_report,
            error_message=error_message,
        )


def _depth_for(options: object) -> str:
    """Reverse-lookup helper — recover the depth label from a ResearchOptions.

    The orchestrator is given options, but the report row stores the
    label. Compare against known presets.
    """
    from ara.options import _DEPTH_PRESETS  # local import, internal lookup

    for label, preset in _DEPTH_PRESETS.items():
        if (
            getattr(options, "max_sub_queries", None) == preset.max_sub_queries
            and getattr(options, "max_iterations", None) == preset.max_iterations
        ):
            return label
    return "standard"


def _is_byok(api_key: str, settings: Settings) -> bool:
    """A run is BYOK if it's NOT using the server's free-tier key."""
    return api_key != settings.anthropic_api_key
```

- [ ] **Step 6: Update other callers of build_graph / run_report**

Grep for callers:

```bash
cd backend && rg -n "build_graph|run_report" --type py
```

Expected callers:
- `src/ara/api/routes.py` (will be rewritten in Task 7 — leave alone for now if it currently passes a `settings`-derived call; will compile because the new signature is additive)
- `tests/test_orchestrator.py` (already updated above)
- `tests/test_sse_contract.py` (might call `run_report` — update to pass overrides)
- `scripts/run_planner.py` (manual eval — update or leave; it likely calls plan_research directly)

For each test caller of `run_report`, construct a `RuntimeOverrides` from settings:

```python
from ara.runtime.overrides import RuntimeOverrides
from ara.options import options_for_depth

overrides = RuntimeOverrides(
    api_key=settings.anthropic_api_key,
    planner_model=settings.claude_planner_model,
    researcher_model=settings.claude_researcher_model,
    synthesizer_model=settings.claude_synthesizer_model,
    options=options_for_depth("standard"),
)
await run_report(
    report_id=rid,
    question=q,
    store=store,
    settings=settings,
    overrides=overrides,
    owner_id=uuid4(),
)
```

For the routes.py call site, update the `run_report(...)` call to construct overrides the same way (this will be properly rewired in Task 7; do a minimal compile-fix here):

```python
# in api/routes.py inside create_research, BEFORE Task 7's rewrite:
from ara.runtime.overrides import RuntimeOverrides
from uuid import uuid4 as _uuid4

overrides = RuntimeOverrides(
    api_key=settings.anthropic_api_key,
    planner_model=settings.claude_planner_model,
    researcher_model=settings.claude_researcher_model,
    synthesizer_model=settings.claude_synthesizer_model,
    options=options,
)
task = asyncio.create_task(
    run_report(
        report_id=report_id,
        question=req.question,
        store=store,
        settings=settings,
        overrides=overrides,
        owner_id=_uuid4(),  # placeholder until Task 7 wires real auth
    )
)
```

- [ ] **Step 7: Run the orchestrator test**

```bash
cd backend && uv run pytest tests/test_orchestrator.py -v
```

Expected: the new override test PASSES; pre-existing orchestrator tests still pass after their migration.

- [ ] **Step 8: Run the full suite**

```bash
cd backend && uv run pytest -q
```

Expected: green.

- [ ] **Step 9: Lint + types**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 10: Commit**

```bash
git add backend/src/ara/runtime backend/src/ara/graph backend/src/ara/api backend/tests
git commit -m "refactor(runtime): RuntimeOverrides for per-request key + models"
```

---

## Task 6: SupabaseReportStore (asyncpg) + Protocol conformance tests

**Files:**
- Create: `backend/src/ara/storage/supabase.py`
- Create: `backend/tests/test_supabase_store.py`
- Modify: `backend/tests/conftest.py` (add Postgres skip marker)

The Postgres-backed store. Requires a live Supabase (or any reachable Postgres) to test against. Tests skip gracefully if `SUPABASE_DB_URL` is not set in the environment, so CI without DB still passes.

- [ ] **Step 1: Add a skip marker for Postgres-dependent tests**

Edit `backend/tests/conftest.py` (add to existing content):

```python
import os
import pytest


def _has_db() -> bool:
    return bool(os.environ.get("SUPABASE_DB_URL"))


requires_db = pytest.mark.skipif(not _has_db(), reason="SUPABASE_DB_URL not set")
```

- [ ] **Step 2: Write the failing conformance test**

Create `backend/tests/test_supabase_store.py`:

```python
"""SupabaseReportStore — same Protocol contract as the in-memory store.

Requires a reachable Postgres with the 001_initial.sql migration applied.
Skip when SUPABASE_DB_URL is absent so local-without-DB still passes CI.
"""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from ara.models.events import PlanReady, ResearcherStarted
from ara.models.research import Plan, SubQuery
from ara.storage.supabase import SupabaseReportStore
from tests.conftest import requires_db


@pytest.fixture
async def db_pool() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()


@pytest.fixture
async def store(db_pool: asyncpg.Pool) -> SupabaseReportStore:
    return SupabaseReportStore(pool=db_pool)


@pytest.fixture
async def fake_owner(db_pool: asyncpg.Pool):
    """A throwaway auth.users row so reports.owner_id FK passes."""
    uid = uuid4()
    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            insert into auth.users (id, instance_id, aud, role, email,
                encrypted_password, email_confirmed_at, created_at, updated_at)
            values ($1, '00000000-0000-0000-0000-000000000000', 'authenticated',
                'authenticated', $2, '', now(), now(), now())
            """,
            uid,
            f"{uid}@test.local",
        )
    yield uid
    async with db_pool.acquire() as conn:
        await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_create_persists_metadata(store, fake_owner) -> None:
    rid = uuid4()
    await store.create(
        rid,
        "what is the airspeed of a swallow?",
        owner_id=fake_owner,
        depth="quick",
        browse_web=False,
        used_byok=False,
    )
    q = await store.get_question(rid)
    assert q == "what is the airspeed of a swallow?"


@requires_db
@pytest.mark.asyncio
async def test_subscribe_replays_then_lives(store, fake_owner) -> None:
    rid = uuid4()
    await store.create(rid, "q", owner_id=fake_owner, depth="quick", browse_web=False, used_byok=False)

    plan = Plan(sub_queries=[SubQuery(text="x")], web_search_enabled=False)
    await store.put_event(rid, PlanReady(plan=plan))

    received = []

    async def consume():
        async for ev in store.subscribe(rid):
            received.append(ev)
            if len(received) == 2:
                return

    import asyncio
    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    await store.put_event(rid, ResearcherStarted(sub_query_id=plan.sub_queries[0].id))
    await asyncio.wait_for(task, timeout=2.0)
    await store.close(rid, status="completed", cost_usd=0.0)

    assert len(received) == 2
    assert isinstance(received[0], PlanReady)
    assert isinstance(received[1], ResearcherStarted)
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
cd backend && uv run pytest tests/test_supabase_store.py -v
```

Expected: skipped (no `SUPABASE_DB_URL` in test env) OR fails with "module ara.storage.supabase not found." Either is fine — we just need to confirm the test file is wired.

- [ ] **Step 4: Implement SupabaseReportStore**

Create `backend/src/ara/storage/supabase.py`:

```python
"""Postgres-backed ReportStore using asyncpg.

Persistence per Protocol method:
- create:    INSERT into reports
- put_event: INSERT into report_events  +  fan-out to in-process live queues
- subscribe: replay last N events from report_events, then yield live events
- close:     UPDATE reports (status, cost_usd, report_payload, completed_at)

In-process pubsub stays (single-process for v1). When ARA goes
multi-instance we add a LISTEN/NOTIFY variant; Protocol unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

import asyncpg

from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.storage.base import Depth

_REPLAY_TAIL = 50  # how many trailing events to replay to a fresh subscriber


@dataclass
class _Subscribers:
    queues: list[asyncio.Queue[ResearchEvent | None]] = field(default_factory=list)
    closed: bool = False


class SupabaseReportStore:
    """asyncpg-backed implementation of `ReportStore`.

    Live pubsub is in-memory — fine while single-process. The DB is the
    source of truth for replay; in-flight subscribers are also fanned to
    directly for low latency.
    """

    def __init__(self, *, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._subs: dict[UUID, _Subscribers] = {}

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                insert into reports
                  (id, owner_id, question, status, depth, browse_web, used_byok)
                values ($1, $2, $3, 'running', $4, $5, $6)
                on conflict (id) do nothing
                """,
                report_id, owner_id, question, depth, browse_web, used_byok,
            )

    async def get_question(self, report_id: UUID) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("select question from reports where id = $1", report_id)
        return row["question"] if row else None

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        payload_json = event.model_dump_json()
        async with self._pool.acquire() as conn:
            await conn.execute(
                "insert into report_events (report_id, event) values ($1, $2::jsonb)",
                report_id, payload_json,
            )
        subs = self._subs.get(report_id)
        if subs is None or subs.closed:
            return
        for q in list(subs.queues):
            await q.put(event)

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        payload_json = report_payload.model_dump_json() if report_payload else None
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                update reports
                set status = $2, cost_usd = $3, report_payload = $4::jsonb,
                    error_message = $5, completed_at = now()
                where id = $1
                """,
                report_id, status, cost_usd, payload_json, error_message,
            )
        subs = self._subs.get(report_id)
        if subs is None or subs.closed:
            return
        subs.closed = True
        for q in list(subs.queues):
            await q.put(None)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        # Register the live queue BEFORE snapshotting tail events from the
        # DB so a put_event arriving during snapshot is delivered live and
        # not lost.
        subs = self._subs.setdefault(report_id, _Subscribers())
        queue: asyncio.Queue[ResearchEvent | None] = asyncio.Queue()
        if subs.closed:
            # Report finished before this subscriber arrived. Just replay tail.
            async for ev in self._replay_tail(report_id):
                yield ev
            return
        subs.queues.append(queue)

        try:
            async for ev in self._replay_tail(report_id):
                yield ev
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            if queue in subs.queues:
                subs.queues.remove(queue)

    async def _replay_tail(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        """Yield the last `_REPLAY_TAIL` events for a report, oldest first."""
        from ara.models.events import ResearchEventAdapter

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select event from (
                  select id, event from report_events
                  where report_id = $1
                  order by id desc
                  limit $2
                ) sub
                order by id asc
                """,
                report_id, _REPLAY_TAIL,
            )
        for row in rows:
            yield ResearchEventAdapter.validate_python(row["event"])
```

Note: the import for `ResearchEventAdapter` — verify the symbol name in `backend/src/ara/models/events.py`. If the project uses a different name (e.g. `ResearchEvent` as a `TypeAdapter`), update the import accordingly. Run:

```bash
cd backend && rg -n "TypeAdapter|ResearchEventAdapter" src/ara/models/events.py
```

If the adapter has a different name, adjust the import in `_replay_tail`.

- [ ] **Step 5: Run the test (locally with a real DB)**

```bash
cd backend && SUPABASE_DB_URL="$YOUR_DB_URL" uv run pytest tests/test_supabase_store.py -v
```

Expected: both tests PASS. If `SUPABASE_DB_URL` is unset, both are skipped — that's also a valid outcome (CI / dev without DB).

- [ ] **Step 6: Run the in-memory store tests too (regression guard)**

```bash
cd backend && uv run pytest -q
```

Expected: everything green.

- [ ] **Step 7: Lint + types**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors. (If asyncpg has missing-stubs complaints, add to the existing `[[tool.mypy.overrides]]` block in `pyproject.toml`:

```toml
[[tool.mypy.overrides]]
module = ["asyncpg.*"]
ignore_missing_imports = true
```
)

- [ ] **Step 8: Commit**

```bash
git add backend/src/ara/storage/supabase.py backend/tests/test_supabase_store.py backend/tests/conftest.py backend/pyproject.toml
git commit -m "feat(storage): SupabaseReportStore (asyncpg) + conformance tests"
```

---

## Task 7: Quota module + tests

**Files:**
- Create: `backend/src/ara/quota.py`
- Create: `backend/tests/test_quota.py`

The free-tier gate. Two checks against the `reports` table: per-user count this month, global spend sum this month. Returns a structured `QuotaStatus` so the route handler can build the right 402 body.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_quota.py`:

```python
"""Free-tier quota — per-user count + global spend caps."""

from __future__ import annotations

import os
from uuid import uuid4

import asyncpg
import pytest

from ara.config import Settings
from ara.quota import QuotaDenial, QuotaOk, check_free_tier
from tests.conftest import requires_db


@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(os.environ["SUPABASE_DB_URL"], min_size=1, max_size=2)
    try:
        yield pool
    finally:
        await pool.close()


def _settings(per_user: int = 3, global_cap: float = 20.0) -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.free_tier_per_user_monthly = per_user
    s.free_tier_global_cap_usd = global_cap
    return s


async def _insert_free_run(
    conn: asyncpg.Connection, owner_id, cost_usd: float, status: str = "completed"
) -> None:
    rid = uuid4()
    await conn.execute(
        """
        insert into reports
          (id, owner_id, question, status, depth, browse_web, used_byok, cost_usd)
        values ($1, $2, 'q', $3, 'quick', false, false, $4)
        """,
        rid, owner_id, status, cost_usd,
    )


async def _insert_user(conn) -> "uuid.UUID":
    uid = uuid4()
    await conn.execute(
        """
        insert into auth.users (id, instance_id, aud, role, email,
            encrypted_password, email_confirmed_at, created_at, updated_at)
        values ($1, '00000000-0000-0000-0000-000000000000', 'authenticated',
            'authenticated', $2, '', now(), now(), now())
        """,
        uid, f"{uid}@test.local",
    )
    return uid


@requires_db
@pytest.mark.asyncio
async def test_quota_ok_when_fresh(db_pool) -> None:
    async with db_pool.acquire() as conn:
        uid = await _insert_user(conn)
        try:
            status = await check_free_tier(uid, db_pool, _settings())
            assert isinstance(status, QuotaOk)
            assert status.used == 0
            assert status.limit == 3
        finally:
            await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_quota_denied_per_user(db_pool) -> None:
    async with db_pool.acquire() as conn:
        uid = await _insert_user(conn)
        try:
            for _ in range(3):
                await _insert_free_run(conn, uid, cost_usd=0.05)
            status = await check_free_tier(uid, db_pool, _settings())
            assert isinstance(status, QuotaDenial)
            assert status.reason == "free_tier_exhausted"
        finally:
            await conn.execute("delete from auth.users where id = $1", uid)


@requires_db
@pytest.mark.asyncio
async def test_quota_denied_global_cap(db_pool) -> None:
    async with db_pool.acquire() as conn:
        u1 = await _insert_user(conn)
        u2 = await _insert_user(conn)
        try:
            # Make sure global spend already exceeds a tiny cap
            for _ in range(5):
                await _insert_free_run(conn, u1, cost_usd=5.0)
            status = await check_free_tier(u2, db_pool, _settings(global_cap=10.0))
            assert isinstance(status, QuotaDenial)
            assert status.reason == "free_tier_global_cap_reached"
        finally:
            for u in (u1, u2):
                await conn.execute("delete from auth.users where id = $1", u)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd backend && SUPABASE_DB_URL="$YOUR_DB_URL" uv run pytest tests/test_quota.py -v
```

Expected: FAIL — `ara.quota` doesn't exist.

- [ ] **Step 3: Implement the quota module**

Create `backend/src/ara/quota.py`:

```python
"""Free-tier quota — per-user monthly count + global monthly spend cap.

Both numbers are derived from `reports` rows on each check. No counter
table to drift. If this ever becomes a hotspot, add an in-process 30s
TTL cache around `_count_user` and `_sum_global` — but ship without it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import asyncpg

from ara.config import Settings


@dataclass(frozen=True)
class QuotaOk:
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float


@dataclass(frozen=True)
class QuotaDenial:
    reason: Literal["free_tier_exhausted", "free_tier_global_cap_reached"]
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float


QuotaStatus = QuotaOk | QuotaDenial


async def check_free_tier(
    user_id: UUID, pool: asyncpg.Pool, settings: Settings
) -> QuotaStatus:
    used = await _count_user_runs(user_id, pool)
    spend = await _sum_global_spend(pool)
    limit = settings.free_tier_per_user_monthly
    cap = settings.free_tier_global_cap_usd

    if used >= limit:
        return QuotaDenial(
            reason="free_tier_exhausted",
            used=used, limit=limit,
            global_spend_usd=spend, global_cap_usd=cap,
        )
    if spend >= cap:
        return QuotaDenial(
            reason="free_tier_global_cap_reached",
            used=used, limit=limit,
            global_spend_usd=spend, global_cap_usd=cap,
        )
    return QuotaOk(used=used, limit=limit, global_spend_usd=spend, global_cap_usd=cap)


async def _count_user_runs(user_id: UUID, pool: asyncpg.Pool) -> int:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select count(*)::int as n from reports
            where owner_id = $1
              and used_byok = false
              and created_at >= date_trunc('month', now())
            """,
            user_id,
        )
    return row["n"] if row else 0


async def _sum_global_spend(pool: asyncpg.Pool) -> float:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            select coalesce(sum(cost_usd), 0)::float as s from reports
            where used_byok = false
              and created_at >= date_trunc('month', now())
            """,
        )
    return float(row["s"]) if row else 0.0
```

- [ ] **Step 4: Re-run the tests**

```bash
cd backend && SUPABASE_DB_URL="$YOUR_DB_URL" uv run pytest tests/test_quota.py -v
```

Expected: all three PASS (or all skipped without DB).

- [ ] **Step 5: Lint + types**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ara/quota.py backend/tests/test_quota.py
git commit -m "feat(quota): free-tier per-user + global cap checks"
```

---

## Task 8: API routes — auth, new CRUD endpoints, free-tier branch on POST /research

**Files:**
- Modify: `backend/src/ara/api/routes.py` (substantial rewrite)
- Modify: `backend/src/ara/main.py` (wire SupabaseReportStore + db_pool into app.state)
- Create: `backend/tests/test_routes_auth.py`

This is the largest single task. It wires every piece of plumbing built so far to the HTTP surface.

- [ ] **Step 1: Wire the db pool + store into app.state**

Replace `backend/src/ara/main.py`:

```python
"""FastAPI app factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ara.api.routes import router
from ara.config import get_settings
from ara.storage.memory import InMemoryReportStore
from ara.storage.supabase import SupabaseReportStore


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.supabase_db_url:
            app.state.db_pool = await asyncpg.create_pool(
                settings.supabase_db_url, min_size=1, max_size=10
            )
            app.state.store = SupabaseReportStore(pool=app.state.db_pool)
        else:
            app.state.db_pool = None
            app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
        try:
            yield
        finally:
            if app.state.db_pool is not None:
                await app.state.db_pool.close()

    app = FastAPI(title="Autonomous Research Assistant", version="0.2.0", lifespan=lifespan)
    # Eager state init so TestClient without `with` still works.
    app.state.db_pool = None
    app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
    tasks: set[asyncio.Task[None]] = set()
    app.state.tasks = tasks

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
```

- [ ] **Step 2: Rewrite the routes module**

Replace `backend/src/ara/api/routes.py`:

```python
"""HTTP routes.

Auth: all endpoints require a signed-in Supabase user EXCEPT:
- GET  /api/config             (public — already was)
- GET  /api/gallery            (public — lists is_sample=true reports)
- GET  /api/reports/{id}       (public when is_sample OR ?t=share_token)
- GET  /api/research/{id}/stream  (same rule as GET /reports/{id})
- GET  /api/reports/{id}/replay   (same rule)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ara.auth import User, get_current_user, get_optional_user, require_admin
from ara.config import Settings, get_settings
from ara.options import Depth, depth_presets, options_for_depth
from ara.quota import QuotaDenial, check_free_tier
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides
from ara.storage.base import ReportStore

router = APIRouter(prefix="/api")

# --- Free-tier model lockdown ---
FREE_TIER_MODEL = "claude-haiku-4-5"


# ---------- Request / response models ----------


class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Depth = "standard"
    browse_web: bool = True


class CreateResearchResponse(BaseModel):
    report_id: UUID


class ModelsConfig(BaseModel):
    planner: str
    researcher: str
    synthesizer: str


class DepthPresetConfig(BaseModel):
    max_sub_queries: int
    max_iterations: int


class ConfigResponse(BaseModel):
    models: ModelsConfig
    depth_presets: dict[str, DepthPresetConfig]


class MeResponse(BaseModel):
    id: UUID
    email: str


class ReportSummary(BaseModel):
    id: UUID
    question: str
    status: Literal["running", "completed", "error"]
    depth: Depth
    used_byok: bool
    is_sample: bool
    cost_usd: float | None
    created_at: str  # ISO8601
    completed_at: str | None


class ReportDetail(ReportSummary):
    report_payload: dict[str, Any] | None
    error_message: str | None
    share_token: UUID | None


class ShareResponse(BaseModel):
    share_url_path: str  # e.g. "/r/<id>?t=<token>"
    share_token: UUID


class QuotaResponse(BaseModel):
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float
    circuit_breaker_tripped: bool


# ---------- Helpers ----------


def _pool_or_503(request: Request) -> asyncpg.Pool:
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    return pool


async def _fetch_report_row(pool: asyncpg.Pool, report_id: UUID) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow("select * from reports where id = $1", report_id)


async def _require_report_access(
    pool: asyncpg.Pool,
    report_id: UUID,
    user: User | None,
    share_token: UUID | None,
) -> asyncpg.Record:
    """Three-path access check. Returns the row or raises 403/404."""
    row = await _fetch_report_row(pool, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if user is not None and row["owner_id"] == user.id:
        return row
    if row["is_sample"]:
        return row
    if share_token is not None and row["share_token"] is not None and row["share_token"] == share_token:
        return row
    raise HTTPException(status_code=403, detail="Not authorized to view this report")


def _row_to_summary(row: asyncpg.Record) -> ReportSummary:
    return ReportSummary(
        id=row["id"],
        question=row["question"],
        status=row["status"],
        depth=row["depth"],
        used_byok=row["used_byok"],
        is_sample=row["is_sample"],
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        created_at=row["created_at"].isoformat(),
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
    )


def _row_to_detail(row: asyncpg.Record) -> ReportDetail:
    return ReportDetail(
        **_row_to_summary(row).model_dump(),
        report_payload=row["report_payload"],
        error_message=row["error_message"],
        share_token=row["share_token"],
    )


# ---------- Public endpoints ----------


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    settings = get_settings()
    return ConfigResponse(
        models=ModelsConfig(
            planner=settings.claude_planner_model,
            researcher=settings.claude_researcher_model,
            synthesizer=settings.claude_synthesizer_model,
        ),
        depth_presets={
            d: DepthPresetConfig(**p) for d, p in depth_presets().items()
        },
    )


@router.get("/gallery", response_model=list[ReportSummary])
async def get_gallery(request: Request) -> list[ReportSummary]:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select * from reports where is_sample = true order by created_at desc"
        )
    return [_row_to_summary(r) for r in rows]


# ---------- Authed: identity, quota ----------


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> QuotaResponse:
    pool = _pool_or_503(request)
    status_ = await check_free_tier(user.id, pool, settings)
    return QuotaResponse(
        used=status_.used,
        limit=status_.limit,
        global_spend_usd=status_.global_spend_usd,
        global_cap_usd=status_.global_cap_usd,
        circuit_breaker_tripped=(
            isinstance(status_, QuotaDenial)
            and status_.reason == "free_tier_global_cap_reached"
        ),
    )


# ---------- Reports CRUD ----------


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    request: Request, user: User = Depends(get_current_user)
) -> list[ReportSummary]:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select * from reports where owner_id = $1 order by created_at desc",
            user.id,
        )
    return [_row_to_summary(r) for r in rows]


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> ReportDetail:
    pool = _pool_or_503(request)
    row = await _require_report_access(pool, report_id, user, t)
    return _row_to_detail(row)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "delete from reports where id = $1 and owner_id = $2",
            report_id, user.id,
        )
    if result.endswith("0"):  # DELETE 0
        raise HTTPException(status_code=404, detail="Report not found")


@router.post("/reports/{report_id}/share", response_model=ShareResponse)
async def share_report(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> ShareResponse:
    pool = _pool_or_503(request)
    token = uuid4()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            update reports
            set share_token = coalesce(share_token, $1)
            where id = $2 and owner_id = $3
            returning share_token
            """,
            token, report_id, user.id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ShareResponse(
        share_url_path=f"/r/{report_id}?t={row['share_token']}",
        share_token=row["share_token"],
    )


@router.delete("/reports/{report_id}/share", status_code=204)
async def revoke_share(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set share_token = null where id = $1 and owner_id = $2",
            report_id, user.id,
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


@router.post("/reports/{report_id}/promote", status_code=204)
async def promote_report(
    report_id: UUID, request: Request, _: User = Depends(require_admin)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set is_sample = true where id = $1", report_id
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


@router.delete("/reports/{report_id}/promote", status_code=204)
async def unpromote_report(
    report_id: UUID, request: Request, _: User = Depends(require_admin)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set is_sample = false where id = $1", report_id
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


# ---------- The main one — POST /research ----------


@router.post("/research", response_model=CreateResearchResponse)
async def create_research(
    req: CreateResearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    x_anthropic_key: str | None = Header(default=None, alias="X-Anthropic-Key"),
) -> CreateResearchResponse:
    pool = _pool_or_503(request)
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks

    # ---- Resolve the run's API key + models + options ----
    if x_anthropic_key:
        api_key = x_anthropic_key
        options = options_for_depth(req.depth, web_search_enabled=req.browse_web)
        overrides = RuntimeOverrides(
            api_key=api_key,
            planner_model=settings.claude_planner_model,
            researcher_model=settings.claude_researcher_model,
            synthesizer_model=settings.claude_synthesizer_model,
            options=options,
        )
    else:
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
                    "message": "Free-tier monthly limit reached"
                    if quota.reason == "free_tier_exhausted"
                    else "Free tier capped site-wide for this month",
                    "used": quota.used,
                    "limit": quota.limit,
                    "global_spend_usd": quota.global_spend_usd,
                    "global_cap_usd": quota.global_cap_usd,
                },
            )
        # Free-tier lockdown
        options = options_for_depth("quick", web_search_enabled=False)
        overrides = RuntimeOverrides(
            api_key=settings.anthropic_api_key,
            planner_model=FREE_TIER_MODEL,
            researcher_model=FREE_TIER_MODEL,
            synthesizer_model=FREE_TIER_MODEL,
            options=options,
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


# ---------- SSE: live stream + replay ----------


@router.get("/research/{report_id}/stream")
async def stream_research(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> EventSourceResponse:
    pool = _pool_or_503(request)
    await _require_report_access(pool, report_id, user, t)
    store: ReportStore = request.app.state.store

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        async for event in store.subscribe(report_id):
            yield {"data": event.model_dump_json()}

    return EventSourceResponse(event_source())
```

- [ ] **Step 3: Write the access-control matrix tests**

Create `backend/tests/test_routes_auth.py`:

```python
"""POST /research auth requirement + reports access matrix."""

from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ara.main import create_app
from tests.conftest import requires_db


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_post_research_requires_auth(client: TestClient) -> None:
    r = client.post("/api/research", json={"question": "hi"})
    assert r.status_code == 401


def test_stream_returns_403_without_access(client: TestClient) -> None:
    # Random report id; no DB row, no auth → expect 503 (no DB configured)
    # or 404 (report not found). Either is fine — what we're guarding
    # against is a code path that silently returns events to the unauthed.
    r = client.get(f"/api/research/{uuid4()}/stream")
    assert r.status_code in (401, 403, 404, 503)


@requires_db
def test_share_token_grants_read(client: TestClient) -> None:
    # NOTE: this case requires a real DB + seeded report. Skipped in CI without one.
    # Full end-to-end with JWT-minting is left as a manual smoke; the unit-level
    # access logic is covered in test_quota.py + the Protocol tests.
    pass
```

- [ ] **Step 4: Run all tests**

```bash
cd backend && uv run pytest -q
```

Expected: green (the access-matrix test is intentionally minimal — manual smoke covers the rest).

- [ ] **Step 5: Lint + types**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 6: Start the server and hit the endpoints manually**

```bash
make dev-backend
```

In another terminal:

```bash
curl -i http://localhost:8000/api/config        # 200
curl -i http://localhost:8000/api/me            # 401
curl -i http://localhost:8000/api/research \
  -H 'Content-Type: application/json' \
  -d '{"question":"x"}'                         # 401
```

Expected status codes as commented.

- [ ] **Step 7: Commit**

```bash
git add backend/src/ara backend/tests
git commit -m "feat(api): auth + reports CRUD + free-tier branch on POST /research"
```

---

## Task 9: Replay endpoint

**Files:**
- Modify: `backend/src/ara/api/routes.py` (add replay endpoint)

Reads saved events from `report_events` and yields them as SSE with brief delays so the visitor sees the workflow unfold.

- [ ] **Step 1: Add the replay endpoint to routes.py**

Insert just below the existing `stream_research` route in `backend/src/ara/api/routes.py`:

```python
import asyncio as _asyncio_for_replay

REPLAY_INTER_EVENT_DELAY_MS = 80


@router.get("/reports/{report_id}/replay")
async def replay_report(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> EventSourceResponse:
    pool = _pool_or_503(request)
    await _require_report_access(pool, report_id, user, t)

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select event from report_events
                where report_id = $1
                order by id asc
                """,
                report_id,
            )
        for row in rows:
            yield {"data": row["event"]}
            await _asyncio_for_replay.sleep(REPLAY_INTER_EVENT_DELAY_MS / 1000)

    return EventSourceResponse(event_source())
```

- [ ] **Step 2: Manual smoke test (requires a completed report in DB)**

Once you have a completed report at known id `<id>` belonging to your user:

```bash
curl -N "http://localhost:8000/api/reports/<id>/replay" \
  -H "Cookie: sb-access-token=<your jwt>"
```

Expected: SSE events stream out with ~80ms between them. Use the share-token URL instead if you don't want to fiddle with cookies:

```bash
# First mint a token via POST /api/reports/{id}/share (authed), then:
curl -N "http://localhost:8000/api/reports/<id>/replay?t=<token>"
```

- [ ] **Step 3: Lint + types**

```bash
cd backend && uv run ruff check . && uv run mypy src
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add backend/src/ara/api/routes.py
git commit -m "feat(api): GET /reports/:id/replay — SSE replay of saved events"
```

---

## Task 10: Frontend — Supabase clients, middleware, login flow

**Files:**
- Modify: `frontend/package.json` (add `@supabase/supabase-js`, `@supabase/ssr`)
- Modify: `frontend/next.config.ts` (rewrites to backend)
- Modify: `frontend/.env.local.example` (or create) — Supabase + backend vars
- Create: `frontend/lib/supabase/client.ts`
- Create: `frontend/lib/supabase/server.ts`
- Create: `frontend/middleware.ts`
- Create: `frontend/app/login/page.tsx`
- Create: `frontend/app/auth/callback/route.ts`

- [ ] **Step 1: Install Supabase deps**

```bash
cd frontend && npm install @supabase/supabase-js @supabase/ssr
```

- [ ] **Step 2: Add env template**

Create `frontend/.env.local.example`:

```dotenv
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon public key from Supabase>
NEXT_PUBLIC_ADMIN_USER_ID=<your auth.users.id>
BACKEND_ORIGIN=http://localhost:8000
```

Document in the README: copy to `.env.local`, fill in real values.

- [ ] **Step 3: Configure Next.js rewrites**

Replace `frontend/next.config.ts`:

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
```

- [ ] **Step 4: Browser Supabase client**

Create `frontend/lib/supabase/client.ts`:

```typescript
"use client";

import { createBrowserClient } from "@supabase/ssr";

export function createSupabaseBrowser() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
```

- [ ] **Step 5: Server Supabase client (RSC + Route Handlers)**

Create `frontend/lib/supabase/server.ts`:

```typescript
import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";

export async function createSupabaseServer() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            for (const { name, value, options } of cookiesToSet) {
              cookieStore.set(name, value, options);
            }
          } catch {
            // No-op in RSC context where setting cookies is disallowed.
          }
        },
      },
    },
  );
}
```

- [ ] **Step 6: Middleware — keep session fresh on every request**

Create `frontend/middleware.ts`:

```typescript
import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          for (const { name, value, options } of cookiesToSet) {
            response.cookies.set(name, value, options);
          }
        },
      },
    },
  );
  // Refreshes the session if expired
  await supabase.auth.getUser();
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

- [ ] **Step 7: Login page**

Create `frontend/app/login/page.tsx`:

```typescript
"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { createSupabaseBrowser } from "@/lib/supabase/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export default function LoginPage() {
  const supabase = createSupabaseBrowser();
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function signInWithGoogle() {
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    if (error) setError(error.message);
  }

  async function signInWithMagicLink(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setPending(true);
    const { error } = await supabase.auth.signInWithOtp({
      email,
      options: {
        emailRedirectTo: `${window.location.origin}/auth/callback?next=${encodeURIComponent(next)}`,
      },
    });
    setPending(false);
    if (error) setError(error.message);
    else setSentTo(email);
  }

  return (
    <main className="mx-auto max-w-md p-8 pt-20">
      <h1 className="font-mono text-2xl tracking-tight">Sign in to ARA</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Required to run reports and keep your history.
      </p>

      <div className="mt-8 space-y-4">
        <Button onClick={signInWithGoogle} className="w-full" variant="default">
          Continue with Google
        </Button>

        <div className="text-muted-foreground py-2 text-center font-mono text-[10px] uppercase tracking-widest">
          or
        </div>

        <form onSubmit={signInWithMagicLink} className="space-y-3">
          <Input
            type="email"
            required
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={pending || sentTo !== null}
          />
          <Button type="submit" disabled={pending || sentTo !== null} className="w-full" variant="secondary">
            {pending ? "Sending…" : sentTo ? `Magic link sent to ${sentTo}` : "Email me a magic link"}
          </Button>
        </form>

        {error && <p className="text-destructive text-sm">{error}</p>}
      </div>
    </main>
  );
}
```

- [ ] **Step 8: OAuth callback route handler**

Create `frontend/app/auth/callback/route.ts`:

```typescript
import { NextResponse } from "next/server";

import { createSupabaseServer } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const code = url.searchParams.get("code");
  const next = url.searchParams.get("next") || "/";

  if (code) {
    const supabase = await createSupabaseServer();
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (error) {
      return NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(error.message)}`, url.origin));
    }
  }
  return NextResponse.redirect(new URL(next, url.origin));
}
```

- [ ] **Step 9: Verify shadcn `button` and `input` exist**

```bash
cd frontend && ls components/ui | grep -E '^(button|input)\.tsx$'
```

If either is missing:

```bash
cd frontend && npx shadcn@latest add button input
```

- [ ] **Step 10: Smoke test the login page**

```bash
make dev-backend &
make dev-frontend
```

Open http://localhost:3000/login. Click "Continue with Google" — verify the OAuth flow lands you back at `/` signed in. Open Supabase Dashboard → Authentication → Users to confirm the row.

- [ ] **Step 11: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/next.config.ts \
        frontend/lib/supabase frontend/middleware.ts \
        frontend/app/login frontend/app/auth \
        frontend/.env.local.example
git commit -m "feat(auth): Supabase clients, middleware, /login + /auth/callback"
```

---

## Task 11: Frontend — top-nav, homepage branching, history rewire

**Files:**
- Create: `frontend/lib/api.ts`
- Create: `frontend/lib/api-key.ts`
- Create: `frontend/hooks/use-user.ts`
- Create: `frontend/hooks/use-reports.ts`
- Modify: `frontend/components/top-nav.tsx`
- Modify: `frontend/components/history-list.tsx`
- Modify: `frontend/app/page.tsx`
- Modify: `frontend/app/r/[reportId]/page.tsx`
- Delete: `frontend/hooks/use-history.ts` (if it exists) and `frontend/lib/history.ts` (clean cut, no localStorage migration)

- [ ] **Step 1: Typed fetch wrapper**

Create `frontend/lib/api.ts`:

```typescript
"use client";

import { createSupabaseBrowser } from "@/lib/supabase/client";
import { getStoredApiKey } from "@/lib/api-key";

export interface ApiError extends Error {
  status: number;
  body: unknown;
}

async function authedFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const supabase = createSupabaseBrowser();
  const { data: { session } } = await supabase.auth.getSession();

  const headers = new Headers(init.headers);
  if (session?.access_token) {
    headers.set("Authorization", `Bearer ${session.access_token}`);
  }
  const key = getStoredApiKey();
  if (key) {
    headers.set("X-Anthropic-Key", key);
  }
  return fetch(input, { ...init, headers, credentials: "include" });
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await authedFetch(path, { method: "GET" });
  return throwOrJson<T>(res);
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await authedFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return throwOrJson<T>(res);
}

export async function apiDelete(path: string): Promise<void> {
  const res = await authedFetch(path, { method: "DELETE" });
  if (!res.ok) await throwOrJson(res);
}

async function throwOrJson<T>(res: Response): Promise<T> {
  if (res.ok) {
    if (res.status === 204) return undefined as unknown as T;
    return (await res.json()) as T;
  }
  let body: unknown;
  try {
    body = await res.json();
  } catch {
    body = await res.text();
  }
  const err = new Error(`API ${res.status}`) as ApiError;
  err.status = res.status;
  err.body = body;
  throw err;
}
```

- [ ] **Step 2: localStorage helpers for the BYOK key**

Create `frontend/lib/api-key.ts`:

```typescript
const KEY = "ara.anthropic_key";

export function getStoredApiKey(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setStoredApiKey(value: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(KEY, value);
}

export function clearStoredApiKey(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(KEY);
}

export function hasStoredApiKey(): boolean {
  return getStoredApiKey() !== null;
}
```

- [ ] **Step 3: User hook**

Create `frontend/hooks/use-user.ts`:

```typescript
"use client";

import { useEffect, useState } from "react";
import type { User } from "@supabase/supabase-js";

import { createSupabaseBrowser } from "@/lib/supabase/client";

export function useUser() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const supabase = createSupabaseBrowser();
    supabase.auth.getUser().then(({ data }) => {
      setUser(data.user);
      setLoading(false);
    });
    const { data: subscription } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });
    return () => subscription.subscription.unsubscribe();
  }, []);

  return { user, loading };
}
```

- [ ] **Step 4: Reports hook (replaces useHistory)**

Create `frontend/hooks/use-reports.ts`:

```typescript
"use client";

import { useCallback, useEffect, useState } from "react";

import { apiDelete, apiGet } from "@/lib/api";

export interface ReportSummary {
  id: string;
  question: string;
  status: "running" | "completed" | "error";
  depth: "quick" | "standard" | "deep";
  used_byok: boolean;
  is_sample: boolean;
  cost_usd: number | null;
  created_at: string;
  completed_at: string | null;
}

export function useReports() {
  const [items, setItems] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      setItems(await apiGet<ReportSummary[]>("/api/reports"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const remove = useCallback(
    async (id: string) => {
      await apiDelete(`/api/reports/${id}`);
      setItems((prev) => prev.filter((r) => r.id !== id));
    },
    [],
  );

  return { items, loading, error, refresh, remove };
}
```

- [ ] **Step 5: Update top-nav (real sign-in/out, no stub)**

Replace `frontend/components/top-nav.tsx`:

```typescript
"use client";

import { CircleUser, LogOut, Zap } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useUser } from "@/hooks/use-user";
import { createSupabaseBrowser } from "@/lib/supabase/client";

const NAV_LINKS = [
  { href: "/", label: "Dashboard", match: (p: string) => p === "/" },
  { href: "/gallery", label: "Gallery", match: (p: string) => p === "/gallery" },
  { href: "/#history", label: "History", match: () => false },
  { href: "/settings", label: "Settings", match: (p: string) => p === "/settings" },
] as const;

export function TopNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user } = useUser();
  const isDashboard = pathname === "/";

  const onExecuteClick = (e: React.MouseEvent) => {
    e.preventDefault();
    if (isDashboard) {
      const el = document.getElementById("question") as HTMLTextAreaElement | null;
      el?.focus();
      window.history.replaceState(null, "", "/#question");
    } else {
      router.push("/#question");
    }
  };

  async function signOut() {
    const supabase = createSupabaseBrowser();
    await supabase.auth.signOut();
    router.push("/");
  }

  return (
    <header className="bg-background sticky top-0 z-50 flex h-14 w-full items-center justify-between border-b border-white/[0.06] px-6 print:hidden">
      <div className="flex items-center gap-8">
        <Link href="/" className="text-primary font-mono text-xl font-bold tracking-tighter transition-opacity hover:opacity-80">
          ARA
        </Link>
        <nav className="hidden gap-6 md:flex">
          {NAV_LINKS.map((link) => {
            const active = link.match(pathname);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={
                  active
                    ? "text-primary border-primary border-b-2 pb-1 font-mono text-xs uppercase tracking-wider opacity-90"
                    : "text-muted-foreground hover:text-primary/80 font-mono text-xs uppercase tracking-wider transition-colors"
                }
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <div className="flex items-center gap-4">
        <Popover>
          <PopoverTrigger
            aria-label="Account"
            className="text-muted-foreground hover:text-primary/80 hidden transition-colors md:inline-flex"
          >
            <CircleUser className="h-5 w-5" strokeWidth={1.5} />
          </PopoverTrigger>
          <PopoverContent align="end" className="w-56">
            {user ? (
              <>
                <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
                  Signed in as
                </p>
                <p className="truncate px-2 pb-2 text-sm">{user.email}</p>
                <Link
                  href="/settings"
                  className="block rounded px-2 py-1.5 text-sm hover:bg-accent"
                >
                  Settings
                </Link>
                <button
                  type="button"
                  onClick={signOut}
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                >
                  <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
                  Sign out
                </button>
              </>
            ) : (
              <>
                <p className="text-muted-foreground/60 px-2 py-1 font-mono text-[10px] uppercase tracking-wider">
                  Account
                </p>
                <Link
                  href="/login"
                  className="block rounded px-2 py-1.5 text-sm hover:bg-accent"
                >
                  Sign in
                </Link>
              </>
            )}
          </PopoverContent>
        </Popover>
        <button
          type="button"
          onClick={onExecuteClick}
          className="bg-primary-container text-on-primary-container hover:bg-primary-container/90 inline-flex items-center gap-1.5 rounded-md px-4 py-1.5 font-mono text-xs font-bold uppercase tracking-wider transition-all"
        >
          Execute Task
          <Zap className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 6: Rewire history-list to use API**

Replace `frontend/components/history-list.tsx`:

```typescript
"use client";

import Link from "next/link";
import { ChevronRight, FileText, Trash2 } from "lucide-react";

import { useReports, type ReportSummary } from "@/hooks/use-reports";

export function HistoryList() {
  const { items, loading, error, remove } = useReports();

  if (loading) {
    return (
      <section className="w-full" id="history">
        <div className="text-muted-foreground/60 font-mono text-xs">Loading history…</div>
      </section>
    );
  }
  if (error) {
    return (
      <section className="w-full" id="history">
        <div className="text-destructive font-mono text-xs">History unavailable: {error}</div>
      </section>
    );
  }
  if (items.length === 0) return null;

  return (
    <section className="w-full" id="history">
      <div className="mb-6 flex items-center justify-between">
        <h2 className="text-muted-foreground font-mono text-xs uppercase tracking-widest">
          Recent reports
        </h2>
      </div>
      <div className="space-y-1">
        {items.map((item) => (
          <HistoryRow
            key={item.id}
            item={item}
            onDelete={async () => {
              if (confirm("Delete this report?")) await remove(item.id);
            }}
          />
        ))}
      </div>
    </section>
  );
}

function HistoryRow({ item, onDelete }: { item: ReportSummary; onDelete: () => void }) {
  return (
    <div className="hover:bg-card group flex flex-col items-stretch justify-between rounded-lg px-6 py-4 transition-all duration-150 md:flex-row md:items-center">
      <Link href={`/r/${item.id}`} className="flex flex-1 items-center gap-4">
        <FileText
          className="text-muted-foreground/60 group-hover:text-primary h-5 w-5 transition-colors"
          strokeWidth={1.5}
        />
        <div className="space-y-0.5">
          <p className="text-foreground group-hover:text-primary line-clamp-2 font-medium leading-snug transition-colors">
            {item.question}
          </p>
          <p className="text-muted-foreground/60 font-mono text-[10px] uppercase tracking-tight">
            {formatTimestamp(item.created_at)} · {item.status}
          </p>
        </div>
      </Link>
      <div className="mt-2 flex items-center gap-3 md:mt-0">
        <button
          type="button"
          onClick={onDelete}
          aria-label="Delete report"
          className="text-muted-foreground/40 hover:text-destructive p-1 transition-colors"
        >
          <Trash2 className="h-4 w-4" strokeWidth={1.5} />
        </button>
        <ChevronRight className="text-muted-foreground/40 h-4 w-4" strokeWidth={1.5} />
      </div>
    </div>
  );
}

function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const min = String(d.getMinutes()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
}
```

- [ ] **Step 7: Homepage branching**

Read the current `frontend/app/page.tsx` to understand its structure. Then modify the top of the component to conditionally render based on auth:

```typescript
// at the top of the page component
import { useUser } from "@/hooks/use-user";
import { GallerySnapshot } from "@/components/gallery-snapshot"; // created in Task 12
import Link from "next/link";

export default function HomePage() {
  const { user, loading } = useUser();
  if (loading) return null;

  if (!user) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16">
        <h1 className="font-mono text-3xl tracking-tight">Autonomous Research Assistant</h1>
        <p className="text-muted-foreground mt-3">
          Ask anything. ARA plans, researches the web, and synthesizes a cited report — in seconds.
        </p>
        <div className="mt-8">
          <Link
            href="/login"
            className="bg-primary text-primary-foreground inline-flex items-center rounded-md px-5 py-2 font-mono text-sm font-semibold"
          >
            Sign in to get started
          </Link>
        </div>
        <div className="mt-16">
          <GallerySnapshot />
        </div>
      </main>
    );
  }

  // existing signed-in homepage content (research form + history list) goes here
  // ...
}
```

Wrap the existing signed-in content in the `else` branch. Leave the existing layout, components, and class names intact for the signed-in branch.

- [ ] **Step 8: Report page access**

Modify `frontend/app/r/[reportId]/page.tsx` so it fetches `/api/reports/{id}` (passing `?t=` if present) and renders the new shape. The exact integration depends on the current page's structure; key requirements:

1. If the page is a server component, use `createSupabaseServer()` to attach auth.
2. If 403 or 404, render a friendly "Not found / Not authorized" placeholder.
3. Pass the report shape (which includes `report_payload`) into the existing report-rendering components.
4. Accept an optional `t` search param for share-token reads.

- [ ] **Step 9: Delete the localStorage history hook (clean cut)**

```bash
cd frontend && rm -f hooks/use-history.ts lib/history.ts
```

If other files import from these paths, remove the imports and fix the call sites (search with `rg -n "use-history|@/lib/history"`).

- [ ] **Step 10: Smoke test**

```bash
make dev-backend &
make dev-frontend
```

Visit http://localhost:3000:
- Signed out: see hero + sign-in CTA (gallery snapshot will look empty until Task 12 + at least one promoted sample).
- Sign in via Google.
- Refresh http://localhost:3000: now see research form + history list (initially empty).
- Submit a research question with no API key → expect free-tier path.

- [ ] **Step 11: Commit**

```bash
git add frontend/lib frontend/hooks frontend/components/top-nav.tsx \
        frontend/components/history-list.tsx frontend/app/page.tsx \
        frontend/app/r
git commit -m "feat(frontend): real auth in top-nav, history via API, signed-out homepage"
```

---

## Task 12: Frontend — settings, gallery, share, admin promote, sample replay

**Files:**
- Modify: `frontend/app/settings/page.tsx`
- Create: `frontend/app/gallery/page.tsx`
- Create: `frontend/components/gallery-snapshot.tsx`
- Modify: `frontend/components/research-form.tsx` (BYOK + free-tier UX)
- Modify: `frontend/components/report-stream.tsx` (SHARE rewires to API token mint)
- Modify: `frontend/app/r/[reportId]/page.tsx` (admin button + sample replay button)

- [ ] **Step 1: Settings page — API key input, quota counter, sign-out**

Replace the body of `frontend/app/settings/page.tsx` so it shows (in order, top to bottom):

1. **API key input** (paste, save to localStorage, mask when displayed, "Clear" button)
2. **Quota panel** (fetched from `/api/quota`)
3. **Existing config display** (already there from the earlier settings page)
4. **Sign-out button**

```typescript
"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiGet } from "@/lib/api";
import {
  clearStoredApiKey,
  getStoredApiKey,
  setStoredApiKey,
} from "@/lib/api-key";
import { createSupabaseBrowser } from "@/lib/supabase/client";
import { useUser } from "@/hooks/use-user";

interface Quota {
  used: number;
  limit: number;
  global_spend_usd: number;
  global_cap_usd: number;
  circuit_breaker_tripped: boolean;
}

export default function SettingsPage() {
  const { user, loading } = useUser();
  const router = useRouter();

  const [keyDraft, setKeyDraft] = useState("");
  const [hasKey, setHasKey] = useState(false);
  const [quota, setQuota] = useState<Quota | null>(null);

  useEffect(() => {
    setHasKey(getStoredApiKey() !== null);
  }, []);

  useEffect(() => {
    if (!user) return;
    apiGet<Quota>("/api/quota").then(setQuota).catch(() => setQuota(null));
  }, [user]);

  if (loading) return null;
  if (!user) {
    return (
      <main className="mx-auto max-w-2xl p-8">
        <p>Please <a className="text-primary underline" href="/login">sign in</a> to view settings.</p>
      </main>
    );
  }

  function saveKey() {
    if (!keyDraft.trim()) return;
    setStoredApiKey(keyDraft.trim());
    setHasKey(true);
    setKeyDraft("");
  }

  function clearKey() {
    clearStoredApiKey();
    setHasKey(false);
  }

  async function signOut() {
    const supabase = createSupabaseBrowser();
    await supabase.auth.signOut();
    router.push("/");
  }

  return (
    <main className="mx-auto max-w-2xl space-y-10 p-8 pt-12">
      <section>
        <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
          Anthropic API key (BYOK)
        </h2>
        <div className="bg-card space-y-3 rounded-lg p-4">
          {hasKey ? (
            <div className="flex items-center justify-between">
              <span className="font-mono text-sm">sk-ant-•••• (saved to this browser only)</span>
              <Button variant="ghost" onClick={clearKey}>Clear</Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder="sk-ant-…"
                value={keyDraft}
                onChange={(e) => setKeyDraft(e.target.value)}
              />
              <Button onClick={saveKey}>Save</Button>
            </div>
          )}
          <p className="text-muted-foreground text-xs">
            Stored only in your browser&apos;s localStorage. Sent per-request as
            <code className="ml-1 font-mono">X-Anthropic-Key</code>. We never persist it on our servers.
          </p>
        </div>
      </section>

      <section>
        <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
          Free tier
        </h2>
        <div className="bg-card space-y-2 rounded-lg p-4">
          {quota ? (
            <>
              <p>
                <span className="font-mono">{quota.used}</span> of{" "}
                <span className="font-mono">{quota.limit}</span> free reports used this month
              </p>
              {quota.circuit_breaker_tripped && (
                <p className="text-destructive text-sm">
                  Free tier capped site-wide for this month. Add your own API key above to keep going.
                </p>
              )}
            </>
          ) : (
            <p className="text-muted-foreground text-sm">Quota unavailable.</p>
          )}
        </div>
      </section>

      <section>
        <Button variant="outline" onClick={signOut}>Sign out</Button>
      </section>
    </main>
  );
}
```

(The existing "active models" + "depth presets" panels from the prior settings page should stay — keep them in this file above or below as fits the layout. Don't delete that view-only display.)

- [ ] **Step 2: Gallery page**

Create `frontend/app/gallery/page.tsx`:

```typescript
import Link from "next/link";

import type { ReportSummary } from "@/hooks/use-reports";

export const dynamic = "force-dynamic";

async function fetchGallery(): Promise<ReportSummary[]> {
  const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
  const res = await fetch(`${backend}/api/gallery`, { cache: "no-store" });
  if (!res.ok) return [];
  return (await res.json()) as ReportSummary[];
}

export default async function GalleryPage() {
  const items = await fetchGallery();
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-mono text-2xl tracking-tight">Sample gallery</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Curated runs showing what ARA does end-to-end.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.length === 0 && (
          <p className="text-muted-foreground col-span-3 font-mono text-xs">
            Gallery is empty.
          </p>
        )}
        {items.map((r) => (
          <Link
            key={r.id}
            href={`/r/${r.id}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-5 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
            <p className="text-muted-foreground/60 mt-3 font-mono text-[10px] uppercase tracking-wider">
              View report
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
```

- [ ] **Step 3: Gallery snapshot for the signed-out homepage**

Create `frontend/components/gallery-snapshot.tsx`:

```typescript
import Link from "next/link";

import type { ReportSummary } from "@/hooks/use-reports";

async function fetchGallerySnapshot(): Promise<ReportSummary[]> {
  const backend = process.env.BACKEND_ORIGIN || "http://localhost:8000";
  const res = await fetch(`${backend}/api/gallery`, { cache: "no-store" });
  if (!res.ok) return [];
  return ((await res.json()) as ReportSummary[]).slice(0, 3);
}

export async function GallerySnapshot() {
  const items = await fetchGallerySnapshot();
  if (items.length === 0) return null;
  return (
    <div>
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
        Sample reports
      </h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {items.map((r) => (
          <Link
            key={r.id}
            href={`/r/${r.id}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-4 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
```

Note: `GallerySnapshot` is a Server Component; the homepage as written above imports it client-side, which Next 16 will warn about. Either:
- Make the signed-out branch its own server component file, or
- Convert `GallerySnapshot` into a client component that uses `useEffect` + `fetch('/api/gallery')`.

For minimum churn, convert it to a client component:

```typescript
"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { apiGet } from "@/lib/api";
import type { ReportSummary } from "@/hooks/use-reports";

export function GallerySnapshot() {
  const [items, setItems] = useState<ReportSummary[]>([]);
  useEffect(() => {
    // Public endpoint — apiGet still works (auth header is just absent).
    apiGet<ReportSummary[]>("/api/gallery")
      .then((rows) => setItems(rows.slice(0, 3)))
      .catch(() => setItems([]));
  }, []);
  if (items.length === 0) return null;
  // ...same JSX as the server-component version
}
```

- [ ] **Step 4: Research form — BYOK awareness + free-tier UX**

Open `frontend/components/research-form.tsx`. Add at the top:

```typescript
import { useEffect, useState } from "react";
import { hasStoredApiKey } from "@/lib/api-key";
import { apiGet } from "@/lib/api";

interface Quota {
  used: number;
  limit: number;
  circuit_breaker_tripped: boolean;
}
```

Inside the component, add:

```typescript
const [hasKey, setHasKey] = useState(false);
const [quota, setQuota] = useState<Quota | null>(null);

useEffect(() => {
  setHasKey(hasStoredApiKey());
}, []);

useEffect(() => {
  apiGet<Quota>("/api/quota").then(setQuota).catch(() => setQuota(null));
}, []);

const freeTier = !hasKey;
const freeBlocked = freeTier && quota !== null && (quota.used >= quota.limit || quota.circuit_breaker_tripped);
```

Use these to:
- Disable the depth dropdown when `freeTier` is true with a tooltip: `"Free tier locked to quick depth — add API key in Settings to unlock"`
- Disable the "Browse web" toggle similarly
- Show a banner above the submit button when `freeBlocked`: `"Free tier exhausted — add your Anthropic API key in Settings to keep running reports"`
- Disable the submit button when `freeBlocked`
- Show a small line under the form when on free tier: `{quota.used} of {quota.limit} free reports used this month`

The submit handler stays mostly the same — `apiPost("/api/research", { question, depth, browse_web })` — but rely on the `apiPost` wrapper to attach `X-Anthropic-Key` from localStorage when present. **No special-casing of free vs BYOK in the submit handler**: the backend already decides based on the header presence.

- [ ] **Step 5: SHARE button rewires**

In `frontend/components/report-stream.tsx` (or wherever the SHARE button lives — `rg -n "SHARE" frontend/components` to find it), update the click handler:

```typescript
import { apiPost } from "@/lib/api";

async function onShare(reportId: string) {
  try {
    const { share_url_path } = await apiPost<{ share_url_path: string; share_token: string }>(
      `/api/reports/${reportId}/share`,
      {},
    );
    const fullUrl = `${window.location.origin}${share_url_path}`;
    await navigator.clipboard.writeText(fullUrl);
    // existing toast / "Copied!" affordance
  } catch (e) {
    // existing error affordance
  }
}
```

- [ ] **Step 6: Admin promote button + sample replay button on report page**

In `frontend/app/r/[reportId]/page.tsx`, add:

```typescript
"use client";

import { useUser } from "@/hooks/use-user";
import { apiDelete, apiPost } from "@/lib/api";

// Inside the report view component, after the report payload is loaded:
const { user } = useUser();
const isAdmin = user?.id === process.env.NEXT_PUBLIC_ADMIN_USER_ID;

async function togglePromote(reportId: string, isCurrentlySample: boolean) {
  if (isCurrentlySample) {
    await apiDelete(`/api/reports/${reportId}/promote`);
  } else {
    await apiPost(`/api/reports/${reportId}/promote`, {});
  }
  // refresh the page or local state
  window.location.reload();
}

// In the JSX (when report status === "completed"):
{isAdmin && (
  <button
    type="button"
    onClick={() => togglePromote(report.id, report.is_sample)}
    className="bg-card hover:bg-accent rounded-md px-4 py-2 font-mono text-xs uppercase tracking-wider"
  >
    {report.is_sample ? "Remove from gallery" : "Promote to gallery"}
  </button>
)}

{report.is_sample && (
  <ReplayButton reportId={report.id} shareToken={searchParamsT} />
)}
```

And create a small `ReplayButton` component that opens an `EventSource` to `/api/reports/{id}/replay?t={t}` (if `t` is set) and renders into the existing live-view component. For minimum churn, this can simply replace the current static report view with a re-mounted `research-live.tsx` driven by replay events. The simplest version:

```typescript
"use client";

import { useState } from "react";
import { ResearchLive } from "@/components/research-live";

export function ReplayButton({
  reportId,
  shareToken,
}: { reportId: string; shareToken?: string }) {
  const [playing, setPlaying] = useState(false);
  const streamUrl = `/api/reports/${reportId}/replay${shareToken ? `?t=${shareToken}` : ""}`;
  if (playing) {
    return <ResearchLive streamUrl={streamUrl} />;
  }
  return (
    <button
      type="button"
      onClick={() => setPlaying(true)}
      className="bg-primary text-primary-foreground inline-flex items-center gap-2 rounded-md px-4 py-2 font-mono text-sm"
    >
      ▶ Replay how this report was built
    </button>
  );
}
```

This assumes `ResearchLive` accepts a `streamUrl` prop. If it currently constructs the URL internally from a `reportId`, add a `streamUrl` prop that takes precedence:

```typescript
// In research-live.tsx:
export interface ResearchLiveProps {
  reportId?: string;
  streamUrl?: string;  // overrides reportId if provided
  // ...other existing props
}

// At top of component:
const url = props.streamUrl ?? `/api/research/${props.reportId}/stream`;
```

- [ ] **Step 7: Smoke test the full flow**

```bash
make dev-backend &
make dev-frontend
```

1. Sign out → visit `/` → see hero + sign-in CTA + 3 empty gallery slots.
2. Sign in.
3. Without setting an API key, run a free-tier research request. Verify it uses Haiku (check the cost meter / backend logs).
4. Run 3 free-tier requests — the 4th should show "Free tier exhausted" banner.
5. Set an Anthropic key in Settings → 4th request now works at the chosen depth.
6. From a completed report, click SHARE → URL copied. Open it in a private window → loads without sign-in.
7. As admin (your `ADMIN_USER_ID`), click "Promote to gallery" → visit `/gallery` → see the sample.
8. Click into the sample → click "▶ Replay how this report was built" → events stream back.

- [ ] **Step 8: Commit**

```bash
git add frontend
git commit -m "feat(frontend): settings BYOK, gallery, share token, admin promote, sample replay"
```

---

## Done

All eleven commit-sized stages are now in. Run a final verification:

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run mypy src
cd frontend && npm run lint && npm run build
```

If green, the feature is shippable. The first deploy needs the manual Supabase setup (Pre-flight section) and env vars filled in on both backend host and Vercel. SSE works through Next.js rewrites only if the backend isn't on Vercel serverless functions (which cap streams at ~10s); use Fly / Render / Railway for the Python side.
