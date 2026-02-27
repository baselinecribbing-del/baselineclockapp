#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

# ---- config (override via env) ----
export DATABASE_URL="${DATABASE_URL:-postgresql://ArthurS@localhost/frontier_dev}"
export JWT_SECRET="${JWT_SECRET:-dev-secret-change-me-dev-secret-change-me}"
export PORT="${PORT:-8010}"

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
uvicorn app.main:app --reload --port "$PORT"
