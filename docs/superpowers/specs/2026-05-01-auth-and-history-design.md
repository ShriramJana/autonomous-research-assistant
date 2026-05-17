# Auth, per-account history, BYOK + sample gallery

## Goal

Make ARA "actually usable" by giving each visitor a persistent identity
and a personal report history that survives browser/device changes. At
the same time, make the live demo broadcast-safe — visitors can play
with ARA without burning the operator's Anthropic credits, but the
operator's cost is bounded by a hard monthly cap.

This is the v1 → v2 transition. Several items in
[CLAUDE.md](../../../CLAUDE.md)'s "intentionally OUT" list — auth,
database persistence — are explicitly in scope for this design and only
this design.

## Scope

**In:**

- Supabase Auth (Google OAuth + magic link)
- Supabase Postgres persistence for reports + events (replaces the
  in-memory `ReportStore`)
- Per-user report history with three access paths: owner, public
  sample, shared via unguessable token
- BYOK (Bring Your Own Key) via per-request `X-Anthropic-Key` header
  stored only in the user's browser
- Free tier (no key required): 3 reports / user / month, quick depth,
  Haiku models, no web search; gated by a global monthly spend cap
- Curated 3-report sample gallery, admin-promoted from the operator's
  own runs; visitors get static-by-default with a "Replay how this
  report was built" button that replays the full SSE event stream
- Cost circuit breaker: when free-tier monthly spend crosses
  `FREE_TIER_GLOBAL_CAP_USD`, free tier auto-disables site-wide until
  the 1st of next month

**Explicitly out:**

- Follow-up Q&A on reports (the "research assistant" chat feature) —
  schema-compatible, future PR
- Document upload as research context — future PR
- Projects / folders / tags — future PR
- "1 free report for signed-out users" — schema-compatible and
  env-controllable, future PR
- Server-side rate limits (each user's spend is governed by their own
  Anthropic account quota)
- localStorage history migration on first sign-in (clean cut; existing
  browser-only history is dropped)
- Soft-delete graveyard for reports (DELETE is hard-delete)
- Per-key cost caps for BYOK users (Anthropic account handles this)

## Architecture

```
┌─────────────────────────────┐         ┌─────────────────────────────┐
│  Next.js 16 frontend        │         │  Supabase                   │
│  - @supabase/ssr (cookies)  │◄───────►│  - Auth (Google, magic link)│
│  - /login, /gallery         │         │  - Postgres + RLS           │
│  - BYOK in /settings        │         │                             │
│    (localStorage only)      │         └─────────────┬───────────────┘
│  - History from API         │                       │
└──────┬──────────────────────┘                       │ JWT verification
       │ HTTP + SSE (same-origin via Next rewrites)   │
       │ Cookies: sb-access-token                     │
       │ Header: X-Anthropic-Key (BYOK only)          │
       ▼                                               │
┌─────────────────────────────────────────────────────▼─────┐
│  FastAPI backend                                           │
│  - get_current_user (verifies Supabase JWT via shared sec) │
│  - require_admin (compares user.id to ADMIN_USER_ID env)   │
│  - SupabaseReportStore (asyncpg, implements ReportStore)   │
│  - quota.check_free_tier (per-user + global cap)           │
│  - LLM client takes api_key per construction               │
└────────────────────────────────────────────────────────────┘
```

**Invariants preserved from v1:**

- `ReportStore` Protocol unchanged. Only the implementation swaps.
- SSE event types and ordering invariants from
  [test_sse_contract.py](../../../backend/tests/test_sse_contract.py)
  unchanged.
- LangGraph DAG unchanged. Researcher fan-out inside `research_node`
  unchanged.
- `pricing.py` cost meter unchanged.

**Conceptually new:**

- Anthropic API key stops being a global server secret. It is per-run
  input, sourced either from the user's browser localStorage (BYOK) or
  the operator's env var (free tier). Never persisted server-side.
- Reports gain ownership (`owner_id`) and the three-path access model.
- Same-origin via Next.js `rewrites` solves SSE auth without
  custom-header gymnastics — browser cookies are sent automatically
  with `EventSource`.

## Schema

