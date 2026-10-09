#!/usr/bin/env bash
# Start ARA in local mode: no sign-in, SQLite in ~/.ara, loopback only.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }
command -v node >/dev/null || { echo "Node.js 20+ is required: https://nodejs.org"; exit 1; }

[ -d backend/.venv ] || (cd backend && uv sync --all-extras)
[ -d frontend/node_modules ] || (cd frontend && npm install)

DATA_DIR="${ARA_DATA_DIR:-$HOME/.ara}"
OLLAMA="${OLLAMA_BASE_URL:-http://localhost:11434}"
OLLAMA="${OLLAMA%/}"
if curl -sf -m 2 "$OLLAMA/api/version" >/dev/null 2>&1; then
  n=$(curl -sf -m 2 "$OLLAMA/api/tags" | grep -o '"name"' | wc -l | tr -d ' ' || true)
  echo "Ollama: found (${n:-0} models)"
else
  echo "Ollama: not running (install from https://ollama.com, then: ollama pull qwen2.5:7b)"
fi

# Short drain + graceful timeout so Ctrl+C during a run stops in seconds; the
# interrupted report is closed as an error (and swept on the next start).
(cd backend && ARA_MODE=local ARA_DATA_DIR="$DATA_DIR" ARA_SHUTDOWN_DRAIN_SECONDS=3 \
  exec uv run uvicorn ara.main:app --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 5) &
BACK=$!
# -H 127.0.0.1: `next dev` binds 0.0.0.0 by default, and it proxies /api/* to the
# unauthenticated backend, so it must not be reachable from the LAN either.
(cd frontend && NEXT_PUBLIC_ARA_MODE=local BACKEND_ORIGIN=http://127.0.0.1:8000 \
  exec npm run dev -- -H 127.0.0.1) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true; wait $BACK $FRONT 2>/dev/null || true; exit 0' INT TERM

echo
echo "ARA local mode → http://localhost:3000   (data: $DATA_DIR)"
echo "Ctrl+C stops both servers."
wait $BACK $FRONT
