#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

py="python3"
if [ -f ".python-version" ]; then
  pinned="$(tr -d '[:space:]' < .python-version)"
  if [ -n "$pinned" ] && command -v "python$pinned" >/dev/null 2>&1; then
    py="python$pinned"
  fi
fi

"$py" -m py_compile official_docs_mcp/*.py
"$py" -m unittest discover -s tests

# ruff.toml があるので、ruff が入っていれば lint も通す。
# 依存ゼロで動く性質は保つため、未インストール時は skip する。
if command -v ruff >/dev/null 2>&1; then
  ruff check .
  ruff format --check .
else
  echo "ruff not installed; skipping lint (config: ruff.toml)"
fi
