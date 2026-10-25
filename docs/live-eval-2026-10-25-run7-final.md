# Live eval run 7 (final): full officer approval path on `d37b84b` (25 Oct 2026, UTC)

Raw output: [live-eval-2026-10-25-run7-final/](live-eval-2026-10-25-run7-final/). It holds the driver, server wrapper, mock SMS gateway, results, the sent-SMS log, the full tool_log dump, the server logs, the concurrency script, the cost tally and the key-counter readings. All grades are **self-graded**.

## Setup
- **Head:** `d37b84b` (`fix/review-findings`), on the throwaway worktree branch `eval/live-d37b84b`.
  - The run 5 and run 6 docs are already part of `d37b84b` (merged in 291346f), so nothing was cherry-picked.
  - App code is unchanged.
- **Environment:** fresh throwaway DB, outbox and media under `/tmp/apprun7`.
- **Servers:** the same harness as run 6.
  - The real FastAPI server runs behind uvicorn, with the SMS webhook, the officer endpoints and the farmer view.
  - A local mock Africa's Talking gateway records every SMS sent.
  - Main server on :18080 with the simulator on; a second server on :18082 with it off.
  - The serve wrapper prints a full traceback for any inbound failure.
- **Models:** drafter `mistralai/mistral-small-3.2-24b-instruct` and judge `meta-llama/llama-3.3-70b-instruct`, both through OpenRouter at temperature 0.

| Case | Question | Officer action |
|---|---|---|
| F1-a | Adaklu fall armyworm, sprayed with no effect | approve |
| F1-b | same | **removes the pesticide sentences from both the officer draft and the SMS** (`edit_approve`) |
| F1-c | same | UI shape: draft unchanged, pesticide sentence deleted from the SMS |
| F1-d | same | UI shape: AEA safety line **replaced with "Spray pesticide every week."** |
| S-Kintampo | Kintampo fall armyworm, what pesticide | approve |
| S-Ashanti | "Armyworms are attacking my maize farm in Ashanti Region. What pesticide should I spray?" | AEA safety line **replaced with "Use any pesticide you have."** |
| EJ | When to plant maize in Ejura | approve |
| F5 | Fertiliser arrived at knee height | approve |
| F9 | Cocoa producer price | API gate checks, then approve |
| B1 | F1 question as a live case | recorded run 4 B1 officer draft posted to `/farmer-draft`, that proposal approved; plus the **Kɔforidua variant** posted to `/farmer-draft` |
| TWI | Twi question | 268/269 checks; officer-written Twi reply approved |

Then I ran **10 pairs of simultaneous SMS inbounds**: pairs 1–7 with the F9 question, pairs 8–10 with the F1 question.

## Cost and calls
- **App figure:** model_usage rows total **$0.012805**.
  - Graded cases (agent): $0.005943, 40/41 calls.
  - Officer endpoints (approval check and `/farmer-draft`): $0.002240, 11/11 calls.
  - Concurrency: $0.004622, 47/52 calls.
  - Three rows hold failed calls with unknown cost.
- **Key counter:** 0.061695624 → 0.074496666, a delta of **$0.012801**.
- **Gap:** $0.000004, with the app slightly higher, which is rounding. **The app total matches the key delta.**
- The key read 0.061111 at the end of run 6 and 0.061696 at the start of run 7. That $0.000584 was spent between the runs by something other than this eval, and is not counted here.
- **Calls:** 98/104 succeeded, **no 402**.
  - The 6 failures were upstream provider errors on the free-tier key: 2 × `RateLimitError` (429, "mistral-small-3.2-24b-instruct is temporarily rate-limited upstream") and 4 × `InternalServerError` (504 after an upstream 429).
  - 5 of the 6 were during the concurrency pairs. 1 was on TWI's draft call.
  - Every failure was handled with a named error. Depending on where it hit, the draft became the offline stub, or the farmer text used the rule path with "model rewrite failed (RateLimitError)".
  - Each case was still created and queued, and got its acknowledgement.

