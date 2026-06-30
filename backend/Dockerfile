FROM python:3.11-slim

RUN pip install --no-cache-dir uv==0.11.3

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD uv run uvicorn ara.main:app --host 0.0.0.0 --port ${PORT:-8000}
