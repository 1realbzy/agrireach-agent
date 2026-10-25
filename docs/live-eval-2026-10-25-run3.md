# Live eval on `a5e9192`: F1–F14 twice, Ejura ×5, core tasks once (25 Oct 2026)

**Code:** `fix/review-findings` at `a5e9192`. Compared with `a6222d1` (the run2 doc), it adds:
- `34fb7de`: speech-to-text in float32;
- `ae53dc3`: the rainfall record is never a source for the farmer SMS, plus narrow judge exemptions;
- `770754a`: judge exemptions must match the whole sentence;
- `5ab7d16`: a late-timing claim layer for the F5 false accept.

**Where it ran:** the throwaway worktree `/workspace/agrireach/eval-live`, branch `eval/live-a5e9192`. Developer's branch was not touched.

**Method:** the same as run2.
- `scripts/run_evals.py field` ran twice (A1, A2), then "When should I plant maize in Ejura?" 5 times (EJB).
- One extra `scripts/run_evals.py core` run (C1) was added to look for the "3 cm… seed vigor" sentence.
- Each process used a throwaway SQLite DB.
- Models (OpenRouter, temperature 0): drafter and SMS rewriter `mistralai/mistral-small-3.2-24b-instruct`, judge `meta-llama/llama-3.3-70b-instruct`. Listed prices $0.075 / $0.20 and $0.10 / $0.32 per M tokens.
- Source-page fetch check on, live Open-Meteo rainfall.
- The key was passed by env mapping only. The wrapper stops at the first failed call, and none failed.

**Raw output:** `docs/live-eval-2026-10-25-run3/`.

**All runs are complete. None is partial.**

## Calls, tokens, cost, time (measured), against `a6222d1`

| Run | Calls succeeded / attempted | Tokens | OpenRouter cost | Wall time | Cost per question (11 agent runs, or 10 model-reached) |
|---|---|---|---|---|---|
| A1: F1–F14 | **34 / 34** (R1 was 32/32) | 25,418 (23,594) | **$0.003515** ($0.003136) | 163 s (131 s) | $0.000320, or $0.000352 ($0.000285 / $0.000314) |
| A2: F1–F14 | **38 / 38** (R2 was 32/32) | 30,122 (24,205) | **$0.004807** ($0.002855) | 132 s (145 s) | $0.000437, or $0.000481 ($0.000260 / $0.000286) |
| EJB: Ejura ×5 | **22 / 22** (22/22) | 31,573 (30,513) | **$0.004764** ($0.005011) | 185 s (284 s) | $0.000953 per run ($0.001002) |
| C1: core 1–12 | 24 / 24 | 30,661 | $0.004328 | 131 s | n/a (no `a6222d1` core run) |

**All 118 calls succeeded.** That is 86 for the like-for-like set plus 24 for core, so no task used a stub because a call failed.

**Cost:**
- Field runs cost more than on `a6222d1` because more model drafts pass and then get an SMS rewrite and an SMS judge call.
- The key's usage went from $0.011104 to $0.029011 ($0.017907). These four runs add up to $0.017414.

## Per-task outcome

**Key:**
- **✓1:** the model draft passed on the first attempt.
- **✓2:** it passed after one regeneration.
- **fallback:** the verbatim passages are shown.

All SMS are GSM-7 and within 4 parts.

| Task | A1 draft | A1 SMS | A2 draft | A2 SMS | `a6222d1` (R1 / R2) |
|---|---|---|---|---|---|
| F1 | ✓1 | model SMS **rejected by the late-timing layer** ("If the worms are **still a problem**…") → rule, 574 ch, 4 parts, safety line kept | ✓2 | model SMS rejected the same way → rule, 432 ch, 3 parts, **safety line dropped** | fallback / ✓1 |
| F2 | ✓2 | **model SMS accepted**, 331 ch, 3 parts | ✓2 | model SMS rejected by the judge ("…is not enough to stop armyworm", a true reject) → rule, 421 ch, 3 | fallback / fallback |
| F3 | clarification | none | clarification | none | same |
| F4 | fallback (auto FAIL) | rule, 581 ch, 4 | fallback (auto FAIL) | rule, 581 ch, 4 | fallback / fallback |
| F5 | **fallback** (late-timing layer, both attempts) | rule (verbatim passages), 507 ch, 4 | **fallback** (same) | rule, 507 ch, 4 | ✓1 / ✓1 with the false-accept SMS |
| F6 | fallback | rule, 537 ch, 4 | ✓2 | model SMS rejected by the judge ("as per the label instructions", borderline) → rule, 381 ch, 3 | ✓1 / fallback |
| F7 | fallback | rule, 537 ch, 4 | fallback | rule, 537 ch, 4 | fallback / fallback |
| F8–F11 | model "I do not know." | 4 model SMS rejected → "I do not know." | same | same | same |
| F14 | pass (code) | – | pass | – | pass |