```sql
-- 1. App-level user data, mirrors auth.users 1:1
create table user_profiles (
  id           uuid primary key references auth.users(id) on delete cascade,
  created_at   timestamptz not null default now(),
  display_name text
);

-- 2. The main entity
create table reports (
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
create index reports_owner_created_idx on reports (owner_id, created_at desc);
create index reports_sample_idx on reports (is_sample) where is_sample;

-- 3. Append-only event log (drives SSE replay, live + after-the-fact)
create table report_events (
  id          bigserial primary key,
  report_id   uuid not null references reports(id) on delete cascade,
  event       jsonb not null,
  created_at  timestamptz not null default now()
);
create index report_events_report_idx on report_events (report_id, id);
```

**Derivable, intentionally not stored:**

- Per-user free quota used this month =
  `count(*) from reports where owner_id = $1 and used_byok = false and created_at >= date_trunc('month', now())`
- Global free-tier spend this month =
  `sum(cost_usd) from reports where used_byok = false and created_at >= date_trunc('month', now())`

Single source of truth, no counters to drift. Cached in-process for 30s
only if it ever becomes a hotspot (deferred — not a launch blocker).

**RLS posture:** enabled on all three tables with owner-only policies
as defense-in-depth. The FastAPI backend uses the Supabase **service
role key** (bypasses RLS) and enforces access in Python with the
three-path check (`owner_id == user.id` ∨ `is_sample == true` ∨
`share_token == ?t=`). The browser never talks to Supabase directly for
app data — only for auth. Access logic lives in one place.

**JSONB for `report_payload`:** the existing `ReportEnvelope` is a
deeply nested Pydantic model (sections, citations, sources, key_facts,
citation UUIDs). Normalizing is five tables of join misery for zero
query benefit — we never query *into* report contents, we load the
whole thing for display.

## API surface

### New endpoints

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/me` | Current user (or 401) | Authed |
| GET | `/api/reports` | List own reports, newest first | Authed (own) |
| GET | `/api/reports/{id}` | Fetch one report | Owner ∨ sample ∨ valid `?t=` token |
| DELETE | `/api/reports/{id}` | Hard-delete | Owner |
| POST | `/api/reports/{id}/share` | Mint or return `share_token` | Owner |
| DELETE | `/api/reports/{id}/share` | Revoke `share_token` | Owner |
| POST | `/api/reports/{id}/promote` | Flip `is_sample = true` | Admin |
| DELETE | `/api/reports/{id}/promote` | Flip `is_sample = false` | Admin |
| GET | `/api/reports/{id}/replay` | Stream saved events back as SSE with brief gaps | Owner ∨ sample ∨ valid `?t=` token |
| GET | `/api/gallery` | List `is_sample = true` reports | Public |
| GET | `/api/quota` | Free runs left this month + circuit-breaker status | Authed |

### Changed endpoints

- **`POST /api/research`** — now requires auth. Accepts optional
  `X-Anthropic-Key` header.
  - **Header present (BYOK):** uses that key, `used_byok = true`,
    accepts any `depth` / `browse_web` / model preset.
  - **Header absent (free tier):**
    1. Per-user check: count of free-tier rows this month <
       `FREE_TIER_PER_USER_MONTHLY` (default 3)
    2. Global check: sum of free-tier spend this month <
       `FREE_TIER_GLOBAL_CAP_USD` (default $20)
    3. Server-side overrides applied: `depth = quick`,
       `browse_web = false`, all three models forced to
       `claude-haiku-4-5`
    4. If either check fails → **402 Payment Required** with structured
       body
       `{ error: "free_tier_exhausted" | "free_tier_global_cap_reached", message, limit, used }`

- **`GET /api/research/{id}/stream`** — same three-path access check as
  `/api/reports/{id}`.

- **`GET /api/config`** — unchanged shape. Free-tier overrides happen
  at request time, not in config.

### Replay semantics

`GET /api/reports/{id}/replay` streams the full sequence of saved
`report_events` rows as SSE, with a small interval (~50–150ms) between
events so the visitor sees the planner output appear, researchers fan
out, synthesis tokens stream in — the same UX as a live run, fed from
the persisted log instead of in-flight events. Frontend reuses the
existing `research-live.tsx` component, parameterized to consume from
the replay endpoint.

Replay is **on-demand**, not auto-play. Sample report page renders the
finished synthesis immediately (fast first paint) with a prominent
"▶ Replay how this report was built" button that triggers the replay
stream.

## Backend modules

**New:**

```
backend/src/ara/
  auth/
    __init__.py
    jwt.py            # verifies Supabase JWT, returns User
    dependencies.py   # get_current_user, require_admin, get_optional_user
  storage/
    supabase.py       # SupabaseReportStore — implements ReportStore Protocol
  quota.py            # free-tier checks (per-user + global)
