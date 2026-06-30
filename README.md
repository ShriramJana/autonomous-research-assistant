# ARA — Autonomous Research Assistant

**A three-stage AI agent pipeline that turns a research question into a cited, multi-source report — streamed live to the browser.** Planner → parallel Researchers → Synthesizer, with every claim traceable to its source.

**🔗 Live demo: https://autonomous-research-assistant-tawny.vercel.app** — no account needed to watch the demo gallery; bring your own Anthropic or OpenAI key to run a live report.

Built as the flagship portfolio project for LLMTechno.

<!-- TODO: add a hero screenshot or short demo GIF here, e.g.:
![ARA running a live research report](docs/assets/ara-demo.png)
-->

## What it does

- **Plans** — decomposes your question into 3–7 focused sub-queries with rationale and priority.
- **Researches** — runs one agent per sub-query in parallel; each searches the live web and returns structured findings with sources.
- **Synthesizes** — merges all findings into one report with an executive summary, sections, and a deduplicated master citation list.
- **Streams live** — each agent's status (pending → running → done/error), a running cost meter, and the synthesis tokens all arrive in real time over SSE.
- **Cites everything** — citations are stable UUIDs, so sources are never mis-numbered when deduplicated across findings.

## Highlights

- **Bring your own key (BYOK)** — run on your own Anthropic or OpenAI key. Keys are encrypted per-user with Fernet, stored write-only, and never returned to the client.
- **Free demo gallery** — pre-recorded real runs replay client-side in the browser, with no backend call and no API key required.
- **Resilient by design** — if a single researcher fails, the run degrades gracefully (that agent is marked, the report still completes and notes the gap) instead of failing hard.
- **Cost-aware** — live token/cost meter and adjustable research depth (quick / standard / deep).

## Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, async throughout, Pydantic v2 |
| Orchestration | LangGraph (3-node `StateGraph`) |
| LLM | Anthropic + OpenAI SDKs directly, behind an `LLMClient` Protocol |
| Web search | Anthropic server-side `web_search_20250305`; Tavily for non-Anthropic providers |
| Packaging | `uv` + `pyproject.toml` |
| Frontend | Next.js 16 (App Router), TypeScript strict, Tailwind v4, shadcn/ui |
| Auth + persistence | Supabase (Postgres + Auth) |
| Hosting | Vercel (frontend) · Render (backend) |

No LangChain or LiteLLM — the provider SDKs are called directly behind a small `LLMClient` Protocol. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the DAG, the SSE event contract, and v2 extension points.

## Run it locally

Requires `uv`, Node 20+, Docker (for `make dev`), and a Supabase project.

```bash
cp .env.example .env     # fill in the values below
make install             # backend deps (uv)
make install-frontend    # frontend deps (npm)
make dev                 # backend + frontend via docker compose
```

Backend on `:8000`, frontend on `:3000` → open <http://localhost:3000>.

### First-time setup

1. Create a Supabase project.
2. In the Supabase SQL editor, run `backend/migrations/001_initial.sql`, then `backend/migrations/002_credentials.sql`.
3. Fill in `.env` (see `.env.example`). Key values:
   - `ANTHROPIC_API_KEY` — for local runs and the optional owner-key free tier
   - `SUPABASE_URL`, `SUPABASE_DB_URL` — auth + persistence
   - `ARA_ENCRYPTION_KEY` — Fernet key for encrypting stored BYOK credentials
     (generate: `cd backend && uv run python -c "from ara.crypto import generate_key; print(generate_key())"`)
   - `TAVILY_API_KEY` — optional; web search for non-Anthropic providers
   - `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY` — frontend Supabase client
4. (Optional) enable Google sign-in under Supabase → Authentication → Providers.

### Make targets

| Target | What it does |
|---|---|
| `make dev` | start backend + frontend (docker compose) |
| `make dev-backend` / `make dev-frontend` | run one side with hot reload |
| `make test` | backend pytest suite |
| `make lint` | ruff + mypy `--strict` (backend), eslint (frontend) |
| `make install` / `make install-frontend` | install backend / frontend deps |

## Deployment

- **Frontend → Vercel** (root directory `frontend/`): set `BACKEND_ORIGIN` to the backend URL plus the `NEXT_PUBLIC_SUPABASE_*` vars. All `/api/*` calls (including the SSE stream) proxy to the backend through a same-origin Next.js rewrite, so auth cookies just work.
- **Backend → Render** (Docker, `backend/Dockerfile`, single instance): in production `ANTHROPIC_API_KEY` is intentionally left **unset**, so every live run uses the visitor's own stored key — keeping hosting cost at **$0** on the free tier.

## License

[MIT](./LICENSE) © 2026 Shriram Jana
