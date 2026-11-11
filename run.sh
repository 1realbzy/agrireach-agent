#!/usr/bin/env bash
# One-command start: ./run.sh  (creates .venv, installs pinned deps, starts API :8000 and UI :8501)
# ./run.sh test  -> runs the pytest suite instead.
set -euo pipefail
cd "$(dirname "$0")"
PY=${PY:-python3}
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/pip install -q -r requirements.txt
export PYTHONPATH="$PWD/src"
set -a; [ -f .env ] && . ./.env; set +a
if [ "${1:-}" = "test" ]; then exec .venv/bin/python -m pytest -q; fi
API_PORT=${AGRIREACH_API_PORT:-8000}
UI_PORT=${AGRIREACH_UI_PORT:-8501}
export AGRIREACH_API="${AGRIREACH_API:-http://127.0.0.1:$API_PORT}"
.venv/bin/uvicorn agrireach.api:app --host 127.0.0.1 --port "$API_PORT" --ws none &
API=$!
trap 'kill $API 2>/dev/null' EXIT
.venv/bin/streamlit run src/agrireach/ui.py --server.address 127.0.0.1 --server.port "$UI_PORT" --server.headless true
