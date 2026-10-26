# Testing the safety branch

Install requirements.txt in an isolated Python environment. The investigation used Python 3.12.14; the historical project record used a different environment. Optional speech tests additionally need requirements-voice.txt and locally cached models.

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest -q tests/test_safety_checkpoint1.py tests/test_safety_checkpoint2.py
PYTHONPATH=src python -m pytest -q tests/test_mcp.py tests/test_agent.py tests/test_channels.py
```

The suite isolates DATABASE_URL, media and outbox paths. The gate tests use the frozen_cases.json corpus committed before the implementation. Keep fixture labels and the original source documents unchanged. Additional adversarial cases must be separate, with their rationale recorded.

The transaction tests use real SQLite files and threads. Provider tests use mocked HTTP; simulator tests write an actual local outbox. MCP tests launch a real subprocess. None of these demonstrate real farmer delivery.

Live model calls are not required for deterministic blocks. Fresh live model and real speech verification have not been performed on this implementation. Do not infer availability from environment variable names or print key values. Run `PYTHONPATH=src python scripts/replay_safety.py` for deterministic historical replay; its JSON output separates normal historical candidates, deliberate attacks and missing evidence. No live model configuration was available during this implementation. Final acceptance remains blocked by the measured policy compatibility issue recorded in the progress report.
