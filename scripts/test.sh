#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

PGUSER=${PGUSER:-postgres}
PGHOST=${PGHOST:-localhost}
TEST_DB=${TEST_DB:-frontier_test}

export DATABASE_URL="postgresql://${PGUSER}@${PGHOST}/${TEST_DB}"

psql "postgresql://${PGUSER}@${PGHOST}/postgres" -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TEST_DB}' AND pid <> pg_backend_pid();"

dropdb --if-exists -h "${PGHOST}" -U "${PGUSER}" "${TEST_DB}"
createdb -h "${PGHOST}" -U "${PGUSER}" "${TEST_DB}"

alembic upgrade head
pytest -q
