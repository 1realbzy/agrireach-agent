# Nairobi demonstration: farmer and officer workflow

The demonstration uses the existing API, officer credentials, case access tokens,
approval ledger, safety gates and delivery controls. It does not change the
agronomic scope: the corpus and place names are Ghanaian, not validated Kenyan
guidance. Follow `windows-local-pilot.md` for isolated loopback setup. Do not enable
SMS or WhatsApp for a synthetic demonstration.

## Pages

- **Farmer**: submit a question, keep its case number and private access token,
  then check status. The token is masked and is specific to this case. Pending,
  rejected, information-requested and delivery states do not expose draft advice.
- **Extension officer** (`/officer`): paste the operator-issued officer token and
  choose **Sign in**. A farmer's token cannot authenticate an officer. The queue
  refreshes every ten seconds. Open a case to inspect the question, draft,
  source passages, safety findings and exact proposed farmer response.
- **Voice simulator** (`/voice`): local synthetic channel intake and consent,
  recording upload, and simulator outbox. This is not a production phone service.

Officer sign-in persists during in-app navigation. Sign-out removes officer
credentials, review snapshots, edits and acknowledgement challenges. A browser
reload can start a new Streamlit session and require sign-in again. No credentials
are put into URLs or local storage.

An opened review retains its server revision. Queue refreshes do not silently
replace that revision. If someone else changes the case, the API refuses a stale
decision. **Reload case and discard unsaved edits** fetches the current version
and clears confirmation and acknowledgement state. Opening a queue case also
starts a fresh review. Review every line before checking the approval box.

The existing reject/request-info note requirements, source acknowledgement,
assessment retry, reopen, delivery retry and uncertain-delivery reconciliation
controls remain available. Reconciliation records evidence without sending.

## Offline walkthrough

1. Start the API and UI against a disposable database with messaging disabled.
2. Open the farmer page in one browser session and the officer page in another.
3. Sign in as the disposable officer. Submit a synthetic question such as
   “When should I harvest soybean in Tamale?” as the farmer.
4. Check the farmer status before approval: no answer should be visible. The
   officer queue should discover the case automatically.
5. Open the case, inspect the source evidence and proposed text. The offline
   label means no language model produced the draft. It is not a quality claim.
6. For this deterministic harvest scenario, review and use the exact harvest
   passage from the APNI/SARI source as the farmer response. Confirm source review
   and approve. Never bypass a hold to complete a demo. Planting examples can
   retrieve conflicting source guidance and correctly remain held for resolution.
7. Check the farmer answer. Only the exact approved response should appear.
8. Repeat with another synthetic question and reject with a note. No answer
   should appear. Sign out of the officer session when finished.

Arbitrary prose may require a live judge and intentionally fail closed offline.

## Voice capability audit

| Capability | Implementation and limits |
| --- | --- |
| Audio upload | Implemented in the simulator inbound API; accepts real recording files, subject to existing intake and consent rules. |
| Consent and case filing | Implemented. The simulator exchanges local messages; no carrier is involved. |
| Transcription | Optional local faster-whisper. With STT disabled, no transcript is fabricated; the officer is told to listen. Missing models or dependencies are not successful transcription. |
| Officer listening | Authenticated voice metadata and audio endpoints; audio playback appears in case review. |
| Response drafting | Existing text pipeline. Offline mode assembles retrieved content; live inference requires a separately configured model. |
| Spoken response | Optional Piper synthesis, gated by approval of the exact voice script and the existing release workflow. |
| Languages | The current speech implementation is documented for synthetic English fixtures. Twi, Dagbani, Wali, Ghanaian-accented English and Kenyan languages are not validated by this run. The configured Piper default is US English. |
| Real phone delivery | Separate SMS/WhatsApp integrations exist but are disabled and were not exercised here. |

This task does not introduce a speech subsystem or change these backend paths.

## Repeatable browser verification

Install developer-only Playwright in your Python environment and provide Google
Chrome. Set `AGRIREACH_BROWSER_CHANNEL=msedge` to use installed Microsoft Edge.
Run from the repository root with `PYTHONPATH=src`:

```powershell
python -m pip install playwright
$env:PYTHONPATH = 'src'
$env:AGRIREACH_BROWSER_WORK = '../browser-work'
$env:AGRIREACH_BROWSER_EVIDENCE = 'output/playwright'
python scripts/verify_pilot_browser.py
```

Ports 18000 and 18501 must be free. The script creates its own database, synthetic
officer, cases, media and local outbox; disables external delivery and model
inference; stops its servers on exit; and leaves disposable data in the chosen
work directory for inspection. It does not read existing pilot credentials.
Screenshots mask private case-token fields. No traces, HTML dumps or token logs
are produced. The separate historical pilot authentication investigation is not
part of this reproducible test script.

The browser suite covers valid/invalid officer sign-in, native clipboard paste,
whitespace, navigation, reruns, automatic queue discovery, farmer submission,
pending secrecy, safety holds, exact approved retrieval, stale revision refusal,
rejection, credential separation, sign-out, audio upload with consent and STT off,
authenticated audio review, and mobile overflow. Unit/integration tests cover the
additional acknowledgement, integrity, delivery, consent and fail-closed paths.
