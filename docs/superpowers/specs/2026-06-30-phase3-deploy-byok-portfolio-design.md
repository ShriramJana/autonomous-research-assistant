# Phase 3 — Deploy ARA v1 live + portfolio post (design)

**Date:** 2026-06-30
**Status:** Approved — ready for writing-plans
**Parent spec:** [2026-06-28-ship-ara-v1-demo-byok-deploy-design.md](2026-06-28-ship-ara-v1-demo-byok-deploy-design.md)

## Goal

Take ARA v1 (Phases 1, 1.5, 2a, 2b complete on `dev`) live on the public internet at **zero recurring owner cost and zero owner API spend**, and draft a portfolio post. The live site must let visitors watch recorded demos instantly and let signed-in users run real reports **on their own API keys only**.

## Decisions (locked during brainstorming)

| Decision | Choice | Rationale |
| --- | --- | --- |
| Frontend host | **Vercel** (free), Git-integration auto-deploy | Native Next.js host |
| Backend host | **Render** free Web Service (Docker), single instance | $0; demos are static so cold start only affects live runs |
| Warmth | **Sleeps when idle** (no keep-warm), upgrade to always-on later if desired | Honor cost; disclose cold start to users |
| Domains | **Free subdomains** (`*.vercel.app`, `*.onrender.com`) | No DNS/cost; custom domain is a no-rework add later |
| Owner API key | **`ANTHROPIC_API_KEY` deliberately UNSET in prod** | Structurally forces BYOK; owner spend = $0 |
| Tavily | **Owner's free Tavily key set**, capped at `TAVILY_GLOBAL_MONTHLY_CAP=1000` | OpenAI-BYOK users get web search inside Tavily's free tier |
| Deploy branch | **Merge `dev` → `main`; deploy prod from `main`** | Prod tracks a stable branch |
| Portfolio post | **Draft markdown in repo; user places it** | Keep phase focused on shipping |

## Architecture / topology

- **Frontend (Vercel):** Next.js 16 App Router. All `/api/*` calls — including the SSE stream — are proxied to the backend via the existing `next.config.ts` rewrite (`BACKEND_ORIGIN`), so the browser only ever talks to the Vercel origin (same-origin, cookie auth preserved). Demos are 100% static (`frontend/public/demos/*.json`), bundled/fetched client-side — they render with no backend and no auth.
- **Backend (Render):** Dockerized FastAPI (`backend/Dockerfile`), `ara.main:app` on uvicorn, single always-on-capable instance that sleeps on Render free. **Must remain single-instance** — the SSE reconnect ring buffer is in-memory per process, so multi-instance/scale-to-zero would break live runs. Completed reports persist to Supabase, so a restart only loses in-flight runs (acceptable).
- **Persistence/Auth (Supabase):** existing project (already the prod project; Google OAuth live). Migrations 001 + 002 already applied; verify only.

## Why "no owner key" works without code changes

The free-tier gate already short-circuits when the server has no Anthropic key
([`backend/src/ara/api/routes.py`](../../../backend/src/ara/api/routes.py) ~L502–508):

```python
if overrides is None:            # user is on the "free" provider
    if not settings.anthropic_api_key:
        raise HTTPException(503, "Free tier disabled (server has no ANTHROPIC_API_KEY)")
```

With `ANTHROPIC_API_KEY` unset, the only path to a successful run is a user's
**saved credential** resolved by [`resolver.py`](../../../backend/src/ara/runtime/resolver.py),
which uses the user's own key. The owner's key cannot be used because it is not present.

## Code changes (small, land on `dev` before deploy)

1. **Dockerfile respects `$PORT`.** Render injects `PORT`; current `CMD` hardcodes 8000. Use shell form so the container honors the injected port, defaulting to 8000 locally:
   `CMD uv run uvicorn ara.main:app --host 0.0.0.0 --port ${PORT:-8000}`
   (Note: shell-form CMD; verify `docker-compose.yml` still works since it overrides the command anyway.)
