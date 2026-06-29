# Phase 2b — Persisted BYOK + Tavily Cap Design

> Design spec. Status: design approved by Shriram (2026-06-29); pending written-spec review.
> Second half of Phase 2 (multi-provider BYOK). Builds directly on Phase 2a's engine.
> Author: Claude Code session, 2026-06-29.

## Goal

Move provider credentials out of per-request transport (header + browser localStorage) into
**encrypted per-user storage in Supabase**, managed from the Settings UI. A user configures an
Anthropic key and/or an OpenAI-compatible config and marks **one active provider**; every run
uses that active saved credential — no keys are typed at run time. Add a **global monthly Tavily
search cap** that **degrades** OpenAI-compatible runs to offline (web search forced off) once the
site-wide budget is exhausted, protecting the single server-provided Tavily key.

Phase 2a's engine is reused unchanged — `build_client` factory, `AnthropicClient` /
`OpenAICompatClient`, the researcher's client-side Tavily loop, and `RuntimeOverrides`
(provider/base_url). **Only the *source* of the provider config changes: request → encrypted
storage.**

## Decisions captured during brainstorming (2026-06-29)

- **Scope:** one Phase 2b spec covering BOTH encrypted key storage + settings UI + wiring AND
  the global monthly Tavily cap.
- **Credentials stored:** BOTH a saved Anthropic key AND a saved OpenAI-compat config
  (`base_url` + `model` + key), unified, encrypted server-side. Browser-localStorage for the
  Anthropic key is **retired**.
- **Runtime model:** **saved-only**, resolved server-side. A **single active provider** per user
  (`free` | `anthropic` | `openai`), chosen via a radio in Settings. The run form has **no**
  provider/key fields — every run uses the active saved credential.
- **Encryption:** **app-level Fernet** in the FastAPI backend; ciphertext stored in a Supabase
  column; secret in a server env var `ARA_ENCRYPTION_KEY`. (`cryptography` is already a
  transitive dependency — no new package.)
- **Tavily cap:** **global only** (one site-wide monthly search budget, mirroring the existing
  global USD cap). When reached, OpenAI-compat runs that requested web search **degrade to
  offline** (model-knowledge only) with a UI notice — they are not blocked. Anthropic runs are
  unaffected (they use the user's own Anthropic search, billed to the user's key).

## Non-goals (deferred / out of scope)

- Automated key rotation (re-encrypt-on-rotate). `ARA_ENCRYPTION_KEY` rotation is a manual ops
  task in 2b.
- Multiple saved configs per provider (one Anthropic slot + one OpenAI slot per user).
- A **per-user** Tavily cap (global only in 2b).
- User-supplied Tavily keys (server provides Tavily, as in 2a).
- Sharing/teams for credentials.
- The per-request `X-Anthropic-Key` / `X-Provider-Key` header path and the run-form provider
  fields from 2a Task 9 — **these are retired** in favor of saved-only resolution.

---

## Architecture

### A. Data model — migration `backend/migrations/002_credentials.sql`

Idempotent, same conventions as `001_initial.sql` (IF NOT EXISTS; DROP POLICY IF EXISTS;
applied manually via Supabase SQL editor / psql). Backend uses the service-role key and bypasses
RLS — policies are defense-in-depth.

