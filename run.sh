#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Prefer an explicit interpreter:
# - RUN_PYTHON=python3 ./run.sh
# - or activate a venv first
# - or create ./.venv and install requirements there
if [[ -n "${RUN_PYTHON:-}" ]]; then
  PY="${RUN_PYTHON}"
elif [[ -x "./.venv/bin/python" ]]; then
  PY="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

exec "${PY}" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
