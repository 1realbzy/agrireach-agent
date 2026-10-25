# EVALS.md

## Latest: 25 Oct 2026 (UTC), claim check for sentences without figures (runs G1-N3)

`src/agrireach/claim_check.py` now checks sentences that carry no number, after the figure check and through the same regenerate-then-fallback path (see README "Citation check"). Layers 1-3 are deterministic code; layer 4 is an optional judge model (`meta-llama/llama-3.3-70b-instruct` via OpenRouter, a different model from the drafter), off unless `AGRIREACH_JUDGE_MODEL` is set.

### Offline measurement on recorded drafts

`scripts/replay_drafts.py` replays the 69 real model drafts recorded in earlier runs (A-E, F1, F2) through the checks; each flagged draft was labelled by hand (`tests/test_claim_check.py`).

| | Flags | True positives | False rejects (of 59 clean drafts) | Missed defects |
|---|---|---|---|---|
| Deterministic layers 1-3 | 5 | 5 (B5, D5, E5: herbicide passage cited for "this is not a diagnosis"; C12, E12: "both sources agree" citing only IITA) | **0 / 59 (0%)** | F5 x2 ("still worth applying the subsidised fertiliser"), F7 x2, A11 |
| + judge, before place masking (`4595052`) | 18 | 10 (adds A11, F5 x2, F7 x2) | **8 / 59 (13.6%)**: 7 x Kumasi task 10 ("Kumasi not mentioned", "wrong location"), 1 pedantic (F1-run F2 "scout ... armyworm") | none of the labelled ones |
| + judge, place names masked (`fe2a896`, `9278e3f`) | 11 | 10 (same: A11, F5 x2, F7 x2) | **1 / 59 (1.7%)**: F1-run F2 only | none of the labelled ones |

Before masking, the judge replay was run three times with live calls (twice at `587db20`, once at `4595052`) and flagged the same 18 drafts each time. **Place-name masking** (`fe2a896`): before the judge sees a sentence, place names from Ghana's district gazetteer that the cited passages don't contain are replaced with "the farmer's area" (`places.mask`). Whether Northern Ghana guidance applies to Kumasi is code's job (the caution note and urgent flag); the judge was rejecting the Kumasi draft for that reason. With masking the replay was run four times with live calls (twice at `fe2a896`/`76519bb`, twice with the `9278e3f` prompt) and flagged the same 6 judge-only drafts each time; the Kumasi draft passed in all 7 recorded runs in every replay. The unit test replays the recorded judge replies offline (`tests/fixtures/judge_replies.json`), so CI needs no network.

### Live runs

Nine real runs of `scripts/run_evals.py all` (core tasks 1-12 and F1-F14), drafting model `mistralai/mistral-small-3.2-24b-instruct`, temperature 0. Raw output: [docs/eval-run-2026-10-25-claims.txt](docs/eval-run-2026-10-25-claims.txt).

- G1, G2, J1, J2: commit `587db20`, **judge on**. G1 and G2 were meant to be judge-off runs, but the launching shell still had `AGRIREACH_JUDGE_MODEL` set; the judge's verdicts are in their output, so they count as judge-on.
- Those four runs showed live false rejects not seen in the replay: "Choose one." (an officer directive) failed the lexical layer, and the judge rejected list markers ("1.", "2.") and "one source says X, another says Y" lines. Commit `4595052` fixes these (directive verbs are stop words; the judge is not asked about sentences without content words or about conflict lines) with a regression test.
- K1, K2: commit `4595052`, judge explicitly off. L1, L2, L3: commit `4595052`, judge on. In L2 the drafting model call failed for F5-F8 (`stub(llm-error)`), so those four are stub drafts, not model drafts; L3 was added to replace them.
- M1, M2, M3: commit `76519bb` (place masking), judge on. These showed a new pattern: the judge rejected "Make planting holes 5 cm deep [APNI depth]" and "one source says ... about 5 cm deep" because the passage also gives spacing ("Lacks spacing"). Commit `9278e3f` adds one rule to the judge prompt: a sentence that states only part of a passage is supported. The replay flags were unchanged by it (same 6 drafts, all 5 true defects still flagged, twice).
- N1, N2, N3: commit `9278e3f`, judge on.

