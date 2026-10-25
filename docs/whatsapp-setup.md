# WhatsApp Cloud API adapter: setup notes

Status, 25 Oct 2026: **code only.** It is not registered with Meta, no phone number is connected, it is not deployed
and it has never sent or received a real WhatsApp message. Everything below was tested only against mocked Graph API
responses (`tests/test_whatsapp.py`).

## How it works

- `GET /channels/whatsapp/webhook`: Meta's subscription check. Answers `hub.challenge` only when
  `hub.mode=subscribe` and `hub.verify_token` matches `WHATSAPP_VERIFY_TOKEN`.
- `POST /channels/whatsapp/webhook`: the body must carry `X-Hub-Signature-256: sha256=<hex>`, the HMAC-SHA256 of the
  raw body with the app secret. It is checked (constant-time compare) before the JSON is parsed; bad or missing
  signatures get 401, bodies over 3 MB get 413. The endpoint answers 200 at once and processes messages in a
  background task.
- Text and audio (voice note) messages become cases through the same `handle_inbound` path as the simulator. Voice
  notes are downloaded with `GET /{media-id}` and then the returned URL, both with the bearer token. Other message
  types are logged and ignored.
- Message ids are de-duplicated (Meta retries deliveries).
- Replies are **text only**. The adapter does not send the Piper WAV file. To send audio, it would have to be
  converted to a format WhatsApp accepts (check Meta's media reference; OGG/Opus is the voice-note format) and
  uploaded first. Not built.
- Messages over 4096 characters are refused with a note for the officer to shorten, not cut.

## Configuration (all required; nothing is mounted unless `WHATSAPP_ENABLED=1`)

| Variable | Meaning |
|---|---|
| `WHATSAPP_ENABLED` | `1` to mount the webhook routes; default off |
| `WHATSAPP_VERIFY_TOKEN` | a random string you choose and type into the Meta webhook settings |
| `WHATSAPP_APP_SECRET` | the Meta app secret, used to verify `X-Hub-Signature-256` |
| `WHATSAPP_ACCESS_TOKEN` | a system-user token with `whatsapp_business_messaging` |
| `WHATSAPP_PHONE_NUMBER_ID` | the business phone number id |
| `WHATSAPP_GRAPH_VERSION` | default `v26.0`; pin it deliberately against Meta's changelog |

Keep these in a local env file outside the repo. `Config.__repr__` hides them, and they are never logged.

## Steps before any real use (none done)

1. Meta Business account, app with the WhatsApp product, verified business phone number.
2. Host the API over HTTPS at a stable URL, set the webhook URL and verify token in the app dashboard, subscribe
   to `messages`.
3. Replies outside WhatsApp's 24-hour customer-service window need an approved template message. The adapter only
   sends free-form text, so an officer approval that comes more than 24 hours after the farmer's message will fail
   (the failure is recorded on the case). Template support is not built.
4. Farmer consent and a privacy notice: a first-contact consent prompt, STOP and a retention purge exist
   (docs/voice-channel.md), but the wording needs legal review against Ghana's Data Protection Act 2012 (Act 843),
   and WhatsApp's own opt-in rules for business messaging apply.
5. Test speech-to-text on real, consented voice notes from the target farmers before relying on it (see
   [voice-channel.md](voice-channel.md): it has only been tested on synthetic US-English speech).
6. Rate limits, retries for failed sends, and monitoring are not built.
