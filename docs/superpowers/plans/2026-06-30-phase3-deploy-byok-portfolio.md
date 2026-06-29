# Phase 3 — Deploy + BYOK-only + Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship ARA v1 live (frontend → Vercel, backend → Render free), enforce bring-your-own-key in production at zero owner spend, disclose cold-start latency, and draft a portfolio post.

**Architecture:** Three small code changes land on `dev` and merge to `main` (a `/health` endpoint, a `free_tier_available` flag on `/api/quota` + a `$PORT`-aware Dockerfile, and a BYOK/cold-start notice on the run form). Then a two-pass deploy wires the two free hosts together (backend URL → frontend env; frontend URL → backend CORS + Supabase redirect allow-list). Production omits `ANTHROPIC_API_KEY` so the only way to run a report is a user's own stored key.

**Tech Stack:** FastAPI + uvicorn (Docker), Next.js 16 (Vercel), Supabase (Postgres + Google OAuth), pytest (backend), vitest (frontend pure-lib tests).

## Global Constraints

- **Conventional Commits**, clear scope. **No `Co-Authored-By:` lines.** (project rule)
- Backend gates must pass on every commit: `cd backend && uv run pytest -q` and `uv run ruff check . && uv run mypy src`.
- Frontend gates: `cd frontend && npm run test && npm run lint`.
- **Production backend MUST NOT set `ANTHROPIC_API_KEY`** — this is the mechanism that forces BYOK and keeps owner spend at $0.
- **Production backend MUST reuse the same `ARA_ENCRYPTION_KEY` as local `.env`** — the live Supabase already holds Fernet-encrypted credentials; a different key fails to decrypt them.
- **Tavily:** set `TAVILY_API_KEY` (owner's free key) and `TAVILY_GLOBAL_MONTHLY_CAP=1000` in prod.
- Backend stays **single-instance** (in-memory SSE ring buffer) — no autoscaling / scale-to-zero across instances.
- Free subdomains only (`*.vercel.app`, `*.onrender.com`); deploy production from `main`.
- Exact BYOK copy string (used in two places): `This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report.`
- Exact cold-start copy string: `Free-hosted demo — if it's been idle, your first run may take ~30–60s to wake up.`

---

## Phase A — Code changes (on `dev`)

### Task 1: Backend `GET /health` endpoint

**Files:**
- Modify: `backend/src/ara/api/routes.py` (add a public route in the "Public endpoints" section, after `get_config`, ~line 230)
- Test: `backend/tests/test_api.py` (add one test alongside `test_get_config_returns_sanitized_settings`)

**Interfaces:**
- Produces: `GET /api/health` → `200 {"status": "ok"}`, public (no auth, no DB).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
async def test_health_is_public_and_ok() -> None:
    async with await _async_client() as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_api.py::test_health_is_public_and_ok -v`
Expected: FAIL with 404 (route not defined).

- [ ] **Step 3: Add the route**

In `backend/src/ara/api/routes.py`, immediately after the `get_config` function (before `get_gallery`), add:

```python
@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the host (Render). Public, no DB, no auth."""
    return {"status": "ok"}
```

Also update the module docstring's public-endpoints list (top of file) to add:
`- GET  /api/health             (public — liveness)`

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_api.py::test_health_is_public_and_ok -v`
Expected: PASS

- [ ] **Step 5: Run lint/type gates**

Run: `cd backend && uv run ruff check . && uv run mypy src`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add backend/src/ara/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): public GET /api/health liveness probe"
```

---

### Task 2: Expose `free_tier_available` on `/api/quota`

**Why:** The run form must know whether the server offers the free tier (it does not in prod, since `ANTHROPIC_API_KEY` is unset) so it can show an intentional BYOK notice instead of letting the user hit a raw 503.

**Files:**
- Modify: `backend/src/ara/api/routes.py` — `QuotaResponse` model (~line 132) and `get_quota` handler (~line 250)
- Test: `backend/tests/test_api.py`

**Interfaces:**
- Produces: `QuotaResponse.free_tier_available: bool` — `True` iff `settings.anthropic_api_key` is non-empty.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py` (note the existing import of `User`, `get_current_user`, `Settings`, `get_settings`, `create_app`, `httpx`, `uuid4` at the top of the file):

```python
async def test_quota_reports_free_tier_unavailable_when_no_anthropic_key() -> None:
    app = create_app()
    app.state.db_pool = object()
    user = User(id=uuid4(), email="t@example.com")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_settings] = lambda: Settings(
        anthropic_api_key="", supabase_db_url="postgres://x"
    )

    async def _status(*_a: object, **_k: object) -> object:
        class _S:
            used = 0
            limit = 3
            global_spend_usd = 0.0
            global_cap_usd = 20.0
        return _S()

    async def _tav(*_a: object, **_k: object) -> object:
        class _T:
            used = 0
            cap = 1000
            reached = False
        return _T()

    with patch("ara.api.routes.check_free_tier", _status), patch(
        "ara.api.routes.check_tavily_cap", _tav
    ):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quota")

    assert resp.status_code == 200
    assert resp.json()["free_tier_available"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_api.py::test_quota_reports_free_tier_unavailable_when_no_anthropic_key -v`
Expected: FAIL with `KeyError: 'free_tier_available'` (field absent).

- [ ] **Step 3: Add the field to the model**

In `backend/src/ara/api/routes.py`, extend `QuotaResponse` (add the new field at the end of the class):

```python
class QuotaResponse(BaseModel):
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float
    circuit_breaker_tripped: bool
    tavily_used: int
    tavily_cap: int
    tavily_cap_reached: bool
    free_tier_available: bool
```

- [ ] **Step 4: Populate it in the handler**

In the `get_quota` handler's `return QuotaResponse(...)`, add the new keyword argument (place after `tavily_cap_reached=tavily.reached,`):

```python
        free_tier_available=bool(settings.anthropic_api_key),
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_api.py::test_quota_reports_free_tier_unavailable_when_no_anthropic_key -v`
Expected: PASS

- [ ] **Step 6: Run full backend gates**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy src`
Expected: all pass (watch for any other test asserting the exact `QuotaResponse` field set — if one fails, add `free_tier_available` to its expected keys).

- [ ] **Step 7: Commit**

```bash
git add backend/src/ara/api/routes.py backend/tests/test_api.py
git commit -m "feat(api): surface free_tier_available on /api/quota"
```

---

### Task 3: Dockerfile honors `$PORT`

**Why:** Render injects `$PORT`; the current `CMD` hardcodes 8000 so the container never receives traffic.

**Files:**
- Modify: `backend/Dockerfile` (last line, `CMD`)

**Interfaces:**
- Produces: container listens on `$PORT` if set, else 8000.

- [ ] **Step 1: Change the CMD to shell form**

In `backend/Dockerfile`, replace the final line:

```dockerfile
CMD ["uv", "run", "uvicorn", "ara.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

with:

```dockerfile
CMD uv run uvicorn ara.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

(Shell form so `${PORT:-8000}` is expanded by the shell. `docker-compose.yml` overrides the command for dev, so local dev is unaffected.)

- [ ] **Step 2: Verify (if Docker is available locally)**

Run:
```bash
cd backend && docker build -t ara-backend . \
  && docker run --rm -d -e PORT=9000 -e SUPABASE_DB_URL= -p 9000:9000 --name ara-test ara-backend \
  && sleep 4 && curl -s localhost:9000/api/health && docker stop ara-test
```
Expected: prints `{"status":"ok"}`.

If Docker is **not** installed in this environment, skip the local run — this change is validated for real in Task 8 when Render's health check hits `/api/health`. Note in the commit that local Docker verification was skipped.

- [ ] **Step 3: Commit**

```bash
git add backend/Dockerfile
git commit -m "fix(docker): bind uvicorn to \$PORT for cloud hosts"
```

---

### Task 4: Frontend pure run-gate helpers

**Why:** Keep the run-blocking copy logic pure and unit-tested (matching the existing `lib/*.test.ts` pattern), separate from the form's JSX.

**Files:**
- Create: `frontend/lib/run-status.ts`
- Test: `frontend/lib/run-status.test.ts`

**Interfaces:**
- Produces:
  - `interface QuotaInfo { used: number; limit: number; circuit_breaker_tripped: boolean; free_tier_available: boolean }`
  - `freeTierBlockMessage(quota: QuotaInfo | null): string | null`
  - `friendlyRunError(status: number | undefined, fallback: string): string`

- [ ] **Step 1: Write the failing test**

Create `frontend/lib/run-status.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { freeTierBlockMessage, friendlyRunError, type QuotaInfo } from "./run-status";

const base: QuotaInfo = {
  used: 0,
  limit: 3,
  circuit_breaker_tripped: false,
  free_tier_available: true,
};

const BYOK =
  "This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report.";

describe("freeTierBlockMessage", () => {
  it("returns null when quota is unknown", () => {
    expect(freeTierBlockMessage(null)).toBeNull();
  });

  it("returns null when free tier is available and quota remains", () => {
    expect(freeTierBlockMessage(base)).toBeNull();
  });

  it("asks for a key when the server has no free tier", () => {
    expect(freeTierBlockMessage({ ...base, free_tier_available: false })).toBe(BYOK);
  });

  it("explains the site-wide cap", () => {
    expect(freeTierBlockMessage({ ...base, circuit_breaker_tripped: true })).toContain(
      "capped site-wide",
    );
  });

  it("explains personal exhaustion", () => {
    expect(freeTierBlockMessage({ ...base, used: 3, limit: 3 })).toContain("exhausted");
  });
});

describe("friendlyRunError", () => {
  it("maps 503 to the BYOK message", () => {
    expect(friendlyRunError(503, "API 503")).toBe(BYOK);
  });

  it("maps 402 to a quota message", () => {
    expect(friendlyRunError(402, "API 402")).toContain("limit reached");
  });

  it("passes other errors through", () => {
    expect(friendlyRunError(500, "boom")).toBe("boom");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run lib/run-status.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module**

Create `frontend/lib/run-status.ts`:

```ts
// Pure run-gate copy. Kept out of the form component so it can be unit-tested
// like the other lib/* helpers. The BYOK string is the canonical one shared
// with the cold-start notice in research-form.tsx.

export interface QuotaInfo {
  used: number;
  limit: number;
  circuit_breaker_tripped: boolean;
  free_tier_available: boolean;
}

export const BYOK_MESSAGE =
  "This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report.";

// Why: in production the server has no ANTHROPIC_API_KEY, so the free tier is
// off and every "free"-provider user must bring their own key. We still cover
// the owner-key (local/dev) exhaustion and site-wide-cap states.
export function freeTierBlockMessage(quota: QuotaInfo | null): string | null {
  if (quota === null) return null;
  if (!quota.free_tier_available) return BYOK_MESSAGE;
  if (quota.circuit_breaker_tripped) {
    return "Free tier is capped site-wide for this month — add your Anthropic API key in Settings to keep running reports.";
  }
  if (quota.used >= quota.limit) {
    return "Free tier exhausted — add your Anthropic API key in Settings to keep running reports.";
  }
  return null;
}

export function friendlyRunError(status: number | undefined, fallback: string): string {
  if (status === 503) return BYOK_MESSAGE;
  if (status === 402) {
    return "Free-tier limit reached — add your own API key in Settings to keep running reports.";
  }
  return fallback;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run lib/run-status.test.ts`
Expected: PASS (all cases).

- [ ] **Step 5: Commit**

```bash
git add frontend/lib/run-status.ts frontend/lib/run-status.test.ts
git commit -m "feat(run-form): pure run-gate + friendly-error helpers"
```

---

### Task 5: Wire helpers + cold-start notice into the run form

**Files:**
- Modify: `frontend/components/research-form.tsx`

**Interfaces:**
- Consumes: `freeTierBlockMessage`, `friendlyRunError` from `@/lib/run-status`; `ApiError` from `@/lib/api`.

- [ ] **Step 1: Add imports**

In `frontend/components/research-form.tsx`, update the import from `@/lib/api` and add the new helper import. Replace:

```ts
import { apiGet, createResearch } from "@/lib/api";
```

with:

```ts
import { apiGet, createResearch, type ApiError } from "@/lib/api";
import { freeTierBlockMessage, friendlyRunError } from "@/lib/run-status";
```

- [ ] **Step 2: Extend the `Quota` interface**

Replace the local `Quota` interface (top of file) with:

```ts
interface Quota {
  used: number;
  limit: number;
  circuit_breaker_tripped: boolean;
  free_tier_available: boolean;
}
```

- [ ] **Step 3: Replace the `freeBlocked` computation with a message-driven gate**

Replace:

```ts
  const freeTier = activeProvider === "free";
  const freeBlocked =
    freeTier &&
    quota !== null &&
    (quota.used >= quota.limit || quota.circuit_breaker_tripped);
```

with:

```ts
  const freeTier = activeProvider === "free";
  const blockMsg = freeTier ? freeTierBlockMessage(quota) : null;
  const freeBlocked = blockMsg !== null;
```

- [ ] **Step 4: Map the submit error through `friendlyRunError`**

In `submit`, replace the catch body:

```ts
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      setSubmitting(false);
    }
```

with:

```ts
    } catch (err) {
      const status = (err as ApiError).status;
      const fallback = err instanceof Error ? err.message : "Unknown error";
      setError(friendlyRunError(status, fallback));
      setSubmitting(false);
    }
```

- [ ] **Step 5: Render `blockMsg` instead of the hardcoded exhausted notice**

Replace the block:

```tsx
      {freeBlocked ? (
        <p className="border-destructive/40 bg-destructive/10 text-destructive mb-3 rounded-md border px-4 py-2 font-mono text-xs">
          Free tier exhausted — add your Anthropic API key in Settings to keep
          running reports
        </p>
      ) : null}
```

with:

```tsx
      {blockMsg ? (
        <p className="border-destructive/40 bg-destructive/10 text-destructive mb-3 rounded-md border px-4 py-2 font-mono text-xs">
          {blockMsg}
        </p>
      ) : null}
```

- [ ] **Step 6: Add the cold-start transparency line**

Replace the closing of the form — the existing quota line block:

```tsx
      {freeTier && quota !== null ? (
        <p className="text-muted-foreground/70 mt-3 px-2 font-mono text-[10px] tracking-wider">
          {quota.used} of {quota.limit} free reports used this month
        </p>
      ) : null}
    </form>
```

with (adds the always-visible cold-start note; keeps the free-usage line only when the free tier is actually available):

```tsx
      {freeTier && quota !== null && quota.free_tier_available ? (
        <p className="text-muted-foreground/70 mt-3 px-2 font-mono text-[10px] tracking-wider">
          {quota.used} of {quota.limit} free reports used this month
        </p>
      ) : null}
      <p className="text-muted-foreground/50 mt-3 px-2 font-mono text-[10px] tracking-wider">
        Free-hosted demo — if it&apos;s been idle, your first run may take ~30–60s to wake up.
      </p>
    </form>
```

- [ ] **Step 7: Run frontend gates**

Run: `cd frontend && npm run test && npm run lint`
Expected: vitest passes (Task 4 tests), eslint clean.

- [ ] **Step 8: Typecheck via build (catches TS errors the linter misses)**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/components/research-form.tsx
git commit -m "feat(run-form): BYOK gate + cold-start transparency notice"
```

---

## Phase B — Merge & deploy

### Task 6: Merge `dev` → `main`

- [ ] **Step 1: Confirm gates are green on `dev`**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy src`
Then: `cd frontend && npm run test && npm run lint && npx tsc --noEmit`
Expected: all green.

- [ ] **Step 2: Push `dev`**

```bash
git push origin dev
```

- [ ] **Step 3: Merge to `main` and push**

```bash
git checkout main
git merge --no-ff dev -m "merge: phase 3 code changes (health, byok gate, \$PORT)"
git push origin main
git checkout dev
```
Expected: `origin/main` now contains the Phase A commits. (Render/Vercel will deploy from `main`.)

---

### Task 7: Deploy backend to Render (dashboard — guided)

> Procedural/manual task (like the OAuth setup). The implementer guides the user through the Render dashboard; the user clicks. Verification is a `curl`.

- [ ] **Step 1: Create the service**

At https://dashboard.render.com → **New** → **Web Service** → connect the GitHub repo `ShriramJana/autonomous-research-assistant` → branch **`main`**.
- **Root Directory:** `backend`
- **Runtime:** Docker (auto-detected from `backend/Dockerfile`)
- **Instance type:** Free
- **Health Check Path:** `/api/health`

- [ ] **Step 2: Set environment variables (Render → Environment)**

Set these (values from the local repo-root `.env`):
- `SUPABASE_URL`
- `SUPABASE_DB_URL`
- `ARA_ENCRYPTION_KEY` — **must be byte-for-byte identical to local `.env`**
- `TAVILY_API_KEY`
- `TAVILY_GLOBAL_MONTHLY_CAP` = `1000`
- `ADMIN_USER_ID` (optional)

**Do NOT set `ANTHROPIC_API_KEY`.** Leave `ARA_CORS_ORIGINS` unset for now (set in Task 9).

- [ ] **Step 3: Deploy and capture the URL**

Trigger the first deploy. When live, copy the service URL (e.g. `https://ara-backend-xxxx.onrender.com`). Record it as `RENDER_URL`.

- [ ] **Step 4: Verify health**

Run: `curl -s <RENDER_URL>/api/health`
Expected: `{"status":"ok"}` (first hit after build may take ~30–60s if it cold-starts).

- [ ] **Step 5: Verify BYOK enforcement at the API level**

Run: `curl -s -o /dev/null -w "%{http_code}\n" <RENDER_URL>/api/config`
Expected: `200` (public). The free-tier disablement is confirmed end-to-end in Task 10; here we only confirm the service is up and `ANTHROPIC_API_KEY` is absent (Render env shows no such var).

---

### Task 8: Deploy frontend to Vercel (dashboard — guided)

- [ ] **Step 1: Import the project**

At https://vercel.com/new → import `ShriramJana/autonomous-research-assistant` → **Root Directory:** `frontend` → framework auto-detected (Next.js) → production branch **`main`**.

- [ ] **Step 2: Set environment variables (Vercel → Settings → Environment Variables, Production)**

- `BACKEND_ORIGIN` = `<RENDER_URL>` (from Task 7)
- `NEXT_PUBLIC_SUPABASE_URL` (from local `.env.local`)
- `NEXT_PUBLIC_SUPABASE_ANON_KEY` (from local `.env.local`)
- `NEXT_PUBLIC_ADMIN_USER_ID` (from local `.env.local`, if set)

- [ ] **Step 3: Deploy and capture the URL**

Deploy. Copy the production URL (e.g. `https://ara-xxxx.vercel.app`). Record it as `VERCEL_URL`.

- [ ] **Step 4: Verify the static path works (no backend needed)**

Run: `curl -s -o /dev/null -w "%{http_code}\n" <VERCEL_URL>`
Expected: `200`. Open `<VERCEL_URL>/gallery` in a browser → demo cards render and a demo replays (proves the static client-side path).

---

### Task 9: Pass-2 wiring (CORS + Supabase redirect + migrations)

- [ ] **Step 1: Set backend CORS to the Vercel origin**

Render → Environment → set `ARA_CORS_ORIGINS` = `<VERCEL_URL>` (exact origin, no trailing slash) → save (triggers a redeploy).

- [ ] **Step 2: Add the prod URL to Supabase Auth**

Supabase dashboard → Authentication → **URL Configuration**:
- **Site URL** = `<VERCEL_URL>`
- **Redirect URLs** → add `<VERCEL_URL>/**`

(Google OAuth needs **no** change — its redirect URI points at the Supabase callback, which is unchanged.)

- [ ] **Step 3: Verify migrations on the live Supabase**

In the Supabase SQL editor, run:
```sql
select table_name from information_schema.tables
where table_schema = 'public' and table_name in ('reports', 'user_credentials');
```
Expected: both `reports` and `user_credentials` rows returned (migrations 001 + 002 applied). If `user_credentials` is missing, apply `backend/migrations/002_credentials.sql`.

---

### Task 10: End-to-end verification (acceptance gate)

- [ ] **Step 1: Demos (anonymous)**

Open `<VERCEL_URL>/gallery` in a fresh/incognito browser → a demo card replays fully. No sign-in, backend may be asleep. Expected: works.

- [ ] **Step 2: Auth**

Click sign in → **Continue with Google** → approve. Expected: redirected back to `<VERCEL_URL>`, signed in.

- [ ] **Step 3: BYOK gate (owner key never used)**

Signed in with **no** saved key (default "free" provider): the run form shows the BYOK notice (`This live demo runs on your own API key …`) and **EXECUTE is disabled**. Expected: confirms the owner key is structurally unused.

- [ ] **Step 4: Live run on a user key**

Settings → save a personal Anthropic key → set it active → return to the form (notice clears, EXECUTE enabled) → run a question. Expected: SSE streams tokens; report completes; reload shows it persisted. First run after idle shows the cold-start delay (the notice already warned).

- [ ] **Step 5: Record results**

Note `RENDER_URL` and `VERCEL_URL` for the portfolio post (Task 11). If any step fails, debug before declaring Phase 3 done.

---

## Phase C — Portfolio post

### Task 11: Draft the portfolio post

**Files:**
- Create: `docs/portfolio/ara-v1-post.md`

- [ ] **Step 1: Write the post**

Create `docs/portfolio/ara-v1-post.md` covering, in this order: the problem (research is slow, manual, uncited); the solution and a one-line live-demo CTA; the architecture (Planner → parallel Researchers → Synthesizer, with the LangGraph 3-node chain and the fan-out inside `research_node`); live SSE streaming and the event contract; the BYOK + cost design (free static demos for everyone, live runs on the visitor's own key, $0 owner spend); the stack (FastAPI/LangGraph/Pydantic v2/Next.js 16/shadcn/Supabase); and 3–5 "what I learned" bullets (e.g. citations-by-UUID, partial-researcher-failure handling, in-memory ring buffer constraint). Include placeholders to fill: `LIVE_URL` = `<VERCEL_URL>`, `GITHUB_URL` = `https://github.com/ShriramJana/autonomous-research-assistant`.

- [ ] **Step 2: Commit**

```bash
git add docs/portfolio/ara-v1-post.md
git commit -m "docs(portfolio): draft ARA v1 build-story post"
```

---

## Self-Review

**Spec coverage:**
- Topology (Vercel + Render + Supabase) → Tasks 7, 8, 9. ✓
- `$PORT` Dockerfile → Task 3. ✓
- `/health` → Task 1. ✓
- BYOK-enforcing prod (no `ANTHROPIC_API_KEY`) → Task 7 Step 2 + Global Constraints. ✓
- Friendlier BYOK gate + cold-start notice → Tasks 2, 4, 5. ✓
- Tavily set + cap → Task 7 Step 2. ✓
- Env matrix → Tasks 7, 8. ✓
- Deploy order / chicken-and-egg → Tasks 6–9 (two-pass). ✓
- Supabase redirect allow-list + migrations verify → Task 9. ✓
- Verification gate → Task 10. ✓
- Portfolio post → Task 11. ✓
- Deploy from `main` → Task 6. ✓

**Placeholder scan:** `RENDER_URL`/`VERCEL_URL`/`LIVE_URL` are deliberate runtime values captured during deploy, not unfilled spec gaps. No "TBD/TODO" in code steps; every code step shows complete code.

**Type consistency:** `QuotaInfo`/`QuotaResponse` field set (`used`, `limit`, `circuit_breaker_tripped`, `free_tier_available`) is consistent across Tasks 2, 4, 5. `freeTierBlockMessage` / `friendlyRunError` signatures match between definition (Task 4) and use (Task 5). `/api/health` returns `{"status":"ok"}` consistently in Task 1 and Tasks 8–10.
