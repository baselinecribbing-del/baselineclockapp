#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

export DATABASE_URL=postgresql://ArthurS@localhost/frontier_dev

createdb frontier_dev || true

alembic upgrade head

export JWT_SECRET="${JWT_SECRET:-dev-secret-change-me-dev-secret-change-me}"

uvicorn app.main:app --reload