migrations/
  001_initial.sql     # tables + RLS policies from "Schema" section
```

**Refactored:**

- **`runtime/orchestrator.py`** — `run_report(...)` accepts
  `RuntimeOverrides { api_key, models, options }` instead of pulling
  from `settings`. Threads the key through to every LLM call. Writes
  status / cost / payload back to the `reports` row on completion.
  Partial-failure semantics (`ResearcherError` → degraded
  `SubQueryFinding`) preserved.
- **`llm/`** — Anthropic client takes `api_key` per construction. No
  module-level singleton; one client per run.
- **`api/routes.py`** — gains the new endpoints, all gated by
  `Depends(get_current_user)` except `GET /api/gallery` and the
  publicly-accessible report read paths. Reads `X-Anthropic-Key`. Calls
  `quota.check_free_tier(...)` for the free-tier branch.
- **`config.py`** — new settings: `SUPABASE_URL`,
  `SUPABASE_JWT_SECRET`, `SUPABASE_DB_URL`, `ADMIN_USER_ID`,
  `FREE_TIER_PER_USER_MONTHLY=3`, `FREE_TIER_GLOBAL_CAP_USD=20.0`.
  Existing `ANTHROPIC_API_KEY` stays — repurposed as the free-tier
  server key.

**`SupabaseReportStore` — Protocol implementation:**

- `create(report_id, question, owner_id, depth, browse_web, used_byok)` →
  `INSERT INTO reports`. (Protocol signature gains parameters; this is
  the only backwards-incompatible Protocol change.)
- `put_event(report_id, event)` → `INSERT INTO report_events` + fan-out
  to in-process live subscribers (same `asyncio.Queue` mechanism as the
  in-memory store).
- `subscribe(report_id)` → register live queue, replay buffered events
  from `report_events` (last 50 by id), then yield live events.
  Replay source moves from Python deque to Postgres SELECT;
  ordering/no-duplication invariants preserved (queue registered
  before SELECT snapshot, both synchronous → no interleave window).
- `close(report_id)` →
  `UPDATE reports SET status, cost_usd, report_payload, completed_at`,
  then None-sentinel to live queues.

**In-memory pubsub stays.** Single-process for v1; LISTEN/NOTIFY is
overkill. The Protocol abstracts both — a future multi-instance deploy
adds a `RedisReportStore` (or LISTEN/NOTIFY variant) without touching
agents.

**Auth verification:** Supabase issues HS256-signed JWTs by default
(some newer projects use ES256 — see Open Risks). Backend verifies
with `pyjwt.decode(token, jwt_secret, algorithms=['HS256'], audience='authenticated')`,
returns `User { id: UUID, email: str }`. No round-trip to Supabase per
request — JWT is self-validating.

**New dependencies (`pyproject.toml`):**

- `pyjwt[crypto]` — JWT verification
- `asyncpg` — Postgres driver, raw parameterized SQL (no ORM; ARA's
  domain doesn't need one)

**Notably not added:** `supabase-py` (clunky; we only need JWT verify +
Postgres, both have better direct deps), Alembic (manual `.sql` files
applied via Supabase SQL editor are fine at this scale).

## Frontend changes

**New files:**

```
frontend/
  app/
    login/page.tsx              # Google OAuth + magic-link email
    auth/callback/route.ts      # OAuth code exchange
    gallery/page.tsx            # public sample gallery
  lib/
    supabase/client.ts          # browser Supabase client
    supabase/server.ts          # cookie-aware server client
    api.ts                      # typed fetch wrapper (auth + X-Anthropic-Key)
    api-key.ts                  # localStorage helpers (ara.anthropic_key)
  middleware.ts                 # refresh Supabase session on every request
  hooks/
    use-user.ts                 # current user + signed-in state
    use-quota.ts                # GET /api/quota
    use-reports.ts              # GET /api/reports (replaces useHistory)
