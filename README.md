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
