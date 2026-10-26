# Testing the safety branch

For Round 2, run tests with `PYTHONPATH=tests:src` so optional ONNX telemetry is
disabled in both pytest and speech subprocesses. Set AGRIREACH_REQUIRE_SPEECH=1
for a speech acceptance run; any skip then fails. Use a verified pinned model cache.
Run historical replay with --strict to validate record identity and explicitly
retain the five known evidence gaps. See round2-report.md and round2-progress.md.

Install requirements.txt in an isolated Python environment. The investigation used Python 3.12.14; the historical project record used a different environment. Optional speech tests additionally need requirements-voice.txt and locally cached models.

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest -q tests/test_safety_checkpoint1.py tests/test_safety_checkpoint2.py
PYTHONPATH=src python -m pytest -q tests/test_mcp.py tests/test_agent.py tests/test_channels.py
```

The suite isolates DATABASE_URL, media and outbox paths. The gate tests use the frozen_cases.json corpus committed before the implementation. Keep fixture labels and the original source documents unchanged. Additional adversarial cases must be separate, with their rationale recorded.

The transaction tests use real SQLite files and threads. Provider tests use mocked HTTP; simulator tests write an actual local outbox. MCP tests launch a real subprocess. None of these demonstrate real farmer delivery.

Live model calls are not required for deterministic blocks. No live advisory model configuration was available for remediation. Real Whisper and Piper verification is separate from mocked speech tests. Synthetic English clips do not validate Ghanaian accents or native languages. See docs/remediation-progress.md for actual results and pending independent acceptance.

```bash
PYTHONPATH=src python scripts/replay_safety.py
PYTHONPATH=src python scripts/verify_legacy_migration.py
PYTHONPATH=src python -m pytest -q tests/test_qa_remediation.py
pip install -r requirements-voice.txt
export AGRIREACH_STT_DIR=/tmp/agrireach-whisper
export AGRIREACH_TTS_DIR=/tmp/agrireach-piper
python scripts/cache_speech_models.py
PYTHONPATH=src python -m pytest -q tests/test_stt_real.py
```

The model cache script pins public speech model revisions. Downloads require network access. No API key or paid model is used. Without dependencies or cached assets the optional speech module skips; the model independent voice approval regression always runs in test_qa_remediation.py. CI has a separate speech job which downloads assets before running the module. Replay exits nonzero if any labelled unsafe case passes. The legacy migration check creates a temporary database from the synthetic SQL fixture and verifies backfill, publication, historical log rows, backups and read only verification.
