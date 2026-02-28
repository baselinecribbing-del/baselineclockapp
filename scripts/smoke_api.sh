#!/usr/bin/env bash
set -euo pipefail

# Smoke test for running API server (no DB seeding).
# Assumes server is already running (e.g., via ./scripts/dev.sh).

PORT="${PORT:-8010}"
BASE_URL="${BASE_URL:-http://127.0.0.1:${PORT}}"
COMPANY_ID="${COMPANY_ID:-1}"
USER_ID="${USER_ID:-dev-user}"

# Must match the server's JWT_SECRET.
# scripts/dev.sh default:
JWT_SECRET="${JWT_SECRET:-dev-secret-change-me-dev-secret-change-me}"
export JWT_SECRET

echo "== smoke_api =="
echo "BASE_URL=${BASE_URL}"
echo "COMPANY_ID=${COMPANY_ID}"
echo "USER_ID=${USER_ID}"
echo "JWT_SECRET len=${#JWT_SECRET}"

# Server reachability
curl -sS "${BASE_URL}/docs" >/dev/null
echo "SERVER_OK"

# Mint token
TOKEN="$(curl -sS -X POST "${BASE_URL}/auth/token" \
  -H "Content-Type: application/json" \
  -d "{\"user_id\":\"${USER_ID}\",\"company_id\":${COMPANY_ID}}" \
  | python -c 'import sys, json; print(json.load(sys.stdin).get("access_token",""))')"

test "${#TOKEN}" -ge 20 || { echo "FAIL: token minting failed"; exit 1; }
echo "TOKEN_OK len=${#TOKEN}"

auth_hdr=(-H "Authorization: Bearer ${TOKEN}" -H "X-Company-Id: ${COMPANY_ID}")

echo "== GET /outbox =="
curl -sS "${BASE_URL}/outbox?limit=5&offset=0" "${auth_hdr[@]}"
echo

echo "== GET /payroll/runs =="
curl -sS "${BASE_URL}/payroll/runs?limit=5&offset=0" "${auth_hdr[@]}"
echo

echo "== GET /costing/ledger/totals =="
curl -sS "${BASE_URL}/costing/ledger/totals?date_start=2026-01-01T00:00:00Z&date_end=2026-12-31T00:00:00Z" "${auth_hdr[@]}"
echo

echo "SMOKE_API PASSED"
