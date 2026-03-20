#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_SORTDOCS="${PROJECT_ROOT}/.venv/bin/sortdocs"

if [[ ! -x "${VENV_SORTDOCS}" ]]; then
  echo "Missing executable: ${VENV_SORTDOCS}" >&2
  echo "Create the project virtualenv first, then install the launcher." >&2
  exit 1
fi

choose_target_dir() {
  if [[ -n "${SORTDOCS_BIN_DIR:-}" ]]; then
    printf '%s\n' "${SORTDOCS_BIN_DIR}"
    return 0
  fi

  for candidate in /opt/homebrew/bin /usr/local/bin "${HOME}/.local/bin" "${HOME}/bin"; do
    if [[ -d "${candidate}" && -w "${candidate}" && -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done

  printf '%s\n' "${HOME}/.local/bin"
}

TARGET_DIR="$(choose_target_dir)"
if [[ ! -d "${TARGET_DIR}" ]]; then
  mkdir -p "${TARGET_DIR}"
fi

TARGET_PATH="${TARGET_DIR}/sortdocs"
TMP_PATH="${TARGET_PATH}.tmp.$$"

cat > "${TMP_PATH}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
GLOBAL_ENV_PATH="\${HOME}/.config/sortdocs/.env"
if [[ -f "\${GLOBAL_ENV_PATH}" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "\${GLOBAL_ENV_PATH}"
  set +a
fi
if [[ -f "${PROJECT_ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${PROJECT_ROOT}/.env"
  set +a
fi
exec "${VENV_SORTDOCS}" "\$@"
EOF

chmod +x "${TMP_PATH}"
mv "${TMP_PATH}" "${TARGET_PATH}"

echo "Installed launcher at ${TARGET_PATH}"
echo "You can now run: sortdocs ."