**Field auto checks:** 11/12 in both runs, the same as before (F4).

**Model drafts that passed:** A1 6/10 and A2 7/10, against 6/10 and 6/10 before. Fallbacks: 4 and 3, against 4 and 4.

**Variation (A1 against A2):**
- By draft outcome, 2 of 12 tasks changed: F1 went from ✓1 to ✓2, and F6 from fallback to ✓2. Only F6 changed between model and fallback.
- At the SMS stage, F1 changed (safety line kept, then dropped) and F2 changed (model SMS accepted, then rejected).
- No task was byte-identical across the two runs the way F5 was before. F5's SMS is the same verbatim fallback both times.

**F8–F11:** the code checks rejected all 8 model SMS, as before.
- F8 echoed the GH¢60 price, and in A1 added selling advice.
- F9 was a bare "contact your extension officer".
- F10 was a district/provincial office advisory with no source.
- F11 invented doses: "every 7 days for 4 weeks", then "20 grams… 10 liters… every 14 days for 3 months".

## F5 and EJ1, the two `a6222d1` false accepts

- **F5 is fixed.** The "can still be applied / still worth applying" sentence was caught by the new late-timing layer in 4 of 4 draft attempts across the two runs, so it never reached the SMS. The SMS is now the verbatim passages (507 characters): moist soil, delay if very dry, 6 weeks. There's no claim that late application is worthwhile.
- **EJ1 is fixed.** EJB4's and EJB5's model SMS included the rainfall dates or figures ("24 of 30 days… 185.5 mm" and "Check rainfall from 2026-09-25…"). Both were rejected, because the record is no longer a source, so "2026", "185.5 mm" and the rest fail the figure check. **No final SMS in any run contains rainfall figures (0/5 Ejura).** EJB5's model SMS also invented "Always spray pesticides as needed."; the lexical layer rejected it.

## QA criterion 5: the F1 safety line

**1 of 2 runs passed.** On `a6222d1` both runs passed.
- **A1:** the rule SMS keeps "consult your local Agricultural Extension Agent (AEA) for advice on recommended fall armyworm control pesticides".
- **A2:** the proposed SMS **drops** it. The officer sees the code note "drops the pesticide safety line: keep the officer text's line on pesticides or spraying", so the gap is flagged but the proposed text is wrong. Two causes stack:
  1. **A new false reject:** the faithful model SMS ("If the worms are still a problem, talk to your local Agriculture Extension Agent…") was rejected by `LATE_CLAIM_RE`. Its `(?:is|are)\s+still\b` part matches "are still a problem", which is not a late-timing claim. The same thing happened in A1, where the rule text happened to keep the line.
  2. **An older rule-rewrite bug** (it is the same on `d1685de`): `farmer_reply.ALLOWED_OFFICER` accepts "Agricultural Extension Agent" and "local AEA" but not "**Agriculture** Extension Agent (AEA)". So `OFFICER_RE` treats the safety sentence as an officer instruction and drops it. I reproduced this offline: "Agricultural…" is kept, "Agriculture…" is dropped.

Twi and Dagbani are still untested (F12 and F13 are placeholders).

## QA criterion 7: false rejects (**self-graded**)

These grades are mine, the authors', not an independent review. I used the same rule as run2: a fallback counts as "only false rejects" when every problem on the final attempt is a faithful sentence.

**Cases:** 25 model-drafted cases (A1 10, A2 10, EJB 5), 10 fallbacks.
- **3 fell back only because of false rejects:**
  - A1 F4: "Sources give different figures for the maize planting window." The judge said "No conflicting figures", but the sources do conflict.
  - EJB2: "Use this data… but note that this is a model estimate…". The record itself says it is a model estimate.
  - EJB3: "A rainfall record is attached for your reference."
- 1 was borderline: A1 F6, the "weevils… dried and shelled" citation.
- 6 were justified: A1 F5, A1 F7, A2 F4, A2 F5, A2 F7, EJB1.

That is **3/25 = 12%, self-graded**, down from 5/25 = 20% on `a6222d1`. Regeneration also rescued 5 cases whose first attempt failed only on a false reject: A2 F1, F2 ×2, A2 F6 and EJB4.

**Draft-check judge rejections:** 23 sentences.
- **11 false:**
  - "Sources give different figures…" ×3;
  - "A rainfall record is attached…" ×3 (EJB2, EJB3, EJB4);
  - "Use this data… model estimate";
  - "Choose the appropriate window based on local conditions **and weather information**" (EJB1; the shape only allows "based on local conditions");
  - A2 F1 "If the infestation persists despite pesticide application, consult your AEA…";
  - A2 F6 "The officer should inspect the maize **for signs of infestation** or refer to a specialist…";
  - A2 F7 "Do not know if the maize is safe to sell or feed."