2. **Add `GET /health`** (public, no auth) → `{"status": "ok"}` for Render's health check. Place alongside existing public routes; assert in a test.
3. **Public-deployment notice + friendlier BYOK gate (frontend).** When a run is attempted with no usable key (server returns the free-tier-disabled signal), the UI shows an intentional message instead of a raw error:
   - BYOK line: *"This live demo runs on your own API key — add an Anthropic or OpenAI key in Settings to run a report."*
   - Cold-start line: *"Heads-up: this is a free-hosted demo. If it's been idle, your first run may take ~30–60s to spin up."*
   The notice should be visible on the run path (run form and/or the error surface). Demos are unaffected (no backend).

## Environment variables (production)

**Backend (Render) — set:**
- `SUPABASE_URL`, `SUPABASE_DB_URL`
- `ARA_ENCRYPTION_KEY` — **must be the same Fernet key used locally**, or existing saved credentials in the shared Supabase DB will fail to decrypt
- `TAVILY_API_KEY` (owner's free key), `TAVILY_GLOBAL_MONTHLY_CAP=1000`
- `ARA_CORS_ORIGINS=<vercel url>` (set in pass 2, after the Vercel URL exists)
- `ADMIN_USER_ID` (optional — gallery promotion)
- Model envs optional (config defaults apply; these govern Anthropic-BYOK runs)

**Backend — deliberately NOT set:** `ANTHROPIC_API_KEY` (forces BYOK; owner spend $0).

**Frontend (Vercel) — set:**
- `BACKEND_ORIGIN=<render url>`
- `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`
- `NEXT_PUBLIC_ADMIN_USER_ID`

## Deploy order (resolves the URL chicken-and-egg)

1. Land code changes on `dev`; run gates (`make test`, `make lint`); merge `dev` → `main`.
2. Deploy **backend** to Render from `main` (root dir `backend/`, Docker). Set backend env vars except final CORS. Capture the `*.onrender.com` URL.
3. Deploy **frontend** to Vercel from `main` with `BACKEND_ORIGIN` = Render URL + Supabase vars. Capture the `*.vercel.app` URL.
4. Set backend `ARA_CORS_ORIGINS` = Vercel URL; restart/redeploy backend.
5. Supabase → add the Vercel URL to **Site URL** + **Redirect URLs** (`https://<vercel>/**`). Google OAuth unchanged.
6. Verify migrations 001 + 002 are applied to the live Supabase.

## Verification (acceptance — the gate for "done")

- **Demos:** gallery loads and one demo replays with the backend asleep (no backend, no auth).
- **Auth:** Google sign-in works on the prod URL (redirect round-trips).
- **BYOK enforced:** signed in with **no** saved key → run attempt yields the friendly "add your key" message (proves the owner key is never used). Save an Anthropic key in Settings → run a live report → SSE streams tokens → `report_complete` and the report persists/reloads. Cold-start notice is visible on first run after idle.
- **Cost posture:** confirm `ANTHROPIC_API_KEY` is absent in Render env (free path returns the disabled signal).

## Portfolio post

Draft `docs/portfolio/ara-v1-post.md`: problem framing → 3-stage Planner → Researchers (parallel) → Synthesizer architecture → live SSE streaming → BYOK/cost design → stack (FastAPI/LangGraph/Next.js/Supabase) → lessons learned. Include links to the live URL and the GitHub repo. User places it on their platform.

## Out of scope / deferred (non-blocking)

- Custom domain (free subdomains for now; no-rework add later).
- Keep-warm pinger (rejected — burns Render free hours and contradicts the transparency banner).
- `middleware.ts → proxy.ts` Next 16 deprecation rename (still works on Vercel).
- Upgrading the backend to always-on (the "upgrade later" path).
- Multi-instance/scale-out (incompatible with the in-memory SSE ring buffer until the store is externalized — a v2 concern).
