# Live eval run 6: full officer approval path on `fb923be` (25 Oct 2026, UTC)

Raw output is in [live-eval-2026-10-25-run6-approval/](live-eval-2026-10-25-run6-approval/). It holds the driver, server wrapper, mock SMS gateway, per-case results, the sent-SMS log, a dump of the audit log (`tool_log`), the server logs and the concurrency scripts. All grades are **self-graded**.

## Setup
- **Code:** head `fb923be` (`fix/review-findings`, which merges `f6a76ae`), with the run 5 docs commit cherry-picked on top. App code is unchanged.
- **Environment:** throwaway worktree, branch `eval/live-fb923be`. The DB, outbox and media are throwaway, under `/tmp/apprun6`.
- **Servers:**
  - The real FastAPI server runs under uvicorn. Farmer questions arrive through the SMS webhook. The officer uses a throwaway token and the real `/officer/...` endpoints. The farmer view is `/farmer/cases/{id}`.
  - SMS goes to a local mock Africa's Talking gateway that records every message. The "phone" text is exactly what the app sent.
  - Main server (:18080) has the simulator on. A second server (:18082) has it off.
- **Logging:** `serve.py` wraps `service.handle_inbound` so that any exception prints its full traceback to `server.log` before it is re-raised. uvicorn runs at info level. The app swallows these exceptions into a `FAILED: <type>` row, which is why run 5 had no traceback.
- **Models:** drafter `mistralai/mistral-small-3.2-24b-instruct` and judge `meta-llama/llama-3.3-70b-instruct`, through OpenRouter at temperature 0.

| Case | Question | How the officer acts |
|---|---|---|
| F1-a | Adaklu fall armyworm, sprayed with no effect | approves as proposed |
| F1-b | same | replaces both texts with the farmer text minus its pesticide sentences (`edit_approve`, `edited_text` = farmer text) |
| F1-c | same | **acts as the officer UI does** (`ui.py`): the draft box is unchanged and sent as `edited_text`, the pesticide sentences are deleted from the farmer-text box, and the decision is `approve` |
| B1 | same question as a live case | posts the **recorded B1 officer draft** (`b1f1_draft.txt`, run 4) to `/officer/cases/{id}/farmer-draft`, then approves that proposal with `edited_text` = the recorded draft |
| S-Kintampo | "Fall armyworm is eating my maize in Kintampo. What pesticide should I spray?" | approves |
| EJ | "When should I plant maize in Ejura?" | approves |
| F5 | fertiliser arrived at knee height | approves |
| F9 | cocoa producer price | the API gate checks first, then approves |
| TWI | Twi question ("Mmoa redi me aburo wɔ Kintampo…") | writes a Twi reply; the 268/269 limit checks run first |

The Twi text is test text written for this eval. No Twi speaker or agronomist has checked it.

## Cost and calls
- **App figure:** the model_usage rows in the audit log add up to **$0.006333, 64/64 calls succeeded**.

| Part | Calls | Cost |
|---|---|---|
| Graded cases 1–9 | 30/30 | $0.004140 |
| Concurrency, F9 question (10 inbounds) | 20/20 | $0.000635 |
| Concurrency, F1 question (4 inbounds) | 14/14 | $0.001558 |

- **Key counter:** 0.053516 → 0.061111, a delta of **$0.007595**. No 402, and no call failed.
- **Gap:** $0.001262, not in the app figure. The app writes model_usage only when it creates a case. The model and judge calls made by `/officer/cases/{id}/farmer-draft` (B1 replay ×2) and by the approval-time source check (`sms_claims`) are not recorded in the audit log, so their count and cost aren't there. I verified this from the log: there is no model_usage row tied to a decision or a farmer-draft call. This likely explains part of run 5's gap too.

## Pass/fail

| # | Check | Result |
|---|---|---|
| 1 | Safety line already in the SMS in the officer queue | **Pass** (F1-a, F1-b, F1-c, B1, Kintampo). Queue SMS == proposal for all 9 |
| 2 | Phone == farmer view == recorded text, byte-identical | **Pass, 9/9** (TWI was delivered as UCS-2, 2 parts) |
| 3 | API gate | **Pass** |
| 4 | Audit log has proposal and approval entries, with rejection reasons | **Partial: the run 5 gap is still there** |
| 5 | Officer deletes the line: warning present and logged, line not re-inserted | **Pass on the UI path (F1-c)**. F1-b: no warning (see below) |
| 6 | Length within 612 GSM-7 / 268 UCS-2, sentence cut, no 400 at approval for a proposal | **Pass** |
| 7 | Order: caveat, safety line, advice | **Pass** (Adaklu ×4, Kintampo) |
| 8 | F1 safety line in the proposal in every F1 run | **Pass, 4/4** (F1-a, F1-b, F1-c, B1 live) |
| 9 | "(MoFA) ." warning / empty fallback / duplicate safety sentence | **"(MoFA) ." warning is back (EJ)**. Duplicate safety sentence 3/5. No empty fallback |
| – | Dropped sentences quoted in the officer note | **Pass**: every drop is quoted (F1-a 1, EJ 3, B1 replay 1, F1-c 1, Unicode probe 3) |
| – | B1: rule text about 505 chars, caveat → APNI line → scouting → rotation | **Pass**: 505 chars exactly; sentences below |
| – | Unicode proposal within 268 | **Pass on the limit, but over-drops** (see bugs) |
| – | Concurrency bug (run 5) | **Not reproduced**: 0 failures in 14 inbounds sent in pairs (5 F9 pairs, 2 F1 pairs), no traceback |
| – | Judge `KeyError: 'n'` (run 5) | **Not seen** in 9 approvals and 23 cases |

