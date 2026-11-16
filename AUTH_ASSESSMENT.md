# AgriReach authentication assessment (Nairobi release, 16 Nov 2026)

Branch `work/emergency-routing-fix` (based on `a9ab347`). All statements below were checked in code and tests.

## 1. Farmer case access before this change (baseline `a9ab347`)

- `POST /ask` files a case and returns `case_id` (sequential) and `access_token`
  (`secrets.token_urlsafe(32)`). Only the token's SHA-256 is stored (`farmer_case_access`, migration v3).
- `GET /farmer/cases/{id}` and `POST /farmer/cases/{id}/supplement` require header `X-Case-Access-Token`.
  A wrong or missing token returns **404** (not 401), so case numbers cannot be enumerated.
- The phone number (optional, only with `sms_consent`) is stored for SMS acknowledgement in
  `farmer_sms_contacts`; it is **never** an access credential. No endpoint lists cases by phone.
- The farmer body only ever contains officer-approved text (`answer` is `None` until a validated release).
- Portal: the case id and token are kept in the Streamlit server-side session and in tab-scoped
  `sessionStorage` for refresh recovery (`tab_recovery.py`); a manual "Question number + Private access
  code" lookup form also exists. That form is the "reference number" burden the brief wants removed.

**Guarantee preserved:** a phone number alone cannot read anyone's history. Verified by
`tests/test_farmer_session.py::test_same_phone_does_not_share_history_across_sessions`.

## 2. Farmer private sessions (added, migration v7)

- `POST /farmer/session` returns an opaque `farmer_session` (32-byte random; SHA-256 stored) valid for
  `AGRIREACH_FARMER_SESSION_HOURS` (default 24, max 168). Rate limited like submissions.
- `POST /ask` with `X-Farmer-Session` links the new case to that session (an unknown/expired session is
  refused with 401 and nothing is filed).
- `GET /farmer/session/cases` lists only that session's cases (newest first, max 50) with the same
  approved-text-only body. `GET /farmer/cases/{id}` and the supplement accept the session instead of the
  per-case token, but only for cases filed with it (otherwise 404).
- The portal should create the session server-side and keep it in `st.session_state` (never display it).
  This removes the need for farmers to remember question numbers. The per-case token path still works.
- Limitation: a session is tied to one browser session/device. Without phone verification (OTP), a farmer
  on a new device cannot recover history. That is deliberate: phone numbers are not proof of ownership.

## 3. Officer authentication before this change

- `scripts/add_officer.py "Name"` → `db.add_officer` creates/replaces a row in `officers(name, token_sha256)`
  and prints a `token_urlsafe(24)` token once. Only SHA-256 stored.
- `current_officer` (api.py) reads `Authorization: Bearer <token>`; every officer route and release
  depends on it; the officer name on approvals comes from it, never from the request body.
- Weaknesses: tokens **never expire**; revocation only by re-running `add_officer.py` for that name;
  no logout on the server; no rate limiting on guesses (mitigated by 192-bit token entropy); the portal
  asks the officer to paste the token.

## 4. Officer email + password (added, migration v7)

- Accounts are operator-provisioned only: `python scripts/officer_accounts.py create EMAIL "NAME"`
  (prompts twice, or `--password-stdin`). Also `set-password`, `disable`, `enable`, `revoke`, `list`.
  No sign-up and no admin HTTP endpoint. No default or shared credentials exist.
- Passwords: min 12 / max 256 chars; hashed with stdlib `hashlib.scrypt` (N=2^14, r=8, p=1, 16-byte salt,
  32-byte key), compared with `hmac.compare_digest`. Unknown emails are checked against a dummy hash so
  timing does not reveal which emails exist. One generic 401 message for every failure.
- Sessions: `POST /officer/auth/login` returns an opaque `session_token` (SHA-256 stored in
  `officer_sessions`) with absolute expiry `AGRIREACH_OFFICER_SESSION_HOURS` (default 8, max 24).
  Revoked by `POST /officer/auth/logout`, by the operator (`revoke`), by `disable`, and by `set-password`.
- Rate limiting: failures are recorded in `officer_login_attempts` (hashed keys, no emails/passwords).
  `AGRIREACH_LOGIN_MAX_FAILURES` (default 5) failures per email in `AGRIREACH_LOGIN_WINDOW_SECONDS`
  (default 900) → 429 + `Retry-After`, even for the correct password; per client the allowance is 4x.
  Survives API restarts (stored in SQLite).
- `current_officer` accepts a valid session first; legacy tokens only while
  `AGRIREACH_LEGACY_OFFICER_TOKENS` is not `0`. Code default is on (backward compatibility and the
  existing test-suite); **`compose.demo.yaml` defaults it to `0`**, so a deployed stack accepts sessions only.
- Approval integrity is unchanged: sessions change who is recorded, never what an approval must prove
  (`test_session_approval_still_requires_the_full_approval_gate`).

## 5. Migration numbering decision

The migration runner (`migrations.py`) only accepts a contiguous ledger `1..N` with exact checksums, so
gaps (e.g. jumping to v8) are not supported. This branch therefore uses **v7** for
`officer_accounts`, `officer_sessions`, `officer_login_attempts`, `farmer_sessions`, `farmer_session_cases`.

**Conflict:** `work/case-followup-operations` (`8024205`) also defines a different v7 (follow-up tables).
The table names do not overlap. Whichever branch lands second must renumber its migration to **v8**
(statements, checksum, `_valid_ledgers`, `upgrade_v8`, `ensure_schema`, `required` tables, and the
schema-version assertions in tests). A database already migrated with one branch's v7 will be refused by
the other branch (checksum mismatch) — by design; never open the pilot DB with either branch until the
order is decided. The pilot DB (`data/pilot.db`) was not opened by this work.

Also fixed while adding v7: `validate_existing_ledger` now requires the v6 SMS tables for any version
`>= 6` (it previously checked only `== 6`, which would have stopped checking them at v7).

## 6. Officer portal

The existing token form is unchanged (its tests are unchanged). A minimal email/password form was added
below it and calls `POST /officer/auth/login`; the session token goes into the same server-side
`st.session_state['officer_token']` slot and the tab-scoped refresh store (8 h cap, matching the session).
"Sign out" also calls `/officer/auth/logout` for session sign-ins. The interface redesign (removing the
token form, layout) belongs to the Cursor UI work; see `API_AUTH_CONTRACT.md`.

## 7. Residual risks

- The session token sits in tab `sessionStorage` for refresh recovery (as the legacy token did). It is
  expiring and revocable; the API validates it on every request. XSS in Streamlit would expose it.
- Rate-limit counters for farmer submissions are in-memory (reset on API restart); login counters persist.
- No MFA, no password reset by email (operator resets with `set-password`).
- Deployment still needs HTTPS and should keep the officer portal behind an additional access
  restriction (proxy password / IP allow-list) for the event.
