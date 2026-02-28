#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

# ---- config (override via env) ----
export DATABASE_URL="${DATABASE_URL:-postgresql://ArthurS@localhost/frontier_dev}"
export JWT_SECRET="${JWT_SECRET:-dev-secret-change-me-dev-secret-change-me}"
export PORT="${PORT:-8010}"

# ---- optional port preflight (KILL_PORT=1) ----
# If PORT is already in use, uvicorn exits with: [Errno 48] Address already in use
# Set KILL_PORT=1 to kill any local process listening on PORT before starting.
if [ "${KILL_PORT:-0}" = "1" ]; then
  if ! command -v lsof >/dev/null 2>&1; then
    echo "KILL_PORT=1 set but 'lsof' is not installed; cannot free port ${PORT}" >&2
  else
    echo "KILL_PORT=1 set; checking port ${PORT}..."
    PIDS="$(lsof -t -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | sort -u || true)"
    if [ -n "${PIDS}" ]; then
      echo "KILL_PORT=1 set; killing PIDs: ${PIDS}" | tr "\n" " "; echo
      kill ${PIDS} 2>/dev/null || true

      # Wait up to 2 seconds for the port to clear
      for _ in 1 2 3 4 5 6 7 8 9 10; do
        sleep 0.2
        if ! lsof -t -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1; then
          break
        fi
      done

      PIDS2="$(lsof -t -iTCP:${PORT} -sTCP:LISTEN 2>/dev/null | sort -u || true)"
      if [ -n "${PIDS2}" ]; then
        echo "KILL_PORT=1 set; force killing PIDs: ${PIDS2}" | tr "\n" " "; echo
        kill -9 ${PIDS2} 2>/dev/null || true
      fi
    else
      echo "KILL_PORT=1 set; port ${PORT} not in use"
    fi
  fi
fi

# ---- ensure dev DB exists (idempotent, quiet) ----
DB_NAME="$(
python - <<'PY'
import os
from urllib.parse import urlparse
u = urlparse(os.environ["DATABASE_URL"])
print((u.path or "").lstrip("/") or "")
PY
)"
if [ -n "$DB_NAME" ]; then
  createdb "$DB_NAME" >/dev/null 2>&1 || true
fi

# ---- migrate to head ----
alembic upgrade head

# ---- run server ----
exec uvicorn app.main:app --reload --port "$PORT"
