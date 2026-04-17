# ara — backend

FastAPI service that orchestrates the three-stage agent pipeline and streams
events to the frontend over SSE.

```bash
uv sync --all-extras
uv run uvicorn ara.main:app --reload
uv run pytest
uv run mypy src
```
