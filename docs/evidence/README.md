# Dated evidence

Records from earlier review rounds and live runs, kept unchanged for the record. They describe the code at the time they were written, not the current code; see [ARCHITECTURE.md](../../ARCHITECTURE.md) for that.

| File | What it is |
|---|---|
| [implementation-progress.md](implementation-progress.md) | Safety-hardening checkpoints, 26 Oct 2026 |
| [safety-verification.md](safety-verification.md) | Developer test evidence for the safety-hardening branch |
| [remediation-progress.md](remediation-progress.md) | QA remediation progress, 26 Oct 2026 |
| [qa-remediation-report.md](qa-remediation-report.md) | Developer remediation report, 26 Oct 2026 |
| [round2-progress.md](round2-progress.md), [round2-report.md](round2-report.md) | Round 2 remediation |
| [safety-debugging.md](safety-debugging.md) | Debugging notes from the safety-hardening branch; the current version is in ARCHITECTURE.md |
| [safety-historical-replay.json](safety-historical-replay.json) | An earlier output of `scripts/replay_safety.py`; CI compares against `docs/safety-remediation-replay.json` |
| [rainfall-live-2026-10-25.md](rainfall-live-2026-10-25.md) | Live Open-Meteo and NASA POWER calls, 25 Oct 2026 |
| [season-fact-live-2026-10-25.md](season-fact-live-2026-10-25.md) | Live check of the season fact and top-dressing rainfall, 25 Oct 2026 |

Other dated evidence stays in `docs/` because a script, test or CI step reads it by path: the `eval-run*.txt` files, the `live-eval-2026-10-25-run*` folders and notes, `officer-regrade/`, `round2-browser/` and `safety-remediation-replay.json`.
