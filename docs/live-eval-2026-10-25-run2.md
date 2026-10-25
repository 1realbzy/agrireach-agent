# Live eval on `a6222d1`: F1–F14 twice, plus Ejura planting ×5 (25 Oct 2026)

**Code:** `fix/review-findings` at `a6222d1`, which includes `1c241f3` (max_tokens and usage/cost logging), `a1e85a5` (attempted vs succeeded calls, `drafted_by`) and `d1685de` (Ejura rainfall-citation fix). It ran from a throwaway worktree on branch `eval/live-a6222d1`, so Developer's branch was not touched. Each process used its own temporary SQLite DB.

**Models (OpenRouter):**
- Drafter and SMS rewriter: `mistralai/mistral-small-3.2-24b-instruct`.
- Judge: `meta-llama/llama-3.3-70b-instruct`.
- All at temperature 0, with the default token caps (draft 800, farmer text 400, judge 1500).

**Other settings:** `FETCH_MCP_ARGS=--allow-private-ips`, source-page fetch check on, live Open-Meteo rainfall.

**How it ran:** `scripts/run_evals.py field` ran unchanged. A small wrapper, `docs/live-eval-2026-10-25-run2/wrap.py`, recorded the extra fields for each agent run:
- the proposed farmer SMS and its length, encoding and parts (`channels.sms.measure`);
- the model's SMS rewrites;
- every judge verdict, tagged as either draft or SMS check.

It doesn't change any code path. It stops the process at the first failed model call. No call failed, so it never stopped a run.

Raw output is in `docs/live-eval-2026-10-25-run2/`: `R1.out`, `R2.out` and `EJ.out` are the script output, and the `*.side.jsonl` files hold the wrapper records.

**All three runs are complete. None is partial.**

## Calls, tokens, cost, time (measured)

| Run | Start (UTC) | Model calls succeeded / attempted | Tokens (prompt + completion) | OpenRouter-reported cost | Wall time | Cost per question |
|---|---|---|---|---|---|---|
| R1: F1–F14 | 18:56:02 | **32 / 32** | 20,625 + 2,969 = 23,594 | **$0.003136** | 131 s | $0.000285 per agent run (11), or $0.000314 per model-reached question (10) |
| R2: F1–F14 | 18:59:28 | **32 / 32** | 21,173 + 3,032 = 24,205 | **$0.002855** | 145 s | $0.000260 (11), or $0.000286 (10) |
| EJ: Ejura planting ×5 | 19:02:07 | **22 / 22** | 30,513 total | **$0.005011** | 284 s | $0.001002 per run |

**How the counts break down:**
- F12 and F13 are skipped placeholders. F14 is code-only. F3 asks for the crop, so it makes no model call.
- Per role, R1 made 14 draft calls (9,969 + 1,521 tokens), 12 judge calls (9,293 + 1,148) and 6 farmer-text calls (1,363 + 300). R2's split was nearly the same.
- The script exited 0 on both field runs, and its `usage_summary` matches the table.

**Cost checks:**
- The key's lifetime usage after all three runs was $0.011104. The runs add up to $0.011002, and the earlier 5-token probe cost $0.0000017.
- The account still shows `total_credits: 0`, but no 402 occurred.
- One oddity: EJ4 and EJ5 used identical token counts, yet OpenRouter reported $0.000699 and $0.001260. That is probably different upstream providers.

Times in Accra are the same as UTC.

## Per-task outcome

In the Draft column:
- **model ✓1:** the model draft passed every check on the first attempt.
- **model ✓2:** it passed after one regeneration.
- **fallback:** both attempts failed, so the verbatim passages are shown.

All drafts go to `pending_review`. Nothing was approved in this run.

The judge column counts sentences the judge marked not_supported on the draft, then on the SMS. All SMS are GSM-7.

| Task | R1 draft | R1 judge NS (draft/SMS) | R1 SMS | R2 draft | R2 judge NS | R2 SMS | Changed? |
|---|---|---|---|---|---|---|---|
| F1 Adaklu armyworm | fallback | 1+1 / – | rule, 393 ch, 3 parts | **model ✓1** | 0 / 0 | model, 506 ch, 4 parts | **yes** |
| F2 soil in funnel | fallback | 1+0 / – | rule, 588 ch, 4 parts | fallback | 1+0 / – | rule, 588 ch, 4 | no |
| F3 Upper West dry spell | clarification (asks crop) | – | none | clarification | – | none | no |
| F4 late rains Northern | fallback (auto **FAIL**) | 1+1 / – | rule + confirm line, 581 ch, 4 | fallback (auto **FAIL**) | 1+1 / – | rule + confirm, 581 ch, 4 | no (reasons differ) |
| F5 knee-high fertiliser | model ✓1 | 0 / 0 | model, 373 ch, 3 | model ✓1 | 0 / 0 | model, 373 ch, 3 (identical) | no |
| F6 weevils | **model ✓1** | 0 / 0 | model, 204 ch, 2 | **fallback** | 1+1 / – | rule, 537 ch, 4 | **yes** |
| F7 mouldy maize | fallback | 2+2 / – | rule, 537 ch, 4 | fallback | 3+1 / – | rule, 537 ch, 4 | no |
| F8 tomato price | model "I do not know." | – | model SMS rejected ('60' not in officer text) → "I do not know.", 14 ch, 1 | same | – | same | no |
| F9 cocoa price | model "I do not know." | – | model SMS rejected (bare "contact your extension officer", no source) → "I do not know." | same | – | same | no |
| F10 who to call | model "I do not know." | – | model SMS rejected ("still addresses the officer") → "I do not know." | same | – | same | no |
| F11 black pod spray | model "I do not know." | – | model SMS rejected (invented "20 grams… 10 liters… 14 days") → "I do not know." | same (R2 invented "7 to 14 days") | – | same | no |
| F14 voice script | pass (code) | – | – | pass | – | – | no |

