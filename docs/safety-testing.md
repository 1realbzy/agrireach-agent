# Testing the safety gate

CI (`.github/workflows/regression.yml`) runs two jobs on every push to `main` and `work/**` and on pull requests. No secrets are passed to either job.

**Deterministic job.** Run the same steps locally from the repo root, in a virtual environment with `requirements.txt` installed:

```bash
export PYTHONPATH=tests:src AGRIREACH_SOURCE_CHECK=0 AGRIREACH_RAINFALL=off AGRIREACH_STT=none SMS_ENABLED=0 WHATSAPP_ENABLED=0
python -m pytest -q
python scripts/replay_safety.py --strict
python scripts/verify_legacy_migration.py
```

`PYTHONPATH=tests:src` also turns off optional ONNX telemetry in pytest and in speech subprocesses. The suite isolates `DATABASE_URL`, media and outbox paths. If your `.env` sets `AGRIREACH_JUDGE_BASE_URL`, unset it before running the suite; `tests/test_model_usage.py` fails when it is set.

`replay_safety.py` runs the deterministic gate over the approved texts recorded in the `docs/*run5*` to `docs/*run9*` live-eval folders. It fails if any labelled unsafe case is not `safety_blocked`. With `--strict` it also compares the record inventory with `docs/safety-remediation-replay.json`. It requires all 15 unsafe cases to be blocked and at least 17 normal cases to pass. Three unresolved-source and two missing-evidence records are known gaps.

`verify_legacy_migration.py` upgrades a temporary copy of the synthetic legacy fixture. It checks backfill, publication, historical log rows, backups and read-only verification.

**Speech job.** This job needs `requirements-voice.txt` and network access to download pinned public models:

```bash
export AGRIREACH_STT_DIR=/tmp/agrireach-whisper AGRIREACH_TTS_DIR=/tmp/agrireach-piper AGRIREACH_REQUIRE_SPEECH=1
python scripts/cache_speech_models.py
python -m pytest -q tests/test_stt_real.py tests/test_qa_remediation.py
```

With `AGRIREACH_REQUIRE_SPEECH=1`, any skip fails. Without the models, the speech tests skip, but the voice-approval regression in `test_qa_remediation.py` still runs.

**What the tests show and don't show.** Gate tests use `tests/fixtures/safety/frozen_cases.json` and the Round 4 acceptance lines in `tests/acceptance_r4.md`. Keep fixture labels and the source documents unchanged, and add new adversarial cases separately, with a note on why they were added. Transaction tests use real SQLite files and threads. Provider tests use mocked HTTP, simulator tests write a local outbox, and MCP tests start a real subprocess. None of this shows real farmer delivery, and synthetic English clips don't validate Ghanaian accents or local languages. Live model runs are recorded separately in [EVALS.md](../EVALS.md).
