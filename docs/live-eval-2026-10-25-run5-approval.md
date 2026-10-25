# Live eval run 5: full officer approval path on `ccc609a` (25 Oct 2026, UTC)

Raw output: [live-eval-2026-10-25-run5-approval/](live-eval-2026-10-25-run5-approval/). The folder holds the driver, server wrapper, mock SMS gateway, results, the sent-SMS log, the tool_log dumps and the first-attempt evidence. All grades are **self-graded**.

## Setup
- Head is `ccc609a` (merge of fix/sms-safety-guarantee). It runs from a throwaway worktree with a throwaway SQLite DB, outbox and media under `/tmp/apprun`. No app code was changed.
- The real FastAPI server runs under uvicorn with the real HTTP API.
  - The SMS inbound webhook is `/channels/sms/inbound/{token}`, with a fake local token.
  - The officer endpoints use a throwaway officer token made with `db.add_officer`.
  - Farmer view is `/farmer/...`.
- `sms.SANDBOX_BASE` is patched in the wrapper (`serve.py`) to a local mock Africa's Talking gateway (`mock_at.py`, :18081). The mock records every POST, so the "phone" text is exactly what the app sent to the gateway.
- Two servers:
  - main (:18080): simulator on, SMS on;
  - off (:18082): simulator off, used only for the 404 check.
- Models: drafter `mistralai/mistral-small-3.2-24b-instruct`, judge `meta-llama/llama-3.3-70b-instruct`, both via OpenRouter at temperature 0.
- Cases, all sent as farmer SMS through the webhook:

| Label | Question (short) | Notes |
|---|---|---|
| F1-a | Adaklu, fall armyworm in maize | approved as proposed |
| F1-b | same question, second run | **officer edit deletes the safety sentence**, then approve |
| S-Kintampo | Kintampo (Ashanti side), fall armyworm | southern pesticide case |
| EJ | Ejura, when to plant maize | |
| F5 | maize top-dressing timing | |
| F9 | cocoa producer price this season | don't-know case; also used for the API gate checks |

## Cost and calls
- **Second attempt (the graded run): 28/28 model calls succeeded**. Cost from the app's model_usage log:

| Case | Calls | Cost |
|---|---|---|
| F1-a | 6/6 | $0.000875 |
| F1-b | 4/4 | $0.000546 |
| S-Kintampo | 6/6 | $0.000964 |
| EJ | 6/6 | $0.001272 |
| F5 | 4/4 | $0.000380 |
| F9 | 2/2 | $0.000052 |
| **Total** | **28/28** | **$0.004089** |

- The first attempt (below) logged 1/1 model_usage row.
- The concurrency retry logged 2/2.
- **Whole run 5 by the OpenRouter key usage counter: $0.012377** (0.041139 → 0.053516).
  - That is about $0.008 more than the app-logged total. I have not explained the gap.
  - The likely source is the first attempt: it ran 2 agent cases but logged only 1 model_usage row, so its usage was not fully recorded. OpenRouter's counter can also lag.
  - The key counter is the cost figure to trust.
  - No 402, and no call failed.

## Results per criterion

| # | Criterion | Result |
|---|---|---|
| 1 | Safety line already in the SMS in the officer queue (not added at send) | **Pass** |
| 2 | After approval: phone == farmer view == recorded approved text, byte-identical | **Pass, 6/6** |
| 3 | API gate | **Pass** |
| 4 | Audit log has proposal and approval entries, with rejection reasons | **Partial (gap)** |
| 5 | Officer edit that deletes the safety line: goes through **with a logged warning**, line not re-inserted | **FAIL (no warning)**; not re-inserted: pass |
| 6 | Length within 612 GSM-7 / 268 UCS-2 (4 parts), sentence cut, no 400 dead end | **Pass** |
| 7 | Southern case: caveat first, then safety line | **Pass** |
| 8 | F1 safety line kept in both runs | **Pass, 2/2** |
| 9 | "(MoFA) ." warning / empty fallback / duplicate safety sentence | duplicate seen once (safe); others not seen |

### 1. Safety line in the queue SMS: Pass
- F1-a, F1-b and S-Kintampo all show "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)." in the SMS on `/officer/cases`.
- For all 6 cases, queue SMS == `farmer_draft.sms` (the proposal), so nothing is added at send.
- Before approval, the farmer view had no answer, and the phone (mock gateway) had only the acknowledgement SMS.

### 2. Byte-identical delivery: Pass, 6/6
For every case these three were byte-identical:
- the text the mock gateway received;
- the farmer view answer;
- the case's recorded `farmer_text`.

For F1-b, the identical text is the officer-edited text.

### 3. API gate: Pass
Each check was measured against the live server:

| Check | Result |
|---|---|
| no officer token: GET queue and POST decision | 401 |
| bad token | 401 |
| `confirmed: false` | 400 "confirm that you checked…" |
| second decision on a released case (reject, then approve) | 409 "case 6 is 'released', not pending_review" |
| simulator off (:18082): outbox and inbound | 404 |
| simulator on: outbox and inbound | 200 |
| officer text of 692 chars | 400, with a prompt to shorten to 612; "Nothing is cut automatically" |

