#!/usr/bin/env bash
set -euo pipefail

export TEST_DATABASE_URL="${TEST_DATABASE_URL:-postgresql://ArthurS@/frontier_test}"
pytest -q "$@"