- **4 borderline:** A1 F6 ×2, A1 F7 "Do not confirm whether the maize exceeds these limits", A2 F5 "ideal time 6 weeks, but the maize is now two months (8 weeks) old".
- **8 true:** "do not sell or feed" ×2, aflatoxin harm, "likely to exceed", EU/FDA "lower limits", "test for aflatoxin", "knee-high so about 6 weeks", plus F4 "Better yields" with a mis-citation.

**SMS-check judge:** 7 model SMS were judged. Model SMS final outcomes:
- 1 accepted: A1 F2, which is faithful.
- 2 **falsely rejected by the late-timing layer**: F1 in A1 and A2 (above).
- 1 borderline: A2 F6.
- 3 rejected correctly: A2 F2 overstates; EJB4 and EJB5 carry rainfall figures and an invented spray line.
- **No SMS false accept was found.**

## Effects of the whole-sentence exemption change

**New false rejects** (sentences that used to be exempt and are now judged, then rejected):
- **"Choose which planting window / planting depth / plant spacing to follow."** (core task 11, Wa). The judge rejected each with "No choice". The officer-choice shape needs "The officer should…", so the bare imperative is judged.
- **"- \*\*Planting Window:\*\* Sources disagree."** and the same for depth and spacing (core task 12, Twi), 6 verdicts. The judge said "Sources do not disagree", which is wrong because they do. A bold heading followed by a colon doesn't fit `_TOPIC`.
- The heading "\*\*Soybean Planting Advice for Tamale\*\*" (task 12) is also judged and rejected.
- "Choose the appropriate window based on local conditions and weather information." (EJB1), and A2 F6's "inspect the maize for signs of infestation or refer to a specialist…", are both slightly longer than their shapes.
- Tasks 11 and 12 fell back for other reasons too (wrong-passage figures and unshown conflicts). These rejections add noise, but they weren't the only reason.

**"3 cm… seed vigor":** the model didn't write that sentence in C1. The depth sentences it did write ("…or avoid deeper sowing (recommended depth = 3 cm; not deeper than 5 cm)", and "[IITA] says to plant 3 cm deep, not deeper than 5 cm") were judged and **supported**. So I have no live evidence either way for the seed-vigor sentence.

**Plain "don't know" lines:** these are now judged unless they fit the shape.
- **One was falsely rejected by the judge:** A2 F7 "Do not know if the maize is safe to sell or feed." It has no subject, so it falls outside the "we/I do not know…" shape, and the judge said "Passage silent".
- **Two were rejected by the lexical layer, not the judge,** both before and after this change:
  - core task 5: "I do not know which chemical to use." (both attempts, "no shared content words");
  - F2: "The passages do not mention this method." (A1 and A2, first attempt).
- **No bare "We do not know." appeared in any draft.**
- The F8–F11 "I do not know." drafts cite nothing, so they made no judge call and passed in both runs.

**New false accepts from the narrower exemptions:** none found. I re-read every model draft that passed and every accepted model SMS: A1 F1 and F2, A2 F1, F2 and F6, EJB4 and EJB5, and A1 F2's SMS. Each claim is in its cited passage. The exceptions are A2 F6's added "as per the label instructions" (borderline, and the SMS judge rejected it) and A2 F1's off-topic storage line, which is supported.

## Ejura planting, before and after

| | `e12846c` (before `d1685de`) | `a6222d1` | `a5e9192` |
|---|---|---|---|
| Passed first attempt | 0 | 2 | **1** (EJB5) |
| Passed after regeneration | 2 | 1 | **1** (EJB4) |
| Verbatim fallback | 3 | 2 | **3** (EJB1–3) |
| "names RAINFALL but cites no RAINFALL passage" | 5/5 first attempts | 0/8 attempts | 0/9 attempts |
| Rainfall figures in the final SMS | (not measured) | 1/5 (EJ1) | **0/5** |

**Why the fallbacks happened:**
- EJB1: the second attempt cited windows to the wrong passages, a true reject.
- EJB2 and EJB3: only false rejects of sentences about the attached rainfall record.

"A rainfall record is attached…" is now the most common false reject: 4 of 5 Ejura runs, plus core task 11. It is not one of the exempt shapes.

**Cosmetic:** EJB4 and EJB5's rule SMS keep the draft's bold-heading labels as text ("Planting Window: The major season transition period…", "Local Weather Information: …") with double spaces where citations were removed.

## Not covered
- No approval or release step ran, so criteria 1–4, the "(MoFA) ." split warning, the empty fallback and the audit-log gap were not re-tested.
- Five runs per Ejura sample and two per field task are small samples.
