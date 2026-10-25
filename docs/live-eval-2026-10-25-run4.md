# Live eval on `cc7cf4c`: F1–F14 twice, Ejura ×5, core tasks once (25 Oct 2026)

**Code:** `fix/review-findings` at `cc7cf4c`. Compared with `a5e9192` (the run3 doc), it adds:
- `2138f93`: the late-timing layer ignores "are still a problem", and the rule rewrite keeps "Agriculture Extension Agent (AEA)";
- `e2bd7bb`: whole-sentence shapes for the run3 false rejects (heading prefix, bare "choose which…", "Do not know if…", the rainfall-record note, inspect/refer detail);
- `bd7105f`: "still have time" and "it is not late to…" count as late-timing claims.

**Where it ran:** the throwaway worktree `/workspace/agrireach/eval-live`, branch `eval/live-cc7cf4c`. Developer's branch was not touched.

**Method:** the same as run2 and run3.
- `run_evals.py field` ran twice (B1, B2), then "When should I plant maize in Ejura?" 5 times (EJC), then `run_evals.py core` once (C2).
- Each process used a throwaway DB.
- Models (OpenRouter, temperature 0): drafter and SMS rewriter `mistralai/mistral-small-3.2-24b-instruct`, judge `meta-llama/llama-3.3-70b-instruct`.
- The key was passed by env mapping only. The wrapper stops at the first failed call, and none failed.

**Raw output:** `docs/live-eval-2026-10-25-run4/`.

**All runs are complete. None is partial.**

## Calls, cost, time (measured), against `a5e9192`

| Run | Calls succeeded / attempted | Tokens | OpenRouter cost | Wall time | Per question (11 agent runs, or 10 model-reached) |
|---|---|---|---|---|---|
| B1: F1–F14 | **33 / 33** (A1 34/34) | 24,202 (25,418) | **$0.003119** ($0.003515) | 165 s (163 s) | $0.000284, or $0.000312 ($0.000320 / $0.000352) |
| B2: F1–F14 | **36 / 36** (A2 38/38) | 26,915 (30,122) | **$0.003824** ($0.004807) | 151 s (132 s) | $0.000348, or $0.000382 ($0.000437 / $0.000481) |
| EJC: Ejura ×5 | **22 / 22** (22/22) | 32,781 (31,573) | **$0.005186** ($0.004764) | 347 s (185 s) | $0.001037 per run ($0.000953) |
| C2: core 1–12 | 28 / 28 (C1 24/24) | – | $0.004275 ($0.004328) | 162 s (131 s) | – |

**All 119 calls succeeded.** That is 91 for the like-for-like set plus 28 for core, so no task used a stub because a call failed.

**Other measurements:**
- The key's usage went from $0.029011 to $0.041139 over B1, B2 and EJC. That $0.012128 matches their summed reported cost of $0.012129.
- EJC's first run took 125 s on its own, which explains most of EJC's longer wall time.

## Per-task outcome

**Key:**
- **✓1:** the model draft passed on the first attempt.
- **✓2:** it passed after one regeneration.
- **fallback:** the verbatim passages are shown.

All SMS are GSM-7 and within 4 parts.

