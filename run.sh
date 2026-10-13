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
.venv/bin/uvicorn agrireach.api:app --host 127.0.0.1 --port 8000 &
API=$!
trap 'kill $API 2>/dev/null' EXIT
.venv/bin/streamlit run src/agrireach/ui.py --server.port 8501 --server.headless true
