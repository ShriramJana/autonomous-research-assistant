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

(cd backend && ARA_MODE=local ARA_DATA_DIR="$DATA_DIR" \
  exec uv run uvicorn ara.main:app --host 127.0.0.1 --port 8000) &
BACK=$!
(cd frontend && NEXT_PUBLIC_ARA_MODE=local BACKEND_ORIGIN=http://127.0.0.1:8000 exec npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true; wait $BACK $FRONT 2>/dev/null || true; exit 0' INT TERM

echo
echo "ARA local mode → http://localhost:3000   (data: $DATA_DIR)"
echo "Ctrl+C stops both servers."
wait $BACK $FRONT
