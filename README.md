# ARA

**Autonomous Research Assistant.** A three-stage agent pipeline
(Planner → Researchers → Synthesizer) that turns a research question into a
cited report, streamed live over SSE.

Flagship portfolio project for [LLMTechno](https://llmtechno.com).

## Stack

- **Backend**: Python 3.11, FastAPI, LangGraph, Anthropic SDK, Pydantic v2
- **Frontend**: Next.js 15 (App Router), TypeScript strict, Tailwind v4, shadcn/ui
- **Persistence**: in-memory (v1) behind a `ReportStore` Protocol — swap later
- **Web search**: Anthropic server-side tool (`web_search_20250305`)

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the DAG, streaming protocol, and
v2 extension points.

## First-time DB setup

1. Create a Supabase project (see [docs/superpowers/specs/2026-05-01-auth-and-history-design.md](docs/superpowers/specs/2026-05-01-auth-and-history-design.md) "Pre-flight" section)
2. Paste `backend/migrations/001_initial.sql` into the Supabase SQL editor and Run
3. Copy the values from your Supabase dashboard into `.env` (see `.env.example`)
4. Sign in once via the running frontend, then copy your `auth.users.id` (from Supabase Dashboard → Authentication → Users) into `ADMIN_USER_ID` in `.env`

## Quickstart

```bash
cp .env.example .env    # fill in ANTHROPIC_API_KEY
make install            # backend deps via uv
make install-frontend   # frontend deps via npm
make dev                # backend + frontend via docker compose
```

Backend on `:8000`, frontend on `:3000`. Open `http://localhost:3000`.

## Targets

| Target                  | What it does                                   |
| ----------------------- | ---------------------------------------------- |
| `make dev`              | Start backend + frontend (docker compose)      |
| `make test`             | Run backend pytest suite                       |
| `make lint`             | ruff + mypy --strict on backend, eslint on fe |
| `make install`          | `uv sync` the backend                          |
| `make install-frontend` | `npm install` the frontend                     |
