# Judging-readiness UI report

This branch changes only the Streamlit portal. It does not change Grok's candidate, the deployed AWS release `d33ab46`, `main`, or any other worktree.

## Branch

- Worktree: `C:\Users\1realbzy\Downloads\Agrireach\ux-farmer-officer`
- Branch: `work/cursor-judging-readiness`
- Preserved UI checkpoint: `work/cursor-ux-farmer-officer` at `ec6d06fb0fafdd902ff133badc688001bbef3b79` (tree `39e9d62cbd3145efa014fab09440c6a78d23847a`)
- API exercised locally, not modified: `candidate/nairobi-live-draft-fix` at `00196c6` (tree `9e2ec89`), checked out detached at `C:\Users\1realbzy\Downloads\Agrireach\candidate-readonly-00196c6`

The commit and tree for this UI change are recorded in git after this file is committed.

## What the portal does

Officer sign-in calls `POST /officer/auth/login` and keeps `session_token` in Streamlit server session state. The token is not written into the page, the URL, or the browser `sessionStorage` bridge. Each signed-in run calls `GET /officer/auth/me`. A 401 clears the server session and asks the officer to sign in again. Sign-out calls `POST /officer/auth/logout`. The old access-code form is gone.

A full browser reload starts a new Streamlit session, so the officer sees sign-in again. That is the consequence of not putting the bearer token in browser script storage. The API session itself stays valid until logout or the absolute expiry.

Farmer questions are filed with `X-Farmer-Session` when `POST /farmer/session` succeeds. The tab lists only that session's questions. A phone number is not treated as a login. The page says no SMS was sent unless the API message says the provider accepted it. A collapsed lookup remains for a question whose tab was closed.

The queue prints the server `EMERGENCY:` reason before the case is opened, in the order the API returns. Tool rows come from `tool_evidence.mcp_runs[].calls` (`seq`, `tool`, `server`, `ok`, `error`, `ms`). If that record is absent, the screen says so and can show the existing case log. It does not invent calls. Generation text uses `generation.state` and `generation.label`. A draft that still contains the offline marker is not described as "no language model was used" when the payload records model calls. A missing cost stays "cost unknown".

## Evidence

Disposable local run, stub mode, no paid model call, ports 18000 / 18501 / 18502:

- Wrong password: HTTP 401, page text "Invalid email or password.", password not left in `sessionStorage`.
- Email sign-in: queue opened, signed-in line showed the email and `expires_at`, `sessionStorage` was empty.
- Logout from a second API session: `GET /officer/auth/me` 200, `POST /officer/auth/logout` `{"revoked": true}`, following `me` 401.
- Reload of the officer page returned to "Officer sign in".
- Farmer submit without a phone: "Your question has been received." and "No confirmation SMS was sent." The private-session list showed the question. A second farmer session's case list was empty.
- Emergency queue item was labelled before opening, using the server reason for gramoxone.
- Opened soybean case showed `search_guidance`, `retrieve_reference`, and `get_crop_calendar` with durations, and `NO MODEL CALLS: offline source draft`, which matches this stub server. The rejected-live-model wording is covered by `tests/test_ui_judging.py` and `tests/test_round2_ui.py` against the verified payload, not by a live model call.
- Source line for that case was one title: the soybean guide, Harvesting.
- iPhone-width farmer page and Android-width officer queue stacked in one column. Screenshots: `docs/ux/judging/`.
- Automated tests: 68 passed (`test_ui_judging`, `test_round2_ui`, `test_ux_pending_login`, `test_streamlit_refresh_recovery`, `test_farmer_active_question`, `test_post_live_evidence_gap`, `test_live_inference_readiness`, `test_cp3_staged_clarification`).

The browser reject checkbox could be checked. The Reject button stayed disabled in that automated pass because the note did not remain in the Streamlit widget across the rerun. Approve stayed disabled until its confirmation checkbox. No approval was sent.

## Recommendation

**NO GO** for merge or deployment.

The portal is ready to review on this branch, pointed at a server that already implements `CURSOR_API_CONTRACT_VERIFIED.md`. It is not a combined build. `generation.state` and `tool_evidence` exist on the unapproved candidate, not on the preserved UI checkpoint's own API. AWS `d33ab46` was not changed. Do not deploy this UI, the candidate, or a merge of the two until that candidate is approved and a browser approve/reject completes on the combined process.
