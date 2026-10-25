# Run 9: final check on `e79c43c` (25 Oct 2026, UTC)

All grades are self-graded. Raw output is in [live-eval-2026-10-25-run9-final-check/](live-eval-2026-10-25-run9-final-check/). The branch `eval/live-e79c43c` carries the run 7 and run 8 docs commits forward, because neither was in `e79c43c`.

## 1. What changed since `9948f0d`
`git diff --stat 9948f0d e79c43c`:

| File | Change |
|---|---|
| `EVALS.md` | +5 |
| `src/agrireach/agent.py` | +2 −1: passes `draft_mode` to `audit_entry` |
| `src/agrireach/farmer_reply.py` | +11 −2: `audit_entry(fd, draft_mode)` sets `draft_mode` and `offline_draft`, and adds "officer draft was the offline stub draft…" to the summary |
| `tests/test_run7_audit_draft_origin.py` | +52, new |
| `tests/test_run6_approval_safety.py` | +4 −2 |

- **Pass, with one addition to the expected list.** The source changes are only the audit-log `draft_mode`/`offline_draft` field.
- The one file outside "that field, its tests and EVALS.md" is `tests/test_run6_approval_safety.py`. That is QA's swap tests (`4bac6cf`, merged in `ae15315`), and it is a test file only.

## 2. Full suite
`PYTHONPATH=src pytest -q`, run with the test venv and no `LLM_API_KEY` in the environment: **625 passed** in 95 s, 0 failed. This matches Developer's 625.

## 3. Tiny live run (fresh DB, real HTTP, mock SMS gateway)
- Same harness as runs 6–8.
- Model server: OpenRouter, drafter `mistralai/mistral-small-3.2-24b-instruct`, judge `meta-llama/llama-3.3-70b-instruct`.
- No-model server: `LLM_BASE_URL`, `LLM_MODEL` and every key unset, so `/health` reports `draft_mode: stub`.
- Both servers got the F1 question by SMS webhook. Both cases were approved with the proposed text.

| Case | `farmer_text_proposal` entry | Approval | Byte-for-byte delivery |
|---|---|---|---|
| F1, model | `path: model`, `draft_mode: llm:mistralai/mistral-small-3.2-24b-instruct`, **`offline_draft: false`**; summary "model SMS proposed" (589 chars, one APNI line, the model's own referral removed as a repeat) | 200, no warnings | **Pass** (phone == farmer view == record == approved text) |
| F1, no model | `path: rule`, `draft_mode: stub`, **`offline_draft: true`**; summary "rule-based text proposed. officer draft was the offline stub draft (no language model): stub. 3 sentence(s) dropped to fit: …" | 200, one warning: "source check couldn't run: no judge model is configured" | **Pass** |

Both entries are as required. **Pass.**

**Cost:**
- App: $0.001060, 5/5 calls; the no-model server made no calls.
- Key counter: 0.087403258 → 0.088462888, a delta of **$0.001060**. They match.
- No 402.

## 4. EVALS.md known limits (Developer's text in `e79c43c`, not edited)

| Limit | Stated? |
|---|---|
| Negated AEA line counts as kept | **Present**, but stale: it says the judge "should flag it, though that is not tested". Run 8 tested it live: the judge flagged it ("opposite advice") and did not block |
| A safety-line warning does not block approval; the officer decides | **Missing**. No known-limit line says the warnings are advisory and the text is sent |
| An unsafe sentence added next to a kept safety line is caught only by the judge | **Missing** (run 8, ADD) |
| False judge warnings | **Partial**: only F5 "Extra source". Missing F1-c's rotation sentence ("Extra sources cited", run 7) and BD's rotation sentence ("p22-sacks unrelated", run 8) |
| Rate limits | **Present**, but partly inaccurate. It says those cases "used the offline stub draft". In run 7, 3 of the 6 did (cases 11–13). The other 3 (cases 15, 17, 18) had a model draft, and their model SMS call failed, so they used the rule text ("model rewrite failed (RateLimitError/InternalServerError)") |
| Kɔforidua spelling | **Present**, as the "place names written with Twi letters" known limit (`zones.zone_for` misses Kɔforidua/Tɛchiman) |

## Summary
- **Pass:** diff scope (plus QA's test file), 625 tests, model/offline audit entries, byte-for-byte delivery, cost match.
- **EVALS gaps:**
  - two limits missing (warnings don't block; an added unsafe sentence is caught only by the judge);
  - one partial (false judge warnings);
  - two present but stale or inaccurate (negated line; rate limits).