### 1, 2. Queue text and delivery
- Before approval:
  - each farmer view's `answer` was null;
  - each phone had only the acknowledgement.
- After approval:
  - the mock gateway text, the farmer-view answer, the case's `farmer_text` and the text sent to the API were byte-identical for all 9 cases;
  - the F1-b and F1-c edited texts were delivered exactly as edited.

### 3. API gate (on F9, live server)

| Check | Result |
|---|---|
| no token (GET and decision) | 401 |
| bad token | 401 |
| `confirmed:false` | 400 "confirm that you checked…" |
| second decision, reject and approve | 409 "case 6 is 'released', not pending_review" |
| simulator off: outbox and inbound | 404 |
| simulator on | 200 |
| officer text of 692 chars | 400, with the shorten-to-612 prompt |
| sms-check, 612 × "a" | OK, 4 parts |
| sms-check, 613 × "a" | prompt |
| sms-check, "Mɛ " × 100 | prompt: max 268, 5 parts |

On TWI, the officer-written Twi text was:
- 268 chars: Unicode, 4 parts, no prompt;
- 269 chars: prompt, "Shorten it to 268";
- approved at 269: **400**. This is by design: it's officer text, not a proposal;
- approved at 95 chars: 200, delivered as UCS-2.

### 4. Audit log
- **What is there:** the log rows are `create_or_update_case` (draft, then pending_review), `model_usage`, `inbound_message`, `officer_decision`, `release_to_farmer`, `send_answer`, and `approval_warning` (logged for every warning returned: F1-a, EJ, TWI ×2, F1-c).
- **Still missing:** there is no proposal entry. Model-SMS rejection reasons are only in the case's `farmer_draft.problems`, for example:
  - F1-a "678 characters, over 600; too long for SMS: 5 parts";
  - B1 and F1-c "830 characters…";
  - F9 "has no source behind it".
- The same is true of the dropped-sentence notes. The tool list in the dump has no farmer-text or proposal row.

### 5. Officer deletes the safety line
- **F1-c (what the UI sends): Pass.**
  - The officer text is unchanged and the farmer text has its pesticide sentences deleted. The response was 200 with the warning "approved farmer text drops the pesticide safety line: keep the officer text's line on pesticides or spraying".
  - The same warning is in the log as `approval_warning`.
  - The delivered text has no safety line and is byte-identical across all three views, so the line was **not put back**.
- **F1-b: no warning.**
  - The request sent the edited farmer text as `edited_text` too, meaning the officer draft also had no pesticide sentence. The response was 200 with `warnings: []`, and the line was not put back.
  - The new check compares the farmer text against `edited_text` (or the stored draft). An officer who deletes the pesticide sentence from both the draft and the farmer text gets no warning.
  - The UI always sends the draft box as `edited_text`, so this only happens when the officer edits the draft too. I'm reporting it as a gap, not fixing it.
  - Run 5 used the F1-b request shape. On `ccc609a` there was no such check at all.

### 6. Length

| Case | Path | Chars | Parts | Note |
|---|---|---|---|---|
| F1-a | rule | 528 | 4 | model SMS 678 rejected |
| F1-b | model | 558 | 4 | |
| F1-c | rule | 505 | 4 | |
| B1 | rule | 505 | 4 | |
| Kintampo | model | 546 | 4 | |
| EJ | rule | 574 | 4 | |
| F5 | rule | 507 | 4 | |
| F9 | rule | 14 | 1 | |

- All proposals are GSM-7 and end at a sentence boundary.
- Every proposal was approved with 200. **No proposal hit a 400 at approval.**
- Model SMS that went over the limit with the safety line were rejected for the rule path: F1-a 678; B1 and F1-c 830; the live B1 case 683. Nothing was trimmed.

