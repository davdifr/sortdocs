#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
VENV_GUI="${PROJECT_ROOT}/.venv/bin/sortdocs-gui"
GLOBAL_ENV_PATH="${HOME}/.config/sortdocs/.env"

if [[ -f "${GLOBAL_ENV_PATH}" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${GLOBAL_ENV_PATH}"
  set +a
fi

if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${PROJECT_ROOT}/.env"
  set +a
fi

if [[ ! -x "${VENV_GUI}" ]]; then
  echo
  echo "sortdocs GUI is not installed yet."
  echo
  echo "From the project folder, run:"
  echo "  brew install python@3.11"
  echo "  /opt/homebrew/bin/python3.11 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e '.[gui,dev]'"
  echo
  echo "Then double-click this file again."
  echo
  read -r -p "Press Enter to close..."
  exit 1
fi

cd "${PROJECT_ROOT}"
exec "${VENV_GUI}"
