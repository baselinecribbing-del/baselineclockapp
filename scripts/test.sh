#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

export DATABASE_URL=postgresql://ArthurS@localhost/frontier_test

psql postgresql://ArthurS@localhost/postgres -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'frontier_test' AND pid <> pg_backend_pid();"

dropdb --if-exists frontier_test
createdb frontier_test

alembic upgrade head
pytest -q