### 7, 8. Order and F1
- Every Adaklu or Kintampo proposal is: zone caveat, then "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI).", then advice.
- The F1 line was in the proposal 4/4 times.

### B1 (recorded draft replayed through `/farmer-draft`, live model)
- The model rewrite was rejected (830 chars, 6 parts), so the rule path was used.
- **Result: 505 chars, GSM-7, 4 parts.** Kept, in order:
  1. "This advice comes from guides for Northern Ghana and may not suit Adaklu, so check the timing with your local extension agent."
  2. "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)."
  3. "You should scout the maize field at least once a week, looking for unusual patterns such as insect damage, larvae, or stunted growth."
  4. "You should consider rotating maize with non-host plants like groundnut, deep ploughing, and proper weeding to reduce future infestations."
- Dropped and quoted in the note: "For storage, well-dried and shelled maize should be treated with recommended storage chemicals and stored in jute sacks lined with polythene bags."
- The draft's "the officer should consult the local AEA… pesticide" sentence is not in the farmer text. Its content is carried by the word-for-word source line.
- The live B1 case (case 7) and F1-c produced the same 505-char text, both through the rule path.
- Approved with no warnings, and delivered byte-identically.

### 9. Notes
- **"(MoFA) ." spurious approval warning, EJ: present.**
  - The rule SMS this time keeps the verbatim row "…from mid July through August to early Sept. (MoFA)."
  - At approval the claim check splits after "Sept." and warns: "'(MoFA) .' is not supported by its citation … (no shared content words)".
  - It was logged as `approval_warning`. Safe, because it's a warning and doesn't block, but it is noise for the officer.
- **EJ:** caveat not applicable (Ejura is in the transition zone).
  - The "sources differ" text keeps "Your extension officer will confirm which to follow." at the end.
  - Three advice sentences were dropped and quoted: the agro-ecology sentence, "Sow after the rains have stabilized…" and "…local weather information".
- **Duplicate safety sentence: 3 of 5 pesticide proposals** (F1-a, F1-b, Kintampo). The guaranteed APNI line is followed by a second AEA/pesticide sentence in other words:
  - F1-a: "You should consult the local Agricultural Extension Agent (AEA) for advice on recommended pesticides." At approval the judge flagged this sentence as "not supported … too general" (logged).
  - F1-b: "If the worms are still a problem, talk to your local Agricultural Extension Agent about the right pesticide to use."
  - Kintampo: "If you find infestations, consult your local Agricultural Extension Agent for advice on recommended pesticides."
  - Safe, but it uses about 100 chars and, in F1-a, caused a false warning.
- **Empty fallback:** none. The Unicode probe below is the closest: caveat + safety line only, no advice.
- **F5:** the officer draft was the offline stub draft (the model draft did not pass), so the farmer text is the rule text from the stub. No problems were listed, and it was approved with no warnings.
- **F9:** the model SMS was rejected ("has no source behind it"). The farmer got "I do not know."
- **TWI:** no proposal ("the farmer wrote in twi … the officer must write it"), as designed. The officer's Twi reply also got two "has no source behind it: the case cites no passage" approval warnings.

## Bugs and gaps found (reported, not fixed)
1. **The rule path over-drops when the Unicode character is in an early sentence.**
   - Probe: the B1 recorded draft with "in Kɔforidua" added to the scouting sentence, posted to `/farmer-draft`.
   - Advice is dropped from the end until the text fits 268 UCS-2. That dropped storage, then rotation, then the scouting sentence that held the "ɔ". The result was a GSM-7 text of 233 chars: caveat + safety line, **no advice**.
   - Checked offline with `sms.measure`, keeping rotation (371 chars) or rotation + storage (518 chars, 4 parts) would have fit once the Unicode sentence was gone.
   - All 3 dropped sentences were quoted to the officer, so nothing is hidden. But the proposal loses advice it could have kept.
2. **No safety-line warning when the officer also removes the pesticide sentence from the officer draft** (F1-b shape).
3. **Proposal and rejection reasons are still not in the audit log** (run 5 item 2).
4. **Approval-time and `/farmer-draft` model calls are not in the app's cost and usage log** ($0.001262 gap this run).
5. **"(MoFA) ." spurious approval warning** on the verbatim Ejura row.
6. **Redundant duplicate safety sentence** in 3/5 pesticide proposals. In one it caused a judge "too general" warning.

**Run 5 items rechecked:**
- Concurrent inbound `ExceptionGroup` (run 5 item 3): **not reproduced** in 7 pairs, with the traceback wrapper in place and 0 `TRACE` lines in the server log. It is still open: run 5's single failure has no traceback.
- Judge `KeyError: 'n'` (run 5 item 4): **not seen**.

## False-reject rate
3/25 = 12% (self-graded, run 4) is still the documented, accepted limit. No new judge shapes were added or tested.