### 4. Audit log: Partial
- The log has these entries:
  - `create_or_update_case` (draft, then pending_review);
  - `model_usage`, `inbound_message` and `officer_decision` (approved);
  - `release_to_farmer` and `send_answer`;
  - `approval_warning` when one occurs (F5).
- **Gap:** proposal-time SMS rejection reasons are stored only in `farmer_draft.problems` on the case, not in `tool_log`. Examples:
  - F1-b's model SMS rejected for "Adds severity condition";
  - EJ's model SMS rejected over a rainfall figure.
- There is no "proposal" log entry. An auditor reading only the log cannot see why the model SMS was replaced by the rule text.

### 5. Officer deletes the safety line: FAIL on the warning
- On F1-b the officer text removed both pesticide sentences, and the case was approved with HTTP 200.
- Pass: the delivered text has no safety line (`approved_has_safety: false`), and it is byte-identical across all three views. The line was **not** silently re-inserted.
- **Fail:** `warnings: []`. No `approval_warning` was logged. Nothing tells the officer, or the audit log, that the guaranteed safety line was removed. The approval check looks at claims and the caveat but not at whether the safety line is still there.

### 6. Length: Pass
- All 6 proposals are GSM-7, 14–555 chars and 1–4 parts, and all end at a sentence boundary.
- F1-a carried the note "1 other sentence dropped to fit 600".
- `sms-check` boundaries, measured:

| Input | Result |
|---|---|
| 612 × "a" | OK (4 parts) |
| 613 × "a" | shorten prompt |
| UCS-2 "Mɛ" × 100 (300 chars) | prompt with max 268 (it would be 5 parts) |

- No proposed text hit a 400 at approval. The only 400 was the deliberate 692-char officer text, and it comes with a clear shorten prompt, so there is no dead end.

### 7. Southern caveat order: Pass
S-Kintampo SMS:
> This advice comes from guides for Northern Ghana and may not suit Kintampo, so check the timing with your local extension agent. Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI). To manage Fall Armyworm in your maize, rotate crops with groundnut. … Ask your local Agricultural Extension Agent for advice on recommended pesticides to control Fall Armyworm.

The caveat comes first and the safety line second. F1-a and F1-b (Adaklu) have the same order.

### 8. F1 safety line: Pass, 2/2
- F1-a: kept on the model SMS path.
- F1-b: kept on the rule-rewrite path; the officer then removed it on purpose (criterion 5).
- On `cc7cf4c` this was 1/2.

### 9. Notes
- **Duplicate safety sentence (safe):** S-Kintampo ends with the model's own "Ask your local Agricultural Extension Agent for advice on recommended pesticides…". This repeats the guaranteed (APNI) line and costs about 100 chars. Seen 1 in 3 pesticide cases.
- **"(MoFA) ." warning:** not seen, and **not exercised**.
  - The EJ SMS this time was the heading-label rule text ("Planting Window: … Planting Time: …"), with no "(MoFA)".
  - It has a double space before " or" in two places. That is cosmetic, but it goes to the farmer as is.
  - EJ was approved with no warning.
- **Empty fallback:** none.
- **F5 approval warning:** "source check couldn't run: the judge model gave no verdict (KeyError: 'n')". This is a judge-output parse failure. It is logged and fails closed, so the officer sees it. It is a parser robustness issue, not a content problem.
- **F9:** the model SMS was rejected and the farmer got "I do not know." It was delivered byte-identically.

## Failures and bugs found
1. **Criterion 5: no warning when the officer deletes the safety line** (above).
2. **Criterion 4: proposal rejection reasons are not in the audit log** (above).
3. **Concurrent SMS inbound lost a farmer's case: seen once, not reproduced.**
   - In the first attempt two webhook inbounds arrived together. One `inbound_message` row is `FAILED: ExceptionGroup` with `case_id NULL`.
   - The DB then had 2 cases but only 1 channel contact. The other case reached pending_review, but no contact was saved and no ack was sent. That farmer would never get the approved reply.
   - A retry with 2 concurrent inbounds (cases 7 and 8 on the main server) worked: both got contacts and both got acks.
   - No traceback was captured, because the server log has only the summary. Treat this as an intermittent race (likely the shared DB or MCP session under parallel agent runs) that needs a traceback.
   - The graded run was done one case at a time on a fresh DB.
4. **Judge parse KeyError 'n'** on F5 at approval (fail-closed, logged).
5. **First attempt, driver bug (eval only):** the driver accepted `draft` status too early, so approval was skipped. It was fixed to wait for `pending_review` plus the `inbound_message` entry. This is not an app bug.

## False-reject rate
3/25 = 12% (self-graded, from run 4 on `cc7cf4c`). This is **accepted as a documented limit**. No more judge whole-sentence shapes will be added; when the judge rejects a correct sentence, the rule rewrite plus officer review is the backstop.