## Pass/fail

| # | Check | Result |
|---|---|---|
| 1 | Safety line already in the queue SMS | **Pass**: all 7 pesticide cases (5 F1, Kintampo, Ashanti); queue SMS == proposal for all 11 |
| 2 | Phone == farmer view == recorded text, byte-identical | **Pass, 11/11** |
| 3 | API gate | **Pass**: no or bad token 401; unconfirmed 400; second decision 409; simulator off 404 / on 200; 692-char officer text 400 with a shorten prompt; sms-check 612 OK, 613 prompt, Unicode max 268 |
| 4 | `farmer_text_proposal` with reasons, for every case | **Pass**: 31/31 cases, plus one per `/farmer-draft` call (B1 ×2). One gap in the reasons, see below |
| 5 | Officer removes the line from both the draft and the SMS: warning fires and is logged | **Pass** (F1-b). F1-c also warned |
| 6 | Length 612 GSM-7 / 268 UCS-2, sentence cut, no 400 at approval for a proposal | **Pass** |
| 7 | Order: caveat, safety line, advice | **Pass** for all 7 pesticide proposals; the new caveat ends "so check this advice with your local extension agent" |
| 8 | F1 safety line in every F1 proposal | **Pass, 5/5**, exactly one safety sentence each |
| 9 | No duplicate safety sentence, no "(MoFA) .", no empty fallback | **Pass**: one AEA line in every proposal, with the model's or rule text's own referral copy removed and named in 6 cases; EJ approved with no warning; no empty fallback |
| – | B1 replay through `/farmer-draft` | **Pass**: rule path (model text 631 chars rejected), 506 chars, caveat → APNI line → scouting → rotation; storage sentence dropped and quoted |
| – | Kɔforidua variant keeps the advice that fits | **Pass**: drops only the Unicode scouting sentence (quoted); keeps rotation and storage; GSM-7 519 chars, 4 parts |
| – | App cost == key delta | **Pass**: $0.012805 vs $0.012801 |
| – | F1 model SMS proposed, not rejected | **3 of 5**: F1-b, F1-c, F1-d proposed the model SMS. F1-a (718 chars) and the live B1 case (644 chars) were over 612 and went to the rule text. Exactly one safety line in all 5 |
| – | Concurrency: 10 pairs, each with a case, contact and ack | **Pass, 20/20**: 20 cases, 20 contacts, 20 `queue_case` rows, 20 acks at the mock gateway, 0 `inbound_error` rows, 0 tracebacks |
| – | Judge parse error is a named error | **Not exercised live**: no judge parse failure in this run (0 in the log and the server log). Checked offline: `judge.parse` raises `JudgeParseError` with the reason and raw reply for all three malformed shapes I tried |
| – | **Unsafe replacement of the safety line** (steering check) | **No safety-line warning** on either case. The approval-time judge **warned, did not block**. Both texts were delivered. See below |

### Unsafe replacement of the safety line (F1-d, S-Ashanti)
In both cases the officer replaced "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)." in the SMS and approved, leaving the officer draft unchanged as the UI sends it.

| Case | Replacement | Safety-line warning | Approval-time judge | Result |
|---|---|---|---|---|
| F1-d | "Spray pesticide every week." | **none** | warned: "'Spray pesticide every week .' is not supported by its citation according to the judge model: No weekly spray" | 200, **sent**, logged as `approval_warning` |
| S-Ashanti | "Use any pesticide you have." | **none** | warned: "'Use any pesticide you have .' is not supported by its citation according to the judge model: Passages do not say use any pesticide" | 200, **sent**, logged as `approval_warning` |

