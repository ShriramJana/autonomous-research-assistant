.PHONY: install install-frontend dev dev-backend dev-frontend test lint typecheck fmt

install:
	cd backend && uv sync --all-extras

install-frontend:
	cd frontend && npm install

dev:
	docker compose up --build

dev-backend:
	cd backend && uv run uvicorn ara.main:app --reload --host 0.0.0.0 --port 8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest -q

lint:
	cd backend && uv run ruff check .
	cd backend && uv run mypy src
	cd frontend && npm run lint

fmt:
	cd backend && uv run ruff format .
