#!/usr/bin/env bash
set -euo pipefail

echo "== Delivery Check =="

if [ -f package.json ]; then
  echo "== Node project detected =="
  if [ -f package-lock.json ]; then
    npm ci
  else
    npm install
  fi
  npm run lint --if-present
  npm run typecheck --if-present
  npm test --if-present
  npm run build --if-present
fi

if [ -f requirements.txt ] || [ -f pyproject.toml ] || [ -f setup.py ]; then
  echo "== Python project detected =="
  if [ -f requirements.txt ]; then
    pip install -r requirements.txt
  fi
  if [ -f pyproject.toml ] || [ -f setup.py ]; then
    pip install -e . || true
  fi
  if command -v pytest >/dev/null 2>&1; then
    pytest
  else
    python -m unittest discover
  fi
fi

echo "== Secret pattern smoke check =="
grep -RInE '(api[_-]?key|secret|password|token|private[_-]?key)' .   --exclude-dir=.git   --exclude-dir=node_modules   --exclude-dir=.venv   --exclude=package-lock.json   || true

echo "== Delivery check complete =="
