SHELL := /bin/bash
PY ?= python3
VENV := .venv
BIN := $(VENV)/bin
export PYTHONPATH := $(CURDIR)/src

.PHONY: install test run ask clean

$(BIN)/activate: requirements.txt
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q -r requirements.txt
	touch $(BIN)/activate

install: $(BIN)/activate

test: install
	$(BIN)/python -m pytest -q

ask: install  ## make ask Q="When should I harvest soybean in Tamale?"
	set -a; [ -f .env ] && . ./.env; set +a; $(BIN)/python -m agrireach.agent "$(Q)"

run: install  ## API on :8000, UI on :8501
	set -a; [ -f .env ] && . ./.env; set +a; \
	$(BIN)/uvicorn agrireach.api:app --port 8000 & API=$$!; \
	trap "kill $$API" EXIT; \
	$(BIN)/streamlit run src/agrireach/ui.py --server.port 8501 --server.headless true

clean:
	rm -rf $(VENV) data/agrireach.db
