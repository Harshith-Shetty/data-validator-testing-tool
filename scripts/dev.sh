#!/usr/bin/env bash
# Start the validation API and the Angular dashboard together.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -d "$ROOT/backend/.venv" ]; then
  echo "Creating the Python virtualenv…"
  python3 -m venv "$ROOT/backend/.venv"
  "$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Installing frontend dependencies…"
  (cd "$ROOT/frontend" && npm install)
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "API      -> http://localhost:8000  (docs at /docs)"
echo "Dashboard-> http://localhost:4200"

(cd "$ROOT/backend" && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
(cd "$ROOT/frontend" && npm start) &

wait