| Task | B1 draft | B1 SMS | B2 draft | B2 SMS | `a5e9192` (A1 / A2 draft) |
|---|---|---|---|---|---|
| F1 | ✓1 | model SMS rejected for length (723 ch, over 600) → rule, 545 ch, 4 parts, **safety line dropped** (the officer gets the "drops the pesticide safety line" note) | ✓2 | **model SMS accepted**, 502 ch, 4 parts, safety line kept | ✓1 / ✓2 |
| F2 | ✓2 | model SMS rejected by the judge ("…is not enough to stop armyworm", a true reject) → rule, 427 ch, 3 | ✓2 | **model SMS accepted**, 319 ch, 3 | ✓2 / ✓2 |
| F3 | clarification | none | clarification | none | same |
| F4 | fallback (auto FAIL) | rule, 581 ch, 4 | fallback (auto FAIL) | rule, 581 ch, 4 | fallback / fallback |
| F5 | fallback (late-timing layer, both attempts) | rule (verbatim passages), 507 ch, 4 | fallback (same) | rule, 507 ch, 4 | fallback / fallback |
| F6 | **✓1** | model SMS rejected by the judge (**false**: "Use recommended storage chemicals and store… jute sacks lined with polythene bags", which is the p22-sacks passage) → rule, 304 ch, 2 | **✓1** | **model SMS accepted**, 211 ch, 2 | fallback / ✓2 |
| F7 | fallback | rule, 537 ch, 4 | fallback | rule, 537 ch, 4 | fallback / fallback |
| F8–F11 | model "I do not know." | 4 model SMS rejected → "I do not know." | same | same (F9's "I do not know the cocoa producer price this season." was also rejected, because a case with no passages rejects every sentence) | same |
| F14 | pass (code) | – | pass | – | pass |

**Field auto checks:** 11/12 in both runs (F4), the same as before.

**Model drafts that passed:** 7/10 in both runs (A1 6/10, A2 7/10). There were 3 fallbacks per run: F4, F5, F7.

**Variation (B1 against B2):**
- By draft outcome, 1 of 12 tasks changed: F1 went from ✓1 to ✓2. No task moved between model and fallback (before it was 2/12, then 1/12).
- At the SMS stage, F1, F2 and F6 differed. The B2 model SMS was accepted in all three, while B1 used the rule text.

**F8–F11:** all 8 model SMS were rejected, as before. F8 echoed the GH¢60 price and gave selling advice. F11 invented doses: "every 2-3 weeks", then "20 grams… 10 liters… every 14 days".

## Key question: the F1 safety line

**It was kept in 1 of 2 runs, not both.**
- **B2:** the accepted model SMS keeps "If the worms are still a problem, talk to your local Agriculture Extension Agent about the right pesticide to use." This confirms the run3 false positive is fixed: "are still a problem" is no longer flagged as late timing.
- **B1:** the proposed SMS drops the line. The officer sees "drops the pesticide safety line: keep the officer text's line on pesticides or spraying". This was a new cause, separate from both run3 causes:
  1. The B1 draft wrote the referral as an officer instruction: "If the infestation is severe and the recommended chemicals have not worked, **the officer should consult** the local Agricultural Extension Agent (AEA) for advice on the recommended fall army worm control pesticide in the area".
  2. The model SMS kept the line, but it was 723 characters, so it was rejected for length.
  3. The rule rewrite then dropped the sentence as an officer instruction. `OFFICER_RE` matches "the officer", and `_OPENERS` only rewrites "the officer should advise/tell the farmer…" forms, not "the officer should consult…". I reproduced this offline.
- **Possible fixes:**
  - let the rule rewrite keep or convert a `SAFETY_RE` sentence even when it is officer-addressed ("the officer should consult the local AEA" becomes "Consult your local AEA");
  - or put the SAFETY sentence first and trim the other sentences when the model SMS is too long.

Twi and Dagbani are still untested.

## F5 and EJ1 are still fixed

- **F5:** the "can still be applied, but only if the soil is moist" sentence was rejected by the late-timing layer in **4 of 4** draft attempts. The SMS is the verbatim passages.
- **Ejura rainfall figures:** **0 of 5** final SMS contain rainfall figures. No EJC model SMS carried them this time. Two EJC drafts did write the dates and figures uncited ("A rainfall record is provided for Ejura from 2026-09-25 to 2026-10-24…"), and the figure check rejected them.

## Late-timing flags (all runs)

There were **6 flags, all true:**
- F4 "You can still plant maize in the Northern Region at the end of July, but only if you use…" ×2: the cited passage doesn't speak about late timing.
- F5 "can still be applied" ×4.

**0 false flags.** The F1 model SMS in B2 ("worms are still a problem") was not flagged. No draft or SMS used "you still have time", "there is still time" or "it is not late to…", so that new wording has no live test yet.

## Ejura planting, before and after

| | `e12846c` | `a6222d1` | `a5e9192` | `cc7cf4c` |
|---|---|---|---|---|
| Passed first attempt | 0 | 2 | 1 | **1** (EJC1) |
| Passed after regeneration | 2 | 1 | 1 | **1** (EJC3) |
| Verbatim fallback | 3 | 2 | 3 | **3** (EJC2, 4, 5) |
| Rainfall figures in final SMS | – | 1/5 | 0/5 | **0/5** |

**Why the fallbacks happened:**
- **EJC2:** the second attempt cited windows to the wrong passages, a true reject.
- **EJC4:** only false rejects: "However, this is a model estimate and may differ from local conditions." and "This is a model estimate and may differ from local conditions.". The new "this is a model estimate" shape doesn't allow the "and may differ…" tail, though the record itself says estimates can differ.
- **EJC5:** the second attempt failed only on "Choose the window that best fits your local conditions." This isn't a shape, and I grade it a false reject.

**What the new shapes now handle:** "A rainfall record is attached for the officer's reference [RAINFALL-…]." passed in EJC1 without a judge rejection (it was rejected 4 times in run3).

**EJC3:** the SMS judge reply couldn't be parsed (`KeyError: 'n'`), so the model SMS was rejected (fails closed, correct). That SMS also invented "Use pesticides as needed.", which the lexical layer rejected.

## QA criterion 7: false rejects (**self-graded**)

Same rule as before: a fallback counts as "only false rejects" when every problem on the final attempt is a faithful sentence.

**Cases:** 25 model-drafted cases (B1 10, B2 10, EJC 5), 9 fallbacks.
- **3 fell back only because of false rejects:**
  - B1 F4: "Sources give different figures for the maize planting window." The judge said "No comparison" or "Only one figure", but the sources do differ.
  - EJC4: the "model estimate… may differ" lines.
  - EJC5: "Choose the window that best fits your local conditions."
- 6 were justified: B2 F4, F5 ×2, F7 ×2, EJC2.

That is **3/25 = 12%, self-graded**, the same as on `a5e9192`. The cases are different, though: B1 F4 is the same pattern as A1 F4, and the Ejura cases are new variants that sit just outside the new shapes.

**Draft-check judge rejections:** 21 verdicts.
- **14 false:**
  - "Sources give different figures for (the) maize planting window" ×3;
  - B2 F1 "If the infestation persists despite pesticide application, consult your local AEA…" (the farmer's own situation);
  - B2 F7 "Do not know if the maize **can be sold or fed to animals**." The shape allows one word after "or", and "fed to animals" is three;
  - EJC2 "Choose the appropriate window based on local conditions and weather information.";
  - EJC3 and EJC5 "Choose the window that best fits your local conditions." ×4;
  - EJC3 and EJC5 "The officer should decide if the recorded rainfall meets the planting conditions." ×2. The same sentence was judged supported on EJC3's second attempt;
  - EJC4 "model estimate" ×2.
- **2 borderline:** B1 F7 "The officer should check if the mouldy maize exceeds this limit." and "If it does, the maize should not be sold or fed to animals."
- **5 true:** "Do not sell or feed the mouldy maize." ×2, "advise the farmer to dispose of the mouldy maize safely" ×2, and F4 "Better yields" with a mis-citation.

**SMS stage:**
- Faithful model SMS that were rejected: B1 F6 (judge), B2 F9 (no-passage rule) and B1 F1 (length; correct under the 600-character rule).
- Accepted: B2 F1, F2, F6 and EJC1, all faithful.
- **No SMS false accept was found.** One wording nit: EJC1 says "Alternatively, sow after the rains have stabilized". The sources give it as a condition, not an alternative, so it's borderline.

## Effects of the new shapes

**Now passing (sentences rejected in run3):**
- "Inspect the maize for signs of infestation or refer to a specialist if unsure." (B1 F6): no judge rejection, and F6 passed first time in both runs.
- "A rainfall record is attached for the officer's reference." (EJC1).
- Core task 11 (Wa) and task 12 (Twi) now give model drafts that pass, ✓1 and ✓2. Both fell back in C1.

**Still rejected, or new false rejects next to the shapes:**
- "Do not know if the maize can be sold or fed to animals." (B2 F7, judge).
- "Choose the window that best fits your local conditions." ×4 and "Choose the appropriate window based on local conditions and weather information." (Ejura).
- "…this is a model estimate and may differ from local conditions." ×2 (EJC4).
- Core task 5, lexical layer: "The officer should inspect the leaves or refer the farmer to an expert for a diagnosis." fails "no shared content words". The shape keeps the sentence away from the judge, but not away from the word-overlap check.
- Core task 5, also lexical: "I do not know which chemical to use." (both attempts, unchanged).
- Core task 12: "Choose the depth that aligns with your experience." and "Choose the spacing that works best for your farmers." were judged and rejected. I grade both borderline, because they add a basis for the choice that no source gives.
- **Core SMS stage:** option sentences were rejected as "contradictory sources" or "Sources disagree": task 4 "Choose either 15 cm or 10 cm between plants in a row", and the task 10 and task 11 spacing options. I grade these as false rejects of correctly presented alternatives. The confirm line is added in code.

**Bold headings:** no "**Heading:** Sources disagree." line occurred in this run, so the heading shape has no live test yet.

**"3 cm… seed vigor":** it didn't occur in C2 either.

**New false accepts from the new shapes:** none found. I re-read every passing model draft (B1 F1, F2, F6; B2 F1, F2, F6; EJC1, EJC3) and every accepted model SMS.

## Not covered
- No approval or release step ran, so criteria 1–4, the "(MoFA) ." split warning, the empty fallback and the audit-log gap were not re-tested.
- Two runs per field task and five per Ejura are small samples.
