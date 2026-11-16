# AgriReach auth API: verified contract for the Cursor portal work

Verified on 16 Nov 2026 (UTC) against `API_AUTH_CONTRACT.md`.

**Code verified:**
- The deployed release `d33ab46` (tree `d0051f0`), which runs on AWS.
- Candidate branch `candidate/nairobi-live-draft-fix`.

The auth code is the same in both. The candidate does not touch `officer_auth.py`, the auth routes or `current_officer`. Its `api.py` changes are limited to `_generation`, `_tool_evidence` and the officer case-detail response.

## How it was verified

1. **Executable checks.**
   - Script: `work/contract_verify.py` in the t43 evidence folder.
   - Runs in-process with FastAPI TestClient, a throwaway SQLite DB, no network and no model.
   - Ran on both trees, each with `AGRIREACH_LEGACY_OFFICER_TOKENS=1` and with `=0`.
   - Result: **19/19 checks pass in all four runs** (`contract-{base,cand}-legacy{0,1}.json`).
2. **Live behaviour on AWS.** Source: t40 `aws-acceptance/ACCEPTANCE.md`, from browser runs against the deployed `d33ab46` stack.
   - Officer host without basic auth: 401.
   - Wrong password: refused.
   - Synthetic legacy token: refused. The deployed compose sets `AGRIREACH_LEGACY_OFFICER_TOKENS=0`.
   - Email sign-in, then queue, review and approve: PASS.
   - Farmer reads the approved answer in the same private session, and another session can't read it: PASS on desktop, iPhone and Android.
   - The AWS API port is not published (Caddy fronts only the two portals), so its JSON shapes cannot be called from outside. They were verified from code and the executable checks.
3. **Live local run of the candidate (t43 CP2).** Real uvicorn server with real OpenRouter models:
   - Wrong password: 401.
   - Sign-in: 200.
   - `GET /officer/auth/me`: 200 `kind: "session"`.
   - Decision without bearer: 401.
   - Release without approval: 409 `"Fresh safety assessed approval required"`.
   - Logout: 200, after which `me` returns 401.
4. **Docker (candidate image, local project `t43cand`).** API, farmer and officer containers all healthy. Login 200, `/officer/auth/me` without bearer 401, `AGRIREACH_LEGACY_OFFICER_TOKENS=0` inside the container.

## Officer authentication: verified behaviour

| Claim | Verified behaviour |
|---|---|
| `POST /officer/auth/login` 200 | Returns `{"session_token", "token_type": "Bearer", "expires_at", "officer", "email"}`, exactly these keys. |
| Wrong password or unknown email | Both get the same `401 {"detail": "Invalid email or password."}`. A disabled account gets the same 401. |
| Rate limit, per email | 5 failures in 15 min, then `429 {"detail": "Too many failed sign-in attempts. Wait a few minutes and try again."}` with a numeric `Retry-After`. |
| Rate limit, per client | 20 failures in 15 min (4× the per-email limit), across any emails, then 429. Only failures count. |
| Session lifetime | 8 h, absolute (not sliding), set by `AGRIREACH_OFFICER_SESSION_HOURS`, maximum 24 h. Measured value: 8.000 h. |
| Expired session | 401. |
| `POST /officer/auth/logout` | 200 `{"revoked": true}`. Repeating it gives `{"revoked": false}`. The token is then refused with 401. |
| Other revocation | Operator `revoke`, `set-password` and `disable` all give 401 on that account's open sessions. |
| `GET /officer/auth/me` | 200 `{"officer", "email", "expires_at", "kind": "session"}`. A legacy token gets `kind: "legacy_token"` with `email: null`, but only when legacy tokens are enabled. |
| Legacy tokens | Refused (401) when `AGRIREACH_LEGACY_OFFICER_TOKENS=0`. That is the compose default and the AWS setting. |
| Missing, invalid or revoked bearer on any officer route | `401 {"detail": "officer sign-in required"}` with `WWW-Authenticate: Bearer`. |
| **403** | **Never returned by any route.** Officers get 401. Farmers asking for a case they may not read get 404, to prevent enumeration. |

