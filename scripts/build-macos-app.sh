#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

choose_python() {
  local candidates=()
  local candidate=""

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    candidates+=("$PYTHON_BIN")
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    candidates+=("$ROOT_DIR/.venv/bin/python")
  fi
  if command -v python >/dev/null 2>&1; then
    candidates+=("$(command -v python)")
  fi
  if command -v python3.11 >/dev/null 2>&1; then
    candidates+=("$(command -v python3.11)")
  fi
  if command -v python3 >/dev/null 2>&1; then
    candidates+=("$(command -v python3)")
  fi
  if [[ -x "/opt/homebrew/bin/python3.11" ]]; then
    candidates+=("/opt/homebrew/bin/python3.11")
  fi

  for candidate in "${candidates[@]}"; do
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
      >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done

  return 1
}

PYTHON_BIN="$(choose_python || true)"

if [[ -z "${PYTHON_BIN:-}" ]]; then
  echo "Python 3.11+ is required to build the standalone app bundle." >&2
  echo "Install Python 3.11 and create a virtualenv first." >&2
  exit 1
fi

export PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON_BIN" -m sortdocs.bundling --project-root "$ROOT_DIR" --python-executable "$PYTHON_BIN"