**Field auto checks:** 11/12 in both runs. F4 failed both times on "verbatim fallback was used".

**Model drafts that passed (✓1 or ✓2):** 6 of 10 in R1 and 6 of 10 in R2. That includes the four F8–F11 "I do not know." drafts.

**Fallbacks:** 4 per run.

**Every SMS fits the 4-part limit.** All are GSM-7 (none switched to Unicode). The longest is 588 characters in 4 parts.

**Variation between runs (temperature 0):** 2 of 12 tasks changed outcome.
- F1 went from fallback to a model pass.
- F6 went from a model pass to fallback.

The other 10 kept the same outcome. F5's draft and SMS were byte-identical in both runs. F4 and F7 fell back both times, but for different sentences.

## Ejura planting ("When should I plant maize in Ejura?"), after `d1685de`

| Run | Result | Attempt problems | SMS |
|---|---|---|---|
| EJ1 | model ✓2 | a1: uncited "A rainfall record is attached… guides do not specify a rainfall…" failed the lexical check (no shared content words) | model, 486 ch, 4 parts |
| EJ2 | **fallback** | a1: judge rejected "However, this is a model estimate and may differ from local conditions." a2: windows cited to the wrong passages (6 figure errors), conflict not shown | rule, 574 ch, 4 |
| EJ3 | **fallback** | a1: judge rejected "A rainfall record is attached for the officer's reference [RAINFALL-…]" ("No claim made"). a2: judge rejected "Choose the appropriate window… confirm the specific zone's timing." | rule, 574 ch, 4 |
| EJ4 | model ✓1 | none | model, 385 ch, 3 |
| EJ5 | model ✓1 | none | model, 385 ch, 3 (same as EJ4) |

**Before `d1685de`** (on `e12846c`, from the earlier partial run):
- First attempt passed 0/5, and all 5 had "names RAINFALL but cites no RAINFALL passage".
- 2/5 passed after a regeneration.
- 3/5 fell back.

**Now:**
- First attempt passed **2/5**.
- **1/5** passed after a regeneration.
- **2/5** fell back.
- The "names RAINFALL but cites no RAINFALL passage" problem appeared in **0 of 8** draft attempts.

**What still causes the fallbacks:**
- EJ2's second attempt had real citation errors.
- EJ3 failed only on judge verdicts I'd grade as false (next section).
- EJ2's first attempt was also a false reject: the rainfall record itself says it is a model estimate.

Five runs is a small sample.

**Rainfall figures in a farmer SMS:** EJ1's model SMS contains "A rainfall record from 2026-09-25 to 2026-10-24 shows 24 of 30 days with at least 1 mm and a total of 185.5 mm." The SMS judge accepted it because the record is one of the case's sources. However:
- Rainfall figures are meant to be officer-only.
- The SMS leaves out the record's "model estimate, not a gauge reading" caveat.
- In the earlier run, a working judge rejected the same kind of sentence.

`sms_claims` should probably exclude `RAINFALL-*` records from the passages a farmer SMS can rely on.

## QA criterion 5: the F1 safety line survives

**PASS in 2/2 English runs:**
- **R1**, rule SMS (393 characters): keeps "Application of recommended pesticides can help to control infestations once they occur. Consult your local AEA for advice on the recommended fall army worm control pesticide in your area."
- **R2**, model SMS (506 characters): keeps "If the worms are still a problem after spraying, ask your local Agricultural Extension Agent for advice on the right pesticides to use."

No product name or dose appears in either. On `e12846c`, the line was dropped in 4/4 runs.

Twi and Dagbani are still **not testable**, because F12 and F13 have no native-speaker wording.

## QA criterion 7: false rejects (**self-graded**)

I read each sentence the judge marked not_supported against the case's passages. These are my grades, not an independent review.

**Draft-check judge rejections (R1, R2, EJ):** 21 sentences.
- **False (9):**
  - F1 R1 ×2: "The officer should inspect… or refer the farmer to an expert". The prompt treats officer refer/check lines as supported.
  - F2 R1, F2 R2: "We do not know if putting soil… is enough". An honest abstention.
  - F4 R2 ×2: "The planting window varies by source." True, since the sources differ.
  - EJ2 a1: "this is a model estimate". The rainfall record says so.
  - EJ3 a1: "A rainfall record is attached…". The judge's own reason was "No claim made".
  - EJ3 a2: "Choose the appropriate window… confirm…". An officer choose/confirm line.
