# AgriReach API and authentication contract (for the portal redesign)

Backend branch: `release/nairobi-live-demo`. All examples use synthetic data. The portals call the API
server-side (Streamlit), so tokens never need to reach the browser DOM. Base URL inside compose:
`http://api:8000` (never publish the API port publicly).

Common rules
- JSON in/out. Validation errors: `422 {"detail": [{"loc": [...], "type": "...", "msg": "..."}]}` (fixed messages).
- Portals should send `X-AgriReach-Client: <sha256(browser address)[:32]>` on every call; the API uses it
  for per-browser rate limits only when `AGRIREACH_TRUST_PORTAL_CLIENT_HEADER=1` (set in compose).
- Officer auth: `Authorization: Bearer <session_token>`. Missing/invalid/expired/revoked → `401
  {"detail": "officer sign-in required"}` with `WWW-Authenticate: Bearer`.
- Farmer access: `X-Farmer-Session: <farmer_session>` (preferred) or `X-Case-Access-Token: <access_token>`.
  A case the caller may not read → `404 {"detail": "not found"}` (never 401/403, to avoid enumeration).
- Phone numbers are identifiers for SMS consent only. They never grant access to any case.
- Mandatory officer approval: farmers only ever receive `answer` after an officer approved the exact text
  and the release gate validated it. There is no auto-release.

## Officer endpoints

### POST /officer/auth/login
Request `{"email": "ama.mensah@example.org", "password": "<12-256 chars>"}`
- 200 `{"session_token": "<opaque>", "token_type": "Bearer", "expires_at": "2026-11-17T01:00:00+00:00",
  "officer": "Ama Mensah", "email": "ama.mensah@example.org"}`
- 401 `{"detail": "Invalid email or password."}` (same for unknown email, wrong password, disabled account)
- 429 `{"detail": "Too many failed sign-in attempts. Wait a few minutes and try again."}` + `Retry-After`
  (5 failures per email per 15 min by default; 20 per client)
- Store `session_token` in `st.session_state` only; never render it. Session lifetime 8 h (absolute, not
  sliding). On any 401 later, clear state and show the sign-in form.

### POST /officer/auth/logout
Bearer session. 200 `{"revoked": true}` (or `false` if already revoked / legacy token). Always clear state.

### GET /officer/auth/me
Bearer. 200 `{"officer": "Ama Mensah", "email": "ama.mensah@example.org", "expires_at": "...", "kind": "session"}`
(`kind: "legacy_token"`, email null, for legacy tokens).

### GET /officer/queue
Bearer. 200 list of case objects with status `pending_review` or `not_delivered`, urgent first.
Case object (abridged):
```json
{"id": 12, "question": "my goats died after I sprayed", "crop": null, "region": null,
 "status": "pending_review", "priority": "urgent", "revision": 1,
 "urgent_reasons": ["EMERGENCY: animal, bird or fish deaths reported (farmer wrote: 'died', 'goats'). ..."],
 "sources": [], "draft": "...", "farmer_draft": {...} , "created_at": "...", "officer": null,
 "generation": {"draft_mode": "llm:meta-llama/llama-3.3-70b-instruct", "live_model": true,
                "label": "LIVE MODEL DRAFT", "model_calls": 3, "prompt_tokens": 5120,
                "completion_tokens": 640, "models": ["meta-llama/llama-3.3-70b-instruct"],
                "cost_usd": 0.00104, "cost_complete": true}}
```
- Reasons starting with `EMERGENCY:` must be shown prominently (error style). Emergency cases have no
  sources and no model draft by design; the officer contacts the farmer.
- `generation.label` is the live-vs-offline badge text. `cost_usd` null means the provider did not report a
  cost (show "unknown", never 0).

### GET /officer/cases?status=<one of draft|pending_review|approved|released|not_delivered|undeliverable|rejected|needs_info>
Bearer. 200 list of case objects (history). 400 for an unknown status.

### GET /officer/cases/{id}
Bearer. 200 case object + `"log": [tool_log rows]` (MCP tool calls, model_usage, safety checks). 404 unknown.

### POST /officer/cases/{id}/assess
Bearer. `{"farmer_text": "..."}` → safety assessment (S1–S4 findings) without approving.

### POST /officer/cases/{id}/farmer-draft
Bearer. `{"officer_text": "..."}` → proposed farmer wording (may call the model; usage logged on the case).

### POST /officer/cases/{id}/sms-check, /voice-preview
Bearer. `{"farmer_text": ...}` / `{"officer_text": ...}` → length/segments check, voice script preview.