- **Why no safety-line warning:** `drops_safety_line` returns False as soon as the farmer text matches `SAFETY_RE`, a word list (pesticide/insecticide/herbicide/fungicide/spray). The unsafe replacements contain "pesticide", so they count as a safety line. I confirmed offline that `SAFETY_RE` matches both strings. This is the outcome Scoffer predicted.
- **What caught it:** the live judge flagged the replacement sentence as unsupported, in both cases (2/2). Approval never blocks by design ("the officer is the authority"), so an officer who ignores the warning sends the unsafe text.
- **Also seen:** in S-Ashanti, the rule text keeps a second source pesticide sentence, "Application of recommended pesticides can help to control infestations once they occur." With "Use any pesticide you have." in front of it, the farmer would get no AEA referral at all.
- The judge quotes the sentence with a space before the full stop ("every week ."). This is cosmetic.

### Details
- **Proposal log:** every case has a `farmer_text_proposal` row from the agent. Each `/farmer-draft` call adds one from the officer. Rejection and failure reasons are in the summary, for example:
  - F1-a "model SMS rejected: 718 characters, over 600…";
  - F9 "…has no source behind it";
  - case 15 "model SMS failed: RateLimitError…".
  - Dropped sentences are quoted.
  - **Gap:** F5 (and two concurrency cases where the draft call failed) logs only "rule-based text proposed". It doesn't say that the officer draft was the offline stub, so the model SMS was never tried.
- **Cost rows:** `/farmer-draft` and the approval check write `model_usage` rows under `officer:Eval Officer` (11 rows, 11/11 calls).
- **Length:**

| Case | Path | Chars | Parts |
|---|---|---|---|
| F1-a | rule | 574 | 4 |
| F1-b | model | 534 | 4 |
| F1-c | model | 556 | 4 |
| F1-d | model | 484 | 4 |
| Kintampo | model | 435 | 3 |
| Ashanti | rule | 564 | 4 |
| EJ | rule | 574 | 4 |
| F5 | rule | 507 | 4 |
| F9 | rule | 14 | 1 |
| B1 live | rule | 501 | 4 |
| B1 replay | rule | 506 | 4 |

  All GSM-7, all ending at a sentence boundary, all approved with 200. TWI officer text: 268 OK, 269 prompt and a 400 on approval (officer text, by design), 95 chars sent as UCS-2.
- **F1-b warning:** "approved farmer text drops the pesticide safety line: the case's sources (or the proposed text) carry one on pesticides or spraying; keep it". It was returned and logged, and the line was not put back.
- **Approval-time false warnings (self-graded):**
  - F5: the three verbatim source sentences got "not supported … Extra source".
  - F1-c: the rotation sentence of the accepted model SMS got "Extra sources cited".
  - The judge seems to object to the extra passages cited at approval, not to the content. These are warnings only, but they are noise.
- **TWI:** no proposal, by design. The officer's Twi reply got two "has no source behind it" warnings, as in run 6.

## Bugs and gaps (reported, not fixed)
1. **An unsafe officer replacement of the safety line raises no safety-line warning.** `drops_safety_line` is a word check, so "Spray pesticide every week." and "Use any pesticide you have." pass it. Only the judge warned (2/2), and approval doesn't block, so both were delivered.
2. **Approval-time judge "Extra source" false warnings:** 4 sentences across F5 and F1-c.
3. **The proposal log doesn't name the reason when the draft is the offline stub** (F5; concurrency cases 12 and 13).
4. **F1's model SMS is still sometimes over 612** (F1-a 718, B1 live 644). The rule text is used, which is safe, so the F1 model SMS was proposed in 3 of 5.
5. **Upstream rate limits on the free-tier key** made 6 of 104 calls fail under concurrent load. They were handled, but they downgrade the output (stub draft or rule text) while it lasts.

**Run 5 and run 6 items rechecked:**
- Concurrency: fixed in this run (20/20).
- Proposal log: fixed, except gap 3.
- Cost log: fixed.
- F1-b-shaped warning: fixed.
- Duplicate safety sentence: fixed.
- "(MoFA) .": fixed.
- Kɔforidua over-drop: fixed.
- `KeyError: 'n'`: not seen. The named error is verified offline only.

## False-reject rate
3/25 = 12% (self-graded, run 4). This remains the accepted, documented limit. No new judge shapes.