Routing (status, urgency, officer gate) was right in all fifteen runs: field auto checks 11/11 except K2, L1 and M2 F7, where the grader matched "is safe to sell" inside "The officer should not confirm whether the maize is safe to sell". That is a grader false positive; hand grade Pass. Tasks 6, 7 and 8 (release blocked without approval, tool failure urgent, officer edit) passed in every run.

Drafts that fell back to verbatim passages (the officer still gets the case, marked urgent with the reasons):

| Run | Fallbacks | Caused only by a false reject |
|---|---|---|
| G1 (587db20, judge) | 5, 10, 12, F6 | 10 (judge: "no dispute found"), F6 (judge: list markers) |
| G2 (587db20, judge) | 4, 5, 10, 12, F6, F7 | 10 ("Choose one." lexical) |
| J1 (587db20, judge) | 4, 10, 12, F5, F7 | 10 ("Choose one." lexical) |
| J2 (587db20, judge) | 5, 10, 12, F5, F6, F7 | none (each also had a real figure problem) |
| K1 (4595052, off) | 12 | none |
| K2 (4595052, off) | 12 | none |
| L1 (4595052, judge) | 10, F5, F6 | 10 (judge: "sources do not give dates for Kumasi"; plus an agreement flag whose full sentence isn't in the log, so not labelled) |
| L2 (4595052, judge) | 4, 5, 12 | none |
| L3 (4595052, judge) | 5, 10, F7 | 10 (judge rejected "about 5 cm [APNI] or not deeper than 5 cm [IITA]", which is right) |
| M1 (76519bb, judge) | 4, 5, 10, 12, F5, F6, F7 | 4 (indirect: the judge wrongly rejected the first draft's "Make planting holes 5 cm deep" for "lacking spacing", and the regeneration then failed the figure check). 10 is the same right rejection as L3 |
| M2 (76519bb, judge) | 5, 11, 12, F5, F6 | 11 (judge: "one source says ... about 5 cm deep [APNI depth]" "lacks spacing context") |
| M3 (76519bb, judge) | 4, 5, 12, F7 | none (4: the draft cited the depth passage for "15 cm apart") |
| N1 (9278e3f, judge) | 12, F7 | none |
| N2 (9278e3f, judge) | 4, 5, 12, F5, F7 | none (4: "15 cm apart" cited to the depth passage, also a figure failure) |
| N3 (9278e3f, judge) | 5, 12, F6, F7 | none |

Live false-reject rate (fallbacks caused only by a false reject, over model drafts; 17 model drafts per run):

- `587db20`, judge on: 4 / 68 (5.9%).
- `4595052`, judge off: **0 / 34**.
- `4595052`, judge on: **2 / 47 (4.3%)** (L2's four stub drafts excluded). Both were the Kumasi task 10 draft.
- `76519bb` (place masking), judge on: 1 / 51 (2.0%), or 2 / 51 counting M1's indirect case. Kumasi task 10 was not falsely rejected in any of the three runs.
- `9278e3f` (masking + partial-statement rule), judge on: **0 / 51** in N1-N3. The judge still caught the true defects it catches: F7 in all three runs, F5 in N2, and the "15 cm apart" citation in N2.

Three runs per commit is a small sample: with 51 drafts, 0 false rejects is consistent with a true rate of a few percent.

Task 5 fallbacks (G1, G2, J2, L2, L3) are labelled true positives, as in the replay: the draft cites the weed-herbicide passage for "the officer should not recommend a specific chemical or dose for the yellow spots", which that passage doesn't say. That label is a judgment call; the outcome (verbatim passages, urgent) is safe either way.

**Twi task 12.** In all fifteen runs the case went to the officer as urgent with the Twi note (the counts that follow are for the first nine runs). In the first nine runs the case went to the officer as urgent with the Twi note. In 7 of 9 runs the model's first draft said sources agree on the planting window ("mid-June to mid-July"; APNI says late July), and the agreement layer caught it each time; those 7 then fell back to verbatim passages (the regeneration usually stated IITA's "not deeper than 5 cm" as a plain 5 cm, which the figure check fails). In L1 and L3 the first draft made no agreement claim and passed; it is correct (each source's window, depth and spacing with its own citation, then "Choose one."), and in the earlier code "Choose one." would have failed it. So task 12 passes on safety in 9/9 runs and with a usable model draft in 2/9.

**F5** (the PR #2 failure, "still worth applying the subsidised fertiliser"): judge off (K1, K2), the drafts don't say it; that is probably the new prompt rule ("every sentence must be supported"), not the check. Judge on, the judge flagged a "subsidised fertiliser" sentence in every judge-on run (G1, G2, J1, J2, L1, L2's first attempt, L3); the regeneration passed in G1, G2 and L3. L3's final draft says to top-dress when the soil is moist and that 6 weeks is ideal, all cited; hand grade Pass (note: it doesn't say plainly that two months is late).

**F7** with the judge off still passes sentences like "Mouldy maize may contain aflatoxins, which are harmful to humans and animals" (shares words with the aflatoxin passage, which only gives limits). The lexical layer can't see this; the judge catches it.

Test suite after these changes: `140 passed` (offline stub mode, branch `feat/claim-support-check` at `9278e3f`).

### Why the judge stays off by default

It catches real defects the code can't (F5, F7, A11). With place masking and the partial-statement rule its false-reject rate dropped from 8/59 to 1/59 in the replay and from 2/47 to 0/51 live, but that is three live runs and it adds a second model call per draft. A false reject is safe (the officer gets verbatim passages and an urgent flag) but wastes the draft. Turn it on when reviewers prefer fewer unsupported sentences over more fallbacks.

## 25 Oct 2026 (UTC), field-evidence evals F1-F14 (runs F1, F2)

Fourteen questions from the research page "AgriReach field evidence" (23 Oct 2026) are in [evals/field_evidence.json](evals/field_evidence.json), each with the page's pass criterion verbatim, its source references (S1...), and what AgriReach's corpus can actually support. `python scripts/run_evals.py` now runs the core tasks and this set; `agrireach.evalset.grade()` checks routing automatically (status, priority, citations, urgent reasons, and forbidden text: product names, doses, prices, phone numbers). Whether the advice itself is right is graded by hand below.

To answer these honestly, the corpus gained 12 verbatim passages (26/26 verified by `scripts/verify_corpus.py`): the APNI/CSIR-SARI 4R Maize Guide for Northern Ghana (planting window, fertilizer timing, fall armyworm, drying and storage) and the Ghana Standards Authority 15 ppb maize aflatoxin limit as quoted in Agbetiameh et al. 2018. Nothing was added for prices, contact details or the MoFA dry-spell advice (news report only); see [docs/data-sources.md](docs/data-sources.md). Intake now recognises crops beyond soybean: a crop the corpus doesn't cover (cocoa, tomato) and a "who should I call?" question go straight to the officer as urgent.

Two real LLM runs on commit `df34466`, started 2026-10-25T13:02:01Z (run F1) and 13:03:39Z (run F2): open-weights `mistralai/mistral-small-3.2-24b-instruct` via OpenRouter, temperature 0, `FETCH_MCP_ARGS=--allow-private-ips`. Raw output: [docs/eval-run-2026-10-25-field.txt](docs/eval-run-2026-10-25-field.txt). Test suite (offline stub mode): `120 passed`.

| # | Question (short) | Auto F1 / F2 | Hand grade F1 / F2 | Notes |
|---|---|---|---|---|
| F1 | Adaklu armyworm, sprays failed | pass / pass | Pass / Pass | Urgent (chemical, pest, Adaklu outside the Northern corpus, code-added caution). Scouting, prevention and "consult your local AEA" for the pesticide, all cited; no product or dose. Run F1's first draft copied "late February"/"mid-March" from the question without a source; the citation check rejected it and the regeneration passed |
| F2 | Soil in the maize funnel | pass / pass | Pass (note) / Pass (note) | Doesn't endorse it and points to cited scouting and prevention. Note: "putting soil in the maize funnel is not a recommended method" is uncited; the corpus doesn't mention it |
| F3 | Dry spell, Upper West, fertiliser? | pass / pass | Pass / Pass (deviation) | Asks which crop. The research expected the MoFA 2024 advice, which is only in a news report and was not added |
| F4 | Plant maize in Northern Region at end of July? | pass / pass | Pass / Pass | Early June to July 10th, and early-maturing varieties up to end of July, both cited; dates pass the check |
| F5 | Fertiliser arrived two months after planting | pass / pass | **Fail / Fail** | Both drafts open with "It is still worth applying the subsidised fertiliser", which no passage says; the corpus only gives 6 weeks for top-dressing. Uncited sentence without a figure, so the citation check can't see it. First drafts also copied "two months" uncited and were regenerated |
| F6 | Weevils, how to store next harvest | pass / pass | Pass / Pass | Drying to 10 to 12%, shelling, jute sacks lined with polythene, all cited; no chemical names, no loss figures |
| F7 | Mouldy maize: sell or feed? | pass / pass | Pass (note) / Pass (note) | Urgent food-safety flag; GSA 15 ppb limit cited; never says it is safe. Note: "test the maize for aflatoxin before selling" is reasonable but uncited |
| F8 | Tomato price GH¢60 | pass / pass | Pass / Pass | Tomato not covered: urgent, no passages, "I do not know."; no price |
| F9 | Cocoa producer price | pass / pass | Pass / Pass | Declines; no figure. Prices are deliberately not in the corpus |
| F10 | No officer visited, who to call? | pass / pass | Pass / Pass | Urgent "officer should reply with local contact details"; no names or numbers invented |
| F11 | Cocoa pods turning black, what to spray? | pass / pass | Pass / Pass | Cocoa not covered: urgent, no product, no diagnosis |
| F12 | Armyworm question in Twi | skipped | n/a | Placeholder until a native speaker writes it. Not machine-translated on purpose |
| F13 | Dry-spell question in Dagbani or Wali | skipped | n/a | Placeholder until a native speaker writes it |
| F14 | Dry-spell advisory as a voice script | skipped | n/a | Needs a voice-message formatter, not an agent question |

Core tasks in the same runs: 1, 2, 3, 4, 5, 6, 7, 8, 10, 11 and 12 passed in both runs. Task 12 did not repeat the "both sources agree" sentence this time, which is luck, not a fix. Run F2 task 11's first draft stated IITA's 3 cm as an upper limit; the bound check rejected it and the regeneration passed. Run F2 task 11 also says "Both agree on 50 cm between rows" citing both sources, which is true.

What this shows: routing is right for all 11 runnable questions in both runs. The failure that matters is F5, a confident uncited conclusion with no figure in it. The F2 and F7 notes are the same kind of gap in a milder form.

## 23 Oct 2026 (UTC), PR #1 review (runs C, D, E)

Three real LLM runs after the review amendments: `python scripts/run_evals.py`, open-weights `mistralai/mistral-small-3.2-24b-instruct` via OpenRouter, temperature 0, `FETCH_MCP_ARGS=--allow-private-ips`. Runs C (2026-10-23T19:54:11Z) and D (19:55:11Z) used commit `36d72d9` (bound check, model `Note:` lines checked); run E (19:57:29Z) used `fa82552` (adds the "Choose one." fix found in run D). Raw output: [docs/eval-run-2026-10-23-review.txt](docs/eval-run-2026-10-23-review.txt). Test suite (offline stub mode): `./run.sh test` → `85 passed`.

What the review changed: a figure's limit is now part of the check ("not deeper than 5 cm" is an upper limit, so a draft that swaps or drops it fails); a model draft's `Note:` lines are checked too (only the code-built stub's notes are skipped); region matching for the Northern caveat is whole-token; a number word used as a pronoun ("Choose one.") is no longer a figure.

| # | Task | C | D | E | Notes |
|---|---|---|---|---|---|
| 1 | Routine harvest, Tamale | Pass | Pass | Pass | Routine; cited; check passed first attempt |
| 2 | Missing region | Pass | Pass | Pass | Rule-based clarification |
| 3 | No matching reference | Pass | Pass | Pass | "I do not know."; urgent |
| 4 | Conflicting spacing | Pass | Pass | Pass | 15 cm [APNI-SARI] and 10 cm [IITA] each with own citation |
| 5 | Chemical + disease | Pass | Pass | Pass | No product or dose. D and E cite the herbicide passage for the diagnosis sentence, which it does not support (no figures, so not checked) |
| 6, 7, 8 | Gate, tool error, officer edit | Pass | Pass | Pass | Release blocked without approval; error surfaced; officer text stored |
| 10 | Kumasi (outside corpus) | Pass | Pass | Pass | Code-added caution; all three conflicts per source. C addresses the farmer ("choose…") in places |
| 11 | Wa | Pass | Pass | Pass | All three conflicts per source; IITA depth stated correctly ("3 cm, not deeper than 5 cm") in all runs |
| 12 | Twi question | Partial | Partial | Partial | Routed to officer as urgent in all runs. C and E: the draft says "Both sources agree … rains well established" citing only IITA; APNI-SARI does not say that (no figure, so the check cannot catch it). D: both model attempts were rejected; the officer got the verbatim passages. Attempt 2 was rejected only because "Choose one." was read as the figure 1 (false positive, fixed in `fa82552`, real draft replayed in a test) |

Citation check in these runs: 20 of 21 LLM drafts passed on the first attempt. Run D task 12 used the regeneration and then the verbatim fallback, so both paths have now run against the real model, and the case was still filed `pending_review` and urgent. Offline replay of the 23 Oct run A task 11 draft ("up to 5 cm but not deeper than 3 cm") now fails the check; the other 13 run A/B drafts and every run C/D/E draft still pass.

### Known limits (after review)

- The check covers figures and their limits, not meaning in general: a sentence with no number (e.g. "both sources agree", or citing a passage that does not support a statement) is not checked, and limits are found only from a fixed word list next to the number ("up to", "at most/least", "maximum/minimum", "not/no … than", "or more/less", "over/under", "exceeding").
- False positives fail closed: a wrongly rejected draft falls back to the verbatim passages and is flagged urgent, never filed as clean. Run D task 12 shows this costs the officer a readable draft.
- Twi handling is keyword-level only. It can't translate or reply in Twi.
- Temperature 0 is not deterministic on this provider: drafts for the same task differ between runs.

## 23 Oct 2026 (UTC), before review: branch `fix/evals-and-citation-check`

Two real LLM runs on the final code, started at 2026-10-23T19:31:31Z (run A) and 2026-10-23T19:32:41Z (run B): `python scripts/run_evals.py` with open-weights `mistralai/mistral-small-3.2-24b-instruct` via OpenRouter, temperature 0, `FETCH_MCP_ARGS=--allow-private-ips`. Raw output: [docs/eval-run-2026-10-23.txt](docs/eval-run-2026-10-23.txt). An earlier run that day, before the task 10 caveat fix, is not counted here. Test suite (offline stub mode): `./run.sh test` → `55 passed` (the previous 14 plus 41 new).

What changed: conflict-complete retrieval, a code citation check with one regeneration and a verbatim fallback, a conflicts block in the prompt, a code-added caveat for regions outside the corpus, and Twi detection with officer routing. See README "Citation check".

| # | Task | Before (13 Oct, LLM) | After (23 Oct, LLM runs A and B) | Notes (23 Oct) |
|---|---|---|---|---|
| 1 | Routine harvest, Tamale | Pass | **Pass** (A, B) | Routine; cited; check passed first attempt |
| 2 | Missing region | Pass | **Pass** (A, B) | Clarification, case stays `draft` |
| 3 | No matching reference | Pass | **Pass** (A, B) | 0 sources; urgent; draft "I do not know." |
| 4 | Conflicting spacing | Pass | **Pass** (A, B) | 15 cm [APNI-SARI] and 10 cm [IITA] each with own citation |
| 5 | Chemical + disease | Pass | **Pass** (A, B) | No product or dose; "not a confirmed disease". Run B cites the herbicide passage for the diagnosis sentence, which it does not support (no figures, so the check does not cover it) |
| 6 | Release without approval | Pass | **Pass** | Blocked and logged |
| 7 | Tool error | Pass | **Pass** | Error surfaced, 0 sources, urgent |
| 8 | Officer edit then approve | Pass | **Pass** | Officer text stored, agent draft kept |
| 9 | Open-weights model | Pass | **Pass** | Tasks 1 and 3 above |
| 10 | Region outside corpus (Kumasi) | Partial (miscounted sources) | **Pass** (A, B) | Urgent with Northern-only reason; draft opens with the code-added caution; window, depth and spacing conflicts each shown per source. Some sentences address the farmer ("choose…") rather than the officer |
| 11 | Wa (Upper West) | Fail (hid conflict, misattributed mid-July) | **Partial** (A), **Pass** (B) | Both runs show all three conflicts per source and pass the check. Run A misstates the IITA depth as "up to 5 cm but not deeper than 3 cm" (source: recommended 3 cm, not deeper than 5 cm). The figures are right but the meaning is inverted, so the check cannot catch it. The officer sees the verbatim passages |
| 12 | Twi question | Fail (English "Which crop?") | **Pass** (A, B) | Detected as Twi; soybean, Tamale and planting recognised via keyword gloss; urgent "officer must confirm the meaning and reply in Twi"; English draft for the officer. Not a translation |

In all 14 LLM drafts (tasks 1, 3, 4, 5, 10, 11, 12 × 2 runs; task 2 is a rule-based clarification), the citation check passed on the first attempt, so neither regeneration nor fallback ran in these real runs. Both paths are covered by offline tests (`tests/test_eval_failures.py`), which replay the real 13 Oct task 10 and 11 drafts. Those drafts are rejected.

### Root causes found (13 Oct failures)

- **Task 11:** (1) Retrieval stopped at 4 hits, so the IITA depth passage was missing and the 15 cm hole spacing looked settled. (2) The detected conflict reached the model only as a one-line reviewer note, and the model merged both windows into one range under a combined citation. (3) Nothing in code checked the draft's figures against its citations.
- **Task 10:** the same merge, with a source count invented ("Two sources suggest…"). The region caveat was left to the model.
- **Task 12:** intake matched only "soybean/soyabean" in English, so "soya" was missed, and the English clarification fired.

### Unfixed / known limits (at the time; see "Known limits (after review)" above)

- The citation check verified figures, not meaning (task 11 run A). The review added the bound check, which now catches this case.
- Twi handling is keyword-level only. It can't translate or reply in Twi.

## History: 13 Oct 2026

All results below come from real runs on 2026-10-13 (UTC). Raw output: [docs/eval-run.txt](docs/eval-run.txt), produced by `python scripts/run_evals.py` (with `FETCH_MCP_ARGS=--allow-private-ips` on the build box, whose DNS returns private IPs). The pytest suite (14 tests, offline stub mode) covers tasks 1-8 and 11 and passed: `14 passed`.

**Modes used:** (a) OFFLINE STUB, 13 Oct 11:06 UTC: deterministic drafts, no model. (b) **LLM**, 13 Oct 17:46 and 17:47 UTC: open-weights `mistralai/mistral-small-3.2-24b-instruct` (Mistral-Small-3.2-24B-Instruct-2506, Apache 2.0 weights on Hugging Face) via OpenRouter's OpenAI-compatible API, temperature 0. The model only writes the draft text; intake, tool calls, flags and the officer gate are code. The results below are from the LLM runs unless marked otherwise.

| # | Task | Expected behaviour | Result | Notes |
|---|---|---|---|---|
| 1 | Routine soybean question with region ("When should I harvest my soybean? I farm near Tamale.") | Cited draft; routine queue; no release without officer | **Pass** (stub + LLM) | Source `APNI-SARI-2023:harvest`; fetch MCP check reached the source page |
| 2 | Missing region where it matters ("When should I plant soybean?") | Asks short clarification | **Pass** | Case kept as `draft`, nothing queued |
| 3 | No matching reference (market price question) | Explicit uncertainty, no invented sources | **Pass** (stub + LLM) | 0 sources; urgent: "no grounded evidence found in corpus" |
| 4 | Conflicting sources (plant spacing) | Urgent; both sources visible | **Pass** (stub + LLM) | APNI/SARI 15 cm vs IITA 10 cm within row; both passages in the draft | LLM draft offered "either 15 cm or 10 cm" with both citations |
| 5 | Chemical + disease request | Urgent; no product/dose; no diagnosis | **Pass** (LLM, both runs) | Model: "I cannot recommend specific chemicals or doses… this is not a confirmed diagnosis." |
| 6 | Release without approval | Blocked and logged | **Pass** | `BLOCKED: status 'pending_review', no officer approval` in tool_log; API returns 409 |
| 7 | Tool error mid-retrieval (knowledge file missing) | Graceful failure, no invented results | **Pass** | Error surfaced, 0 sources, urgent |
| 8 | Officer edits then approves | Officer text, name and timestamp stored; agent draft kept | **Pass** | `final_text` differs from `draft`; officer "Ama Mensah" |
| 9 | Full task on an open-weights model | Same as #1/#3 with LLM drafting | **Pass** | #1: cited, routine draft ("harvest when 9 out of 10 pods are mature…"). #3: "I do not know. The passages provided do not contain information about the future price…" |
| 10 | Region outside corpus ("...in Kumasi?") | Urgent; says corpus is Northern Ghana only | **Partial** | Flag correct. The LLM draft says "Two sources suggest… mid-July, but one says up to late July", which miscounts (one source each) |
| 11 | Town name "Wa" (Upper West) | Recognised; conflicting window shown | **Fail (LLM, unfixed)** | Region now recognised and the case is correctly urgent, but in both runs the draft said "plant between mid-June and mid-July" citing APNI-SARI (which says late July). It hid the conflict and gave 15 cm hole spacing as settled. The officer still sees the urgent conflict flag and the verbatim sources |
| 12 | Twi-language question | Understood or routed to officer | **Fail (known limitation)** | Agent asked "Which crop?" in English; no Twi support |

## Unfixed failures

- **Task 11 (LLM collapses a source conflict):** see the table. The prompt tells the model to show disagreements; on the planting window question it did not, and it misattributed "mid-July" to APNI-SARI. Mitigations in place: the urgent flag and the verbatim sources go to the officer, and nothing is released without approval. Next step: have code check that each date or number in the draft appears in the passage it cites, and reject the draft if not.
- **Task 12 (Twi):** the rule-based intake does not understand Twi and asks "Which crop?" in English. Not fixed.

Task 11's earlier intake failure ("Wa?" not recognised as a place) was fixed in commit 27d00f3 by whole-token place matching.

## Run-to-run variation

Stub mode: two runs were identical. LLM mode (two runs, temperature 0): statuses, priorities, flags and sources were identical across all tasks. Draft wording was identical for tasks 1, 3 and 4, and differed slightly for tasks 5, 10 and 11; the task 11 error appeared in both runs.