```sql
create table if not exists user_credentials (
  user_id                   uuid primary key references auth.users(id) on delete cascade,
  active_provider           text not null default 'free'
                              check (active_provider in ('free','anthropic','openai')),
  anthropic_key_ciphertext  text,            -- Fernet token, nullable
  openai_key_ciphertext     text,            -- Fernet token, nullable
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

- **One row per user** (PK `user_id`). Given single-active + at most two credential types,
  this is simpler than a row-per-provider table.
- Secrets stored ONLY as Fernet ciphertext. `openai_base_url` / `openai_model` are non-secret →
  plaintext.
- `reports.tavily_searches` is the per-run Tavily call count, written at `close`; the cap sums it
  monthly (no separate usage table — same "derive from `reports`" approach as `quota.py`).

### B. Encryption — `backend/src/ara/crypto.py`

```python
def encrypt_secret(plaintext: str, *, key: str) -> str: ...   # -> Fernet token (str)
def decrypt_secret(token: str, *, key: str) -> str: ...        # raises on tamper/bad key
```

- Uses `cryptography.fernet.Fernet`. `key` is the urlsafe-base64 32-byte Fernet key from
  `Settings.ara_encryption_key`.
- A helper resolves the key from settings and raises a clear error if unset, so the API layer can
  return 503 ("credential storage not configured") exactly like the free-tier-disabled path.

### C. Credential store — `backend/src/ara/credentials.py`

asyncpg-backed module (style of `quota.py` — functions taking `pool`), returning a small frozen
`CredentialRecord` dataclass (`active_provider`, `anthropic_key_ciphertext`,
`openai_key_ciphertext`, `openai_base_url`, `openai_model`). **The store returns ciphertext +
metadata; decryption happens in the resolution layer**, never inside the store.

```python
async def get_credentials(user_id, pool) -> CredentialRecord | None: ...
async def upsert_anthropic(user_id, pool, *, ciphertext) -> None: ...
async def upsert_openai(user_id, pool, *, ciphertext, base_url, model) -> None: ...
async def clear_anthropic(user_id, pool) -> None: ...   # null the ciphertext
async def clear_openai(user_id, pool) -> None: ...      # null ciphertext+base_url+model
async def set_active(user_id, pool, *, provider) -> None: ...
async def check_tavily_cap(pool, settings) -> TavilyCapStatus: ...  # global monthly sum
```

Upserts create the row on first write (`insert ... on conflict (user_id) do update`).
`set_active` validates that the chosen provider is actually configured (or `free`), else raises a
domain error the API maps to 400.

### D. Run-start credential resolution

A resolver (in `api/routes.py` or a small `runtime` helper) replaces 2a's header/body reading in
`create_research`:

1. Load `get_credentials(user.id)`. If `None` or `active_provider == 'free'` → existing free-tier
   path (quota check, Haiku-everywhere, no browsing) **unchanged**.
2. `active_provider == 'anthropic'` and a key is configured → decrypt; build the BYOK
   `RuntimeOverrides` 2a/earlier already use (per-role models from settings, depth/browse from the
   request). `used_byok=True`.
3. `active_provider == 'openai'` and config complete → decrypt; build the OpenAI
   `RuntimeOverrides` (single `openai_model` for all three roles, `provider='openai'`,
   `base_url=openai_base_url`). `used_byok=True`. Apply the Tavily-cap degrade (section E).
4. Active provider selected but its credential is missing/incomplete (shouldn't happen — `set_active`
   guards it, but defensive) → 400 with a clear "configure this provider in Settings" message.

`CreateResearchRequest` reverts to `{question, depth, browse_web}` only — the 2a body fields
(`provider`, `base_url`, `model`) and the `X-Anthropic-Key` / `X-Provider-Key` headers are removed.

### E. Tavily cap — accounting + enforcement

- **Count:** `run_report` keeps a `tavily_searches` counter and defines
  `async def on_tavily_search() -> None` (increments it), threaded
  `build_graph → research_node → research_sub_query → _research_with_tavily`, invoked once per
  `tavily_search(...)` call. At completion, `store.close(..., tavily_searches=n)` writes the
  column. `ReportStore.close` and both store impls gain the `tavily_searches: int = 0` param.
- **Enforce:** in `create_research`, when the resolved provider is `openai` and `browse_web` is
  true, call `check_tavily_cap(pool, settings)`. If the global monthly sum
  `>= settings.tavily_global_monthly_cap`, force `web_search_enabled=False` for this run (degrade
  to offline). The run proceeds and the existing "web search disabled" chip communicates the
  offline state.
- **Surface:** extend `GET /api/quota` (`QuotaResponse`) with `tavily_used: int`,
  `tavily_cap: int`, `tavily_cap_reached: bool` so the Settings UI can show it like the free-tier
  circuit breaker.

### F. API endpoints (`api/routes.py`) — all authed, keys never returned

- `GET /api/credentials` →
  `{active_provider, anthropic_configured: bool, openai: {configured: bool, base_url, model}}`.
  (Key plaintext is never serialized.)
- `PUT /api/credentials/anthropic` `{key}` → encrypt + `upsert_anthropic`.
- `DELETE /api/credentials/anthropic` → `clear_anthropic` (and if it was active, reset active to
  `free`).
- `PUT /api/credentials/openai` `{base_url, model, key}` → encrypt + `upsert_openai`.
- `DELETE /api/credentials/openai` → `clear_openai` (reset active to `free` if it was active).
- `PUT /api/credentials/active` `{provider}` → `set_active` (400 if not configured).
- All return 503 when `ARA_ENCRYPTION_KEY` is unset.

### G. Config (`Settings`) new fields

- `ara_encryption_key: str = Field(default="")` — Fernet key (root `.env`). Empty → credential
  endpoints 503.
- `tavily_global_monthly_cap: int = 1000` — site-wide monthly Tavily search budget (the Tavily
  free dev tier is ~1000 searches/month; tune via `.env`).

### H. Frontend

- **Settings page (`app/settings/page.tsx`) reworked** to server-backed credentials via the new
  endpoints:
  - Anthropic-key slot: write-only input, Save / Clear, shows "configured" state.
  - OpenAI-compat slot: `base_url` + `model` + write-only key, Save / Clear, shows configured
    state (base_url/model echoed, key never).
  - **Active-provider radio**: Free tier / Anthropic / OpenAI-compat — each selectable only when
    configured; calls `PUT /api/credentials/active`.
  - Tavily-cap notice when `tavily_cap_reached` (from `/api/quota`).
- **Run form (`components/research-form.tsx`)**: remove 2a Task 9's provider toggle + key /
  base_url / model fields → back to question + depth + browse-web. Free-tier depth/browse locks
  now key off the active provider being `free` (fetched from `/api/credentials`).
- Retire `lib/api-key.ts` (localStorage) and the `X-Anthropic-Key` header in `authedFetch`
  (`lib/api.ts`); `createResearch` reverts to `{question, depth, browse_web}`.

## Data flow

```
Settings UI ─(PUT key)→ /api/credentials/* → encrypt(Fernet) → user_credentials (ciphertext)
                         PUT active → active_provider

run form ─({question, depth, browse_web})→ create_research
  → get_credentials(user) → branch on active_provider:
       free     → free-tier path (quota, Haiku, no search)            [unchanged]
       anthropic→ decrypt key → RuntimeOverrides (per-role)           [2a engine]
       openai   → decrypt key → RuntimeOverrides(openai, base_url)    [2a engine]
                  + if browse_web and global Tavily cap reached → force search off (degrade)
  → orchestrator → planner/researchers/synthesizer
       (researcher Tavily loop calls on_tavily_search() per search)
  → store.close(..., tavily_searches=n)
  → SSE (unchanged) → UI + cost meter
```

## Error handling

- `ARA_ENCRYPTION_KEY` unset → credential endpoints 503; runs fall back to free-tier (no active
  credential resolvable).
- Decrypt failure (tampered ciphertext / rotated key) → `create_research` returns a clear 4xx
  ("saved credential could not be read — please re-save it in Settings") rather than silently
  falling back to free-tier, so the user knows to re-enter the key. The run is not started.
- `set_active` to an unconfigured provider → 400.
- Tavily cap reached → degrade (not an error); never blocks the run.
- Free-tier and Anthropic-BYOK behavior otherwise unchanged.

## Testing

- `crypto`: encrypt→decrypt round-trip; decrypt of tampered token raises; missing key → clear error.
- `credentials` store: upsert/clear/get for both providers; `set_active` validation;
  `check_tavily_cap` global monthly sum (priced like the USD cap test).
- Resolution: each `active_provider` → correct `RuntimeOverrides` (or free-tier); decrypt wired;
  missing-credential defensive 400.
- `create_research`: uses stored creds (NOT headers/body); free-tier path intact; OpenAI + cap
  reached → `web_search_enabled` forced false.
- Tavily counter: `_research_with_tavily` invokes `on_tavily_search` once per search; persisted via
  `store.close(tavily_searches=...)` in both store impls.
- Endpoints: authed; never return key plaintext; 503 without `ARA_ENCRYPTION_KEY`.
- Migration `002` idempotent (re-runnable).
- SSE contract tests stay green (no event/order changes).
- Frontend: settings save/clear/active flows; run form no longer sends keys; existing vitest pass.

## Risks

- **Encryption key management:** losing `ARA_ENCRYPTION_KEY` makes stored ciphertext
  unrecoverable; rotating it invalidates existing rows (manual re-entry). Acceptable for v2b;
  documented as an ops note.
- **Tavily count fidelity:** the counter must increment exactly once per real Tavily call;
  covered by the loop test. Degraded/failed searches still count as attempts (they hit Tavily).
- **Behavior change:** retiring the per-request header path is a deliberate simplification; the 2a
  engine is fully reused, so the surface area of change is the request *source*, not the engine.

## Execution

Implementation plan via `superpowers:writing-plans` → `subagent-driven-development` (TDD, commit
per stage), same as Phases 1 / 1.5 / 2a. New ops note for Phase 3 deploy: set `ARA_ENCRYPTION_KEY`
and `TAVILY_GLOBAL_MONTHLY_CAP` as backend env vars.
