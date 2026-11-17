# Officer and farmer session contract

For the authentication API. The interface on `work/cursor-ux-farmer-officer` does not implement this. Email and password on the officer page are a layout only: the form does not call the network and does not store the password.

The verified API at `53cf0f6632b87d9df73af889069f64a7c334528e` is unchanged.

## What the interface does today

| Action | Call | Credential |
|---|---|---|
| Ask a question | `POST /ask` JSON `{"question": "..."}` | none |
| Ask and request a text update | `POST /ask` JSON `{"question", "phone", "sms_consent": true}` | none |
| Read the current question | `GET /farmer/cases/{id}` header `X-Case-Access-Token` | token returned by `POST /ask`, held in the tab |
| Add a missing detail | `POST /farmer/cases/{id}/supplement` same header, JSON `{"text", "expected_revision"}` | same tab token |
| Officer queue | `GET /officer/queue` | `Authorization: Bearer <operator token>` |
| Officer question | `GET /officer/cases/{id}` | same bearer |
| Decision | `POST /officer/cases/{id}/decision` | same bearer |
| Safety check | `POST /officer/cases/{id}/assess` | same bearer |

`POST /ask` returns `case_id`, `access_token`, `status`, `message`, and sometimes `clarification`, `revision`, `evidence_gap`, and `acknowledgement`. The farmer screen no longer displays `case_id`. It still keeps both values in the tab so refresh and "Check for updates" can call the API. Closing the tab drops them. A phone number is not treated as authentication.

Officer sign-in today is a bearer token issued by `scripts/add_officer.py`. There is no email, password, expiry, or logout endpoint. A 401 clears the tab credential. Sign-out only forgets it in the browser; the token stays valid on the server.

## Farmer submission

Request:

```json
{"question": "When should I plant maize in Tamale?"}
```

Optional, only when the farmer checks the text-update box:

```json
{"question": "...", "phone": "0240000000", "sms_consent": true}
```

`question` is required, 1–2000 characters after trimming. `phone` is a Ghana mobile number. Do not require a phone in order to ask. Do not create a farmer session from the phone number.

Response `200` must keep the current fields. `access_token` may stay in the JSON for this release because the screen stores it in the tab and does not show it. Do not put the token in a URL.

`422` when the phone is present and invalid, or consent is set without a number. The body must not echo the phone number.

Other failures: `503` or a connection error. The screen tells the farmer nothing was saved.

## Farmer session

Not available. Do not add a "logged in as this phone" state.

A later session, if built, must be separate from typing a phone number on the question form. It needs its own proof (a code to the handset, or an equivalent check), an expiry, and a logout. Until that exists, the tab token remains the only way to reopen a question, including after a browser refresh.

Status the farmer screen already understands: `draft` with `clarification`, `pending_review`, `approved` (not readable yet), `released` with `answer`, `rejected`, `needs_info`, `not_delivered`, `undeliverable`, `evidence_gap`, `processing_failure`. Do not return `answer` unless the farmer is allowed to read it. `approved` is not delivered.

## Officer login

Needed:

`POST /officer/login`

```json
{"email": "officer@example.com", "password": "..."}
```

Success `200`:

- Set an `HttpOnly`, `Secure`, `SameSite=Lax` session cookie. Do not return a long-lived bearer token in JSON.
- Body may be `{"officer": "Ama Mensah"}` and nothing secret.
- The cookie lifetime is the session lifetime. Suggested maximum: 8 hours, matching the current tab recovery cap, with idle expiry if the server supports it.

Failure `401` with a stable body, for example `{"detail": {"outcome": "sign_in_failed"}}`. Do not say which of email or password was wrong. Do not echo the password.

The interface will send this request only after this contract is implemented. Until then the form stays labeled "not connected".

## Session expiration

When the cookie is missing or expired, protected officer calls return `401` with `{"detail": {"outcome": "session_expired"}}`.

The screen already treats `401` as signed out and returns to the sign-in page. It must not keep a copy of the session secret to retry silently.

## Logout

Needed: `POST /officer/logout`.

- Requires the session cookie.
- Revokes that session on the server.
- Clears the cookie.
- Returns `204`.
- A second call with no cookie returns `204` as well.

The current "Sign out" button only deletes the bearer token from tab storage. After login exists, Sign out must call `POST /officer/logout` and then clear local tab state. It must not leave a usable cookie behind.

## Protected requests

Officer routes keep their current paths and bodies. The browser will send the cookie (`credentials` / same site). Stop requiring the interface to attach `Authorization: Bearer` once cookie sessions are the supported path.

Keep accepting the existing bearer token for operator scripts and tests until those callers move. The farmer and officer screens should not ask a person to paste it after cookie login works.

Farmer case routes stay on `X-Case-Access-Token` until a farmer session exists. Do not replace that header with the phone number.

## Errors

Use the existing status codes:

| Status | Meaning for the screen |
|---|---|
| 401 | Officer session missing, expired, or rejected. Return to sign-in. |
| 404 | Farmer question not found, or the case token does not match. Do not reveal whether the id exists. |
| 409 | Stale revision or the question is not in a state that accepts this action. Tell the officer to reload. |
| 422 | Validation or a safety hold. Nothing was approved. Include `detail.findings` when the safety gate produced them. |
| 503 | The safety check or the service could not run. Nothing was approved or sent. |

Do not put exception text, stack traces, phone numbers, tokens, or model names in `detail`.

## Case status

`GET /officer/queue` stays the list of questions that need action (`pending_review`, `not_delivered`).

`GET /officer/cases/{id}` must keep returning the question, status, revision, sources, draft, farmer text, and `log` (tool name, ok, result summary). The screen shows that log to the officer. Do not put phone numbers or secrets in `log`.

`GET /farmer/cases/{id}` must keep withholding the draft. Include `answer` only when the farmer may read it. Include `message` for review, rejection, evidence gap, and processing failure. Include `clarification` and `revision` when the farmer still has to add a detail.

## Out of scope for this contract

Language switching, speech recognition, and any claim that a phone number alone authenticates a farmer.