## Farmer sessions: verified behaviour

| Claim | Verified behaviour |
|---|---|
| `POST /farmer/session` | 200 `{"farmer_session", "expires_at"}`. Lasts 24 h (`AGRIREACH_FARMER_SESSION_HOURS`). Counts toward the submission rate limit. Sets no cookie. |
| `POST /ask` with `X-Farmer-Session` | Files the case and links it to the session. An unknown or expired session gets 401 and nothing is filed. |
| `GET /farmer/session/cases` | Lists that session's own cases. An unknown session gets 401. |
| `GET /farmer/cases/{id}` | Readable with the filing session or `X-Case-Access-Token`. Another session, or no credential, gets `404 {"detail": "not found"}`. |
| Answer visibility | `answer` is null until an officer has approved the exact text and the release gate has validated it. There is no auto-release. |

## Cookie-contract difference (for Cursor)

- **The API has no cookie-based sessions.** No route sends `Set-Cookie`; this was checked on login and on farmer session. There is no CSRF token and no CORS configuration.
- **Tokens travel in the JSON body.** The officer token is returned by login, and the farmer session by `POST /farmer/session`. They are sent back as `Authorization: Bearer …` and `X-Farmer-Session` / `X-Case-Access-Token`.
- **The current Streamlit portals call the API server-side** and keep these tokens in `st.session_state`, so the browser never holds them.
- **A browser SPA that expects an HttpOnly session cookie from the API will not work as-is.** For a cookie-based browser contract, choose one of:
  - **(a)** Keep a server-side BFF (the portal, or a thin proxy) that holds the bearer token and issues its own HttpOnly, Secure, SameSite=Strict cookie, with CSRF protection on state-changing calls.
  - **(b)** Add cookie issuance plus CSRF to the API. That would be new backend work and a change to the deployed contract. **Not done in t43.**
- **The AWS deployment adds Caddy basic auth in front of the officer portal.** That is an extra layer: a browser client needs both the basic-auth credential and the officer session.
- **Session expiry is absolute.** The UI should clear its state on any 401 and show sign-in again. There is no refresh endpoint.

## Changes in the candidate that affect the officer case view

These are additive and backward compatible. Existing keys are unchanged, and `label` is still `"LIVE MODEL DRAFT"` for a model draft that passed.

**New keys in `generation`:**
- `state` (`live_model_draft | model_draft_rejected_source_fallback | model_error_source_fallback | source_draft_with_model_calls | offline_source_draft | officer_written | no_draft`)
- `draft_state`, `draft_label`, `model_used`, `attempted_calls`, `draft_attempts`
- `officer_edited_officer_text`, `officer_wrote_farmer_text`
- `drafting_usage` and `review_usage`, each with calls, tokens and cost

**New labels:**
- `SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT: … (N model calls, $X)` replaces "NO MODEL DRAFT" whenever paid calls were made.
- Offline drafts are now labelled `NO MODEL CALLS: offline source draft (verbatim passages)`.

**`GET /officer/cases/{id}` adds `tool_evidence`:**
- `mcp_runs[]`: per run, the ordered calls with `seq`, `server`, `tool`, `ok`, `error`, `start_ms` and `ms`.
- `draft_checks[]`: per attempt, the outcome, problems (bounded), judge verdicts and source-page checks.
- `timeline[]`: the case's tool_log rows in order.
- `mcp_recorded` / `draft_checks_recorded` are false for cases filed before this change.

**Not covered here:**
- The Streamlit officer UI still shows its own "Offline demonstration draft … No language model was used" banner whenever the draft carries the internal source-draft marker. UI changes were out of scope.
- The API `generation.label` is the accurate badge to use.