- **Borderline (3):**
  - F6 R2 a1: "Inspect the maize… or refer to a specialist".
  - F6 R2 a2: "To prevent weevils… well dried and shelled [p22-shelling]". The judge gave the pest name as its reason, which the prompt allows, but drying is in a different passage.
  - F7 R2 a2: "advise the farmer to check these limits".
- **True (9):**
  - F4 R1 a1: "end of July only with early varieties", cited to MoFA p10.
  - F4 R1 a2: the yields sentence cites the p12 table.
  - F7 ×7: "do not sell or feed", "dispose safely", "EU and US FDA have lower limits" (FDA's 20 ppb is not lower than GSA's 15), "test before deciding" ×2, "proper storage prevents mould", "advise to test".

So **9 of 21 judge rejections were false (43%)** and 3 were borderline.

Lexical-layer false rejects also happened in both F2 runs: "The passages do not mention this method." and "We do not know if this method is effective." failed on "no shared content words".

**At case level:** 25 model-drafted cases, 10 fallbacks.
- **5 fell back only because of false rejects:** R1 F1, R1 F2, R2 F2, R2 F4, EJ3.
- 1 was borderline: R2 F6.
- 4 were justified: R1 F4, R1 F7, R2 F7, EJ2.

That is **5/25 = 20% of model-drafted cases lost to false rejects** (self-graded), right at the "about 1 in 5" line.

**Recurring patterns:**
- Officer-addressed "inspect / refer / choose / confirm" lines.
- Honest "we do not know" lines.
- Sentences that describe the attached rainfall record.

**SMS-check judge:** 7 model SMS were judged (R1 F5, F6; R2 F1, F5; EJ1, EJ4, EJ5).
- **0 were rejected**, so there were 0 false rejects at the SMS stage.
- Two were **false accepts**:
  - F5 in both runs: "You can still apply the subsidised fertiliser, but only if the soil is moist". The passages give 6 weeks and say nothing about whether applying at about 2 months is still worthwhile.
  - EJ1: the rainfall figures above.
- The 8 F8–F11 model SMS were all rejected by the code checks before the judge. All 8 rejections were correct: the farmer's price echoed back, an unsourced "contact your officer", and invented spray doses.

## Earlier partial run (hit a 402): `docs/sms-claim-check-live-2026-10-25.md`, commit `31097bd` on `feat/rainfall-signal` (not merged)

This is a **partial run**. The OpenRouter balance ran out partway through. Most drafting and judge calls returned **HTTP 402**, because AgriReach sent no `max_tokens` at the time. The app then quietly used offline stub drafts.

It ran on `e12846c`, with drafter mistral-small-3.2-24b and judge llama-3.3-70b, and it was self-graded.

**What reached the model:**
- In run A (F1–F11 ×3), only 1 of 33 cases reached the model.
- In run B (P1–P5 ×3), 8 of 15 did.
- Runs C (P1 ×3) and D (dead judge ×6) reached the model.

The two full F1–F14 runs, the run-to-run variance and the cost capture were **not done**.

**Findings it recorded:**
- **Pass:**
  - Nothing leaked to the farmer before approval (57/57).
  - The released text was identical on the phone, the farmer view and the case, with no officer-only content (51/51).
  - The "Your extension officer will confirm…" line survived on every path, including Re-propose (12/12).
  - F9's bare "contact your extension officer" was rejected.
- **Fails closed:** a dead judge rejected the model SMS in 6/6 runs. The gap: the proposal-time reason was not written to `tool_log`.
- **Criterion 5 failed:** the rule-based F1 SMS dropped the AEA pesticide line in 4/4 runs.
- **Criterion 7, self-graded:** 6 of 12 judge-rejected SMS sentences were faithful, and 1 of 6 fully faithful model SMS was rejected (about 17%). There was one false accept (F4 "end of July").
- **Ejura P1:** the first attempt failed with "names RAINFALL but cites no RAINFALL passage" in 5/5 runs, and 3/5 fell back.
- **Holes it raised:**
  - the eval script didn't notice when no model call succeeded;
  - the rule SMS came out empty after a model draft (P2, P4, P5);
  - the "(MoFA) ." approval warning was spurious;
  - cost was not captured.

**What this run confirms is fixed on `a6222d1`:**
- calls are counted, and the script exits non-zero if any call fails;
- per-call cost is captured;
- the F1 safety line survives;
- the Ejura "names RAINFALL" error is gone.

This run had no approval step, so it did not re-check the "(MoFA) ." warning, the empty rule SMS or the `tool_log` gap.

## Not covered here
- No officer approval or release step ran, so criteria 1–4 (gate, leak, identical text) were not re-tested on `a6222d1`.
- QA's latest results on `8912369` cover those.
- F12 and F13 are still placeholders.
