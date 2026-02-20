#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

echo "=== SNAPSHOT ==="
pwd
python -V
echo "python: $(which python)"
echo

echo "=== GIT ==="
echo "branch: $(git branch --show-current)"
git status -sb
echo
git log --oneline -5