```

**Modified files:**

- **`components/top-nav.tsx`** — replace stub. Signed-out: `Sign in` →
  `/login`. Signed-in: email + Sign out + Settings link in popover.
- **`components/history-list.tsx`** — drop `useHistory` localStorage;
  switch to `useReports()` API hook. Trash button per row →
  `DELETE /api/reports/{id}`. Loading skeleton.
- **`app/page.tsx`** — branch on auth:
  - **Signed-out:** centered hero + Sign-in CTA + 3-card sample gallery
    preview.
  - **Signed-in:** existing research form + history list.
- **`app/settings/page.tsx`** — gains:
  - API key input (paste-and-save, target = localStorage only; "We
    never store your key on our servers" copy)
  - Free-tier counter (`X of 3 free reports left this month` + circuit
    breaker status if tripped)
  - Sign-out button
- **`components/research-form.tsx`** — when no key in localStorage and
  quota permits: depth + browse-web disabled with tooltip explaining
  free-tier lock. When quota exhausted: form disabled with banner.
  Submit reads localStorage key, attaches `X-Anthropic-Key` if present.
- **`components/report-stream.tsx` / `research-live.tsx`** — SHARE
  button hits `POST /api/reports/{id}/share`, copies the resulting
  `/r/{id}?t=<token>` URL.
- **`app/r/[reportId]/page.tsx`** — fetch via `GET /api/reports/{id}`
  (with optional `?t=` from URL); 404/403 if access denied. Admin
  (matched against `NEXT_PUBLIC_ADMIN_USER_ID`) sees Promote / Remove
  buttons on completed reports. **For samples specifically:**
  static-by-default render + "▶ Replay how this report was built"
  button that streams from `GET /api/reports/{id}/replay` and mounts
  the existing `research-live.tsx` against it.

**SSE auth wiring — same-origin via Next.js rewrites:**

`EventSource` doesn't support custom headers in browsers. Solved by
adding to `next.config.ts`:

```ts
rewrites: async () => [
  { source: '/api/:path*', destination: `${process.env.BACKEND_ORIGIN}/api/:path*` },
],
```

Frontend and backend appear same-origin; Supabase auth cookies
(`sb-access-token`) are sent automatically with `EventSource`. Backend
reads JWT from cookie when the `Authorization` header is absent. No
JWT-in-URL, works for both dev and prod.

**New frontend dependencies:** `@supabase/supabase-js`, `@supabase/ssr`.

## Cost model

| Tier | Who | Allowed | Server picks |
|---|---|---|---|
| Anonymous | Not signed in | Gallery only | n/a |
| Free | Signed in, no key | 3 reports/month, quick depth only, no browse-web | Haiku across all 3 agents |
| BYOK | Signed in, key in Settings | Unlimited, any depth, any model | User's choices honored |

**Global circuit breaker:** monthly free-tier spend derived from
`reports`. When the sum crosses `FREE_TIER_GLOBAL_CAP_USD` (default
$20), free tier auto-disables. UI shows: "Free tier capped this month —
sign in with your own API key to keep going." Resets the 1st of next
month. Operator's worst-case bill is mathematically bounded.

Math sanity-check at $20/mo cap, ~$0.04 avg quick-Haiku run: ~500 free
runs/month before tripping. With 3 runs/user/month, that's ~167 active
free users before the cap hits.

## Sample gallery

- Operator (admin) runs a question normally from their own account,
  likes the result, clicks **Promote to gallery** on the completed
  report.
- Backend sets `is_sample = true`. Report becomes publicly readable
  (anyone can view static synthesis + replay events).
- Admin gating: `user.id == ADMIN_USER_ID` env var. No role system.
- Initial gallery target: 3 reports. Refreshed at the operator's
  discretion (`DELETE /api/reports/{id}/promote` to remove).
- Suggested mix for the 3 launch samples: showcase a `deep`
  Sonnet/Opus run (not a free-tier Haiku run) so visitors see ARA at
  its best.

## Testing

- **Existing `test_sse_contract.py` must still pass** when run against
  `SupabaseReportStore` (Postgres fixture). The SSE
  ordering/monotonicity/round-trip invariants don't care which store
  backs them.
- **New `test_supabase_store.py`** — same Protocol conformance tests as
  the in-memory store, plus persistence-specific cases (subscriber
  joins after ring buffer fills; replay after process restart).
- **New `test_auth.py`** — JWT verify happy path, expired, wrong
  signature, missing claims, wrong audience.
- **New `test_quota.py`** — per-user under/at/over limit, global cap,
  BYOK bypass, month-boundary rollover (parametrized fake clock).
- **New `test_routes_auth.py`** — access matrix for
  `/api/reports/{id}` and `/stream`: owner / non-owner / sample /
  valid token / invalid token / no auth.
- **Frontend:** no existing tests; not adding. Manual browser smoke
  test is the gate.
- **Lint/type gates unchanged:** `ruff` + `mypy --strict` still pass
  on every commit (per [CLAUDE.md](../../../CLAUDE.md)).

## Implementation order (commit boundaries)

Eleven stages, eleven commits. Granular reverts cheap.

1. `migrations/001_initial.sql` + Supabase project bootstrapped
   (manual dashboard step documented in README)
2. Backend `auth/` module + JWT verification + `test_auth.py`
3. Backend `storage/supabase.py` + Protocol conformance tests
4. Backend orchestrator + LLM refactor (per-request `api_key` +
   `models` overrides)
5. Backend `quota.py` + `test_quota.py`
6. Backend `api/routes.py` — auth dependencies, new endpoints,
   `X-Anthropic-Key`, free-tier branch, `test_routes_auth.py`
7. Backend `GET /api/reports/{id}/replay` endpoint
8. Frontend Supabase clients + middleware + `/login` +
   `/auth/callback`
9. Frontend top-nav + signed-in/out homepage branching +
   history-list rewire
10. Frontend settings page (key input + quota counter + sign-out)
11. Frontend gallery + admin promote button + SHARE rewire +
    sample replay button

## Open risks

- **Supabase JWT algorithm.** New projects sometimes default to ES256
  (asymmetric, JWKS-based); older ones use HS256 (shared secret). The
  `auth/jwt.py` impl needs to handle whichever the project uses —
  verify when creating the Supabase project. One config knob; don't
  hardcode.
- **SSE in production behind same-origin rewrite.** Works in
  `next dev`. Works on Vercel-hosted frontend **only if the backend
  isn't serverless** (Vercel functions cap SSE at ~10s). Assumes
  Python backend on Fly / Render / Railway / similar, frontend on
  Vercel proxying via rewrites. Verify before deploying.
- **No global-spend cache.** `SELECT sum(cost_usd) ...` runs on every
  free-tier request. Fine until rows grow; if it becomes a hotspot,
  add a 30s in-process cache. Not a launch blocker.
- **`X-Anthropic-Key` in transit.** HTTPS-only in prod (obviously).
  Never logged — explicit filter in FastAPI logging config. Worth a
  one-line test that the header doesn't appear in captured logs.
- **No paste-time validation of BYOK key.** Bad key surfaces as 401 on
  first run with a clear "check your API key in Settings" error. By
  design — saves an Anthropic API call on every paste — but document
  in the Settings UI so users aren't surprised.

## Forward-compatibility notes

The schema and module boundaries are deliberately additive-friendly
for the features in CLAUDE.md and the v3 backlog:

- **Follow-up Q&A** → new `report_messages` table; reports stay
  untouched. The orchestrator gains a "chat mode" entry point that
  reuses the synthesizer.
- **Document upload as context** → new `report_attachments` table +
  Supabase Storage bucket. Researchers gain a "trusted source" input
  channel.
- **Projects / folders** → new `projects` table + `reports.project_id`
  nullable column.
- **"1 free report for signed-out users"** → drop the auth requirement
  on `POST /api/research` when `ANONYMOUS_FREE_REPORTS > 0`; track
  via IP-hash in a new tiny `anon_usage` table. ~30 LoC of additive
  code; no schema rework.
- **Multi-instance deploy** → swap `SupabaseReportStore` for a
  `RedisReportStore` (or Postgres LISTEN/NOTIFY variant). Protocol
  unchanged; agents and runtime unaffected.
