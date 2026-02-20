#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
source venv/bin/activate

# Tests require a stable JWT secret; must be >= 32 chars to satisfy /auth/token validation.
export JWT_SECRET="${JWT_SECRET:-test-jwt-secret-for-pytest-only-0000000000000000}"


PGUSER=${PGUSER:-postgres}
PGHOST=${PGHOST:-localhost}
TEST_DB=${TEST_DB:-frontier_test}

export DATABASE_URL="postgresql://${PGUSER}@${PGHOST}/${TEST_DB}"

psql "postgresql://${PGUSER}@${PGHOST}/postgres" -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${TEST_DB}' AND pid <> pg_backend_pid();"

dropdb --if-exists -h "${PGHOST}" -U "${PGUSER}" "${TEST_DB}"
createdb -h "${PGHOST}" -U "${PGUSER}" "${TEST_DB}"

alembic upgrade head
pytest -q

# Optional: local smoke test for time_entries endpoints.
# Requires a running server (uvicorn) with the SAME JWT_SECRET as above.
# Usage example:
#   SMOKE_TIME_ENTRIES=1 BASE_URL=http://127.0.0.1:8000 COMPANY_ID=1 USER_ID=dev-user ./scripts/test.sh
if [ "${SMOKE_TIME_ENTRIES:-0}" = "1" ]; then
  BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"
  COMPANY_ID="${COMPANY_ID:-1}"
  USER_ID="${USER_ID:-dev-user}"
  EMPLOYEE_ID="${EMPLOYEE_ID:-101}"
  JOB_ID="${JOB_ID:-201}"
  SCOPE_ID="${SCOPE_ID:-301}"

  echo "=== SMOKE: mint token ==="
  RESP="$(curl -sS -X POST "${BASE_URL}/auth/token" \
    -H "Content-Type: application/json" \
    -d "{\"user_id\":\"${USER_ID}\",\"company_id\":${COMPANY_ID}}")"

  TOKEN="$(python - <<PY
import json
resp = json.loads('''$RESP''')
print(resp.get('access_token', ''))
PY
)"

  if [ "${#TOKEN}" -lt 20 ]; then
    echo "FAIL: could not mint token"
    echo "RESP=$RESP"
    exit 1
  fi

  echo "=== SMOKE: clock_in ==="
  curl -sS -o /dev/null -w "clock_in HTTP %{http_code}\n" -X POST "${BASE_URL}/time_entries/clock_in" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Company-Id: ${COMPANY_ID}" \
    -H "Content-Type: application/json" \
    -d "{\"employee_id\":${EMPLOYEE_ID},\"job_id\":${JOB_ID},\"scope_id\":${SCOPE_ID}}" \
    | grep -q "200" || { echo "FAIL: clock_in"; exit 1; }

  echo "=== SMOKE: active ==="
  curl -sS -o /dev/null -w "active HTTP %{http_code}\n" "${BASE_URL}/time_entries/active?employee_id=${EMPLOYEE_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Company-Id: ${COMPANY_ID}" \
    | grep -q "200" || { echo "FAIL: active"; exit 1; }

  echo "=== SMOKE: latest ==="
  curl -sS -o /dev/null -w "latest HTTP %{http_code}\n" "${BASE_URL}/time_entries/latest?employee_id=${EMPLOYEE_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Company-Id: ${COMPANY_ID}" \
    | grep -q "200" || { echo "FAIL: latest"; exit 1; }

  echo "=== SMOKE: clock_out ==="
  curl -sS -o /dev/null -w "clock_out HTTP %{http_code}\n" -X POST "${BASE_URL}/time_entries/clock_out" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Company-Id: ${COMPANY_ID}" \
    -H "Content-Type: application/json" \
    -d "{\"employee_id\":${EMPLOYEE_ID}}" \
    | grep -q "200" || { echo "FAIL: clock_out"; exit 1; }

  echo "=== SMOKE: active after clock_out (expect 404) ==="
  curl -sS -o /dev/null -w "active_after HTTP %{http_code}\n" "${BASE_URL}/time_entries/active?employee_id=${EMPLOYEE_ID}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "X-Company-Id: ${COMPANY_ID}" \
    | grep -q "404" || { echo "FAIL: expected 404 after clock_out"; exit 1; }

  echo "SMOKE_TIME_ENTRIES PASSED"
fi