### POST /officer/cases/{id}/decision
Bearer.
```json
{"decision": "approve", "farmer_text": "<exact text the farmer receives>", "confirmed": true,
 "expected_revision": 3, "note": null, "acknowledgement": null, "edited_text": null}
```
`decision`: `approve | edit_approve | reject | request_info`.
- 400: missing `farmer_text`, `confirmed` false, or missing `note` for reject/request_info.
- 409: stale revision, gate error, or `acknowledgement_required` (body has a challenge; resend with
  `acknowledgement`).
- 422: safety blocked / review required (body has `findings`). 503: assessment unavailable.
- 200: case object + `{"delivery": ..., "warnings": [...]}`; approved cases are released immediately.

### POST /cases/{id}/release
Bearer. Retry release of an approved case. 409 if nothing valid to release.

### POST /officer/cases/{id}/reopen
Bearer. `{"expected_revision": 4, "information": "farmer sent the district"}`.

### Delivery/acknowledgement reconciliation (operators)
`GET /officer/cases/{id}/delivery-jobs`, `POST /officer/delivery-jobs/{job}/reconcile`,
`GET /officer/cases/{id}/acknowledgement`, `POST /officer/acknowledgement-jobs/{job}/reconcile`
(`{"accepted": true, "provider_evidence": "..."}`). SMS/WhatsApp are disabled in the demo.

## Farmer endpoints

### POST /farmer/session
No auth. 200 `{"farmer_session": "<opaque>", "expires_at": "..."}` (24 h). Counts toward the submission
rate limit. Create once per portal session; keep server-side in `st.session_state`; never display it.

### POST /ask
Headers: optional `X-Farmer-Session`. Request:
```json
{"question": "When should I plant maize in Tamale?", "crop": "", "region": "",
 "phone": "0240000001", "sms_consent": false}
```
- 200 `{"case_id": 41, "access_token": "<opaque>", "status": "pending_review" | "draft",
  "clarification": null | "Which crop is this about? ...", "message": "...", "acknowledgement": {...}}`
  plus `"emergency": true` (fixed referral message: call 112 / health facility / veterinary officer;
  officer alerted) or `"evidence_gap": true`.
- 401 unknown/expired `X-Farmer-Session` (nothing filed). 422 invalid phone when `sms_consent` is true.
- 429 `{"detail": "Too many questions have been sent ... If someone is ill or has swallowed a chemical,
  call 112 now."}` + `Retry-After` (10 per 10 min per browser and per phone by default).
- Show `message`; if `clarification` is set, ask the farmer and use the supplement endpoint.

### GET /farmer/session/cases
`X-Farmer-Session`. 200 list (newest first, max 50) of farmer case bodies + `question`, `created_at`.
401 unknown/expired session. This replaces "question number + private access code" in the UI.

### GET /farmer/cases/{id}
`X-Farmer-Session` (case filed with it) or `X-Case-Access-Token`. Farmer case body:
- waiting: `{"case_id": 41, "status": "pending_review", "answer": null, "message": "Waiting for an extension officer ..."}`
  (+ `emergency` / `evidence_gap` flags with fixed messages)
- clarification: `{"status": "draft", "clarification": "...", "revision": 2, "answer": null, "message": "..."}`
- released: `{"status": "released", "answer": "<officer-approved text>", "approved_by": "Ama Mensah", "approved_at": "..."}`
- rejected / not_delivered / undeliverable / review_required: `answer` null with a fixed message.
Never contains drafts, model output, sources or `generation`.

### POST /farmer/cases/{id}/supplement
Same farmer auth. `{"text": "Tamale", "expected_revision": 2}` → updated farmer body. 409 if not waiting
for farmer information or stale revision. Counts toward the rate limit.

### GET /health
`{"ok": true, "draft_mode": "llm" | "stub"}` — global mode only; use `generation` per case.

## Environment (names only)
`AGRIREACH_LEGACY_OFFICER_TOKENS` (compose default 0), `AGRIREACH_OFFICER_SESSION_HOURS` (8, max 24),
`AGRIREACH_LOGIN_MAX_FAILURES` (5), `AGRIREACH_LOGIN_WINDOW_SECONDS` (900), `AGRIREACH_SUBMIT_LIMIT` (10),
`AGRIREACH_SUBMIT_WINDOW_SECONDS` (600), `AGRIREACH_FARMER_SESSION_HOURS` (24),
`AGRIREACH_TRUST_PORTAL_CLIENT_HEADER` (1 in compose), plus existing `DATABASE_URL`, `LLM_*`, `AGRIREACH_JUDGE_*`.

## Provisioning officers
`docker compose -f compose.demo.yaml exec -T api python scripts/officer_accounts.py create EMAIL "NAME" --password-stdin`
(password on stdin; never in shell history or files committed). `revoke EMAIL` signs an officer out everywhere.
