# SMS adapter (Africa's Talking): setup notes

Status, 25 Oct 2026: **code only.** There is no Africa's Talking account, no API key, no sender ID and no short
code. It is not deployed, it has not been tested against a live or sandbox account, and it has never sent or received
a real SMS. Everything below was tested only against mocked HTTP responses (`tests/test_sms.py`). It is off unless
`SMS_ENABLED=1`.

## How it works

- **Outbound** goes through the same `service.deliver()` path as the simulator and WhatsApp. Only a case that an
  officer approved and released is sent, as the exact approved farmer text. The only texts sent without an officer
  are the existing fixed system messages: acknowledgement, consent prompt, clarifying question, opt-out confirmation.
- The send is `POST {base}/version1/messaging`, form-encoded, with the `apiKey` header and `Accept: application/json`.
  Fields: `username`, `to` (one `+233...` number), `message`, and `from` only if `AT_SENDER_ID` is set. Base URL is
  `https://api.sandbox.africastalking.com` when `AT_SANDBOX=1` (the default) and `https://api.africastalking.com`
  when `AT_SANDBOX=0`.
- A recipient status of 100 (Processed), 101 (Sent) or 102 (Queued) counts as accepted. That means Africa's Talking
  took the message, not that the phone received it: delivery reports are not handled yet. Any other status, an HTTP
  error, a network error or an unreadable response is recorded on the case as a failed delivery. The farmer's number
  is masked in that record.
- **Inbound**: `POST /channels/sms/inbound/<SMS_WEBHOOK_TOKEN>` takes Africa's Talking's incoming-message callback
  (form fields `from`, `text`, `id`, `to`, `date`, `linkId`, `networkCode`). It answers 200 at once and makes a case
  in a background task through the same `handle_inbound` path as the other channels. That means the first-contact
  consent prompt, YES/STOP/"gyae" handling, the retention purge and de-duplication by `id` (in case Africa's
  Talking retries) all apply unchanged. Senders are masked in every log line.

## Length and encoding

SMS has two encodings, and the adapter works out which one a message needs before it sends:

| Encoding | When | One SMS | Each part of a longer SMS |
|---|---|---|---|
| GSM-7 | every character is in the GSM 03.38 set | 160 characters | 153 |
| UCS-2 | any other character | 70 | 67 |

- `[ ] { } ~ ^ | \` and the euro sign are in GSM-7's extension table and count as two characters.
- Twi, Ga, Ewe and Dagbani letters such as **ɛ ɔ ŋ ɣ ʒ** are not in GSM-7. One of them turns the whole message into UCS-2, so
  it fits less than half as much text per SMS. So do curly quotes (’ “ ”), en and em dashes and emoji. Emoji count
  as two.
- `SMS_MAX_SEGMENTS` (default 4) is the most parts one message may use. Nothing is ever cut or dropped to fit; a
  pesticide safety line stays, and the officer decides what to shorten. The length is checked at four points:
  1. **When an SMS case is filed.** The farmer draft carries `sms_limit`, which the officer sees on every SMS case,
     e.g. "SMS limit for this farmer: 4 parts, which is 612 characters of standard text, or 268 if the text has any
     Twi, Ga, Ewe or Dagbani letter (ɛ ɔ ŋ ɣ), curly quote or emoji". If the proposed text won't fit, an approval
     prompt is added next to "sources differ" and the season check:
     "too long for SMS: this text needs 10 parts (Unicode because of ɛ); the limit is 4. Shorten it to 268
     characters or fewer before approving (it is 609 now). Nothing is cut automatically."
  2. **On Re-propose.** The prompt is worked out again for the new text.
  3. **While the officer edits.** `POST /officer/cases/{id}/sms-check` (read-only) returns the parts, the limit, the
     encoding, which characters forced Unicode, and the same prompt. The officer screen shows it under the farmer
     text.
  4. **At approval.** Approving a text that won't fit is refused with a 400 carrying the same prompt. Nothing is
     saved and the case stays open for editing. Otherwise the case would be released but could never reach the
     farmer.
- The send-time check stays as a backstop. If something over the limit still reaches `send()`, nothing is sent and
  the delivery is recorded as "not sent, nothing was cut: too long for SMS: ..." in the same wording.
- For scale, AgriReach's offline farmer text for "When should I plant maize in Ejura?" is 574 characters, which is 4
  standard parts. The same text with one curly apostrophe (’), or with the farmer's Twi question quoted above it,
  needs 9 or 10 parts. Twi, Ga, Ewe and Dagbani replies need to be about 268 characters at the default limit.
- Each part is billed as a separate SMS.

## Configuration (nothing is mounted or sent unless `SMS_ENABLED=1`)

| Variable | Meaning |
|---|---|
| `SMS_ENABLED` | `1` to mount the inbound route and register the channel; default `0` |
| `AT_USERNAME` | app username; always `sandbox` in the sandbox |
| `AT_API_KEY` | API key from the Africa's Talking dashboard, sent as the `apiKey` header |
| `SMS_WEBHOOK_TOKEN` | your own random string, 20+ characters, the last part of the callback URL |
| `AT_SENDER_ID` | optional registered alphanumeric sender ID or short code, sent as `from` |
| `AT_SANDBOX` | `1` (default) sandbox, `0` live |
| `SMS_MAX_SEGMENTS` | default `4` |

If `SMS_ENABLED=1` and something is missing or inconsistent, startup fails with a message naming it. That covers
a missing username, key or token, `AT_SANDBOX=1` with a username other than `sandbox`, a token under 20 characters,
and a segment limit below 1. Keep real values in a local env file outside the repo. `Config.__repr__` hides the key
and the token, and neither is logged.

## Inbound security: what protects the callback, and what doesn't

Africa's Talking's notification docs describe the callback as a plain form POST, with no signature or shared-secret
header (unlike WhatsApp's `X-Hub-Signature-256`). Anyone who learns the URL can post a fake "incoming SMS". The
adapter therefore:

- puts a secret token in the path and compares it in constant time, answering 404 to anything else;
- refuses bodies over 16 KB and anything without `from` and `text`;
- ignores senders that aren't an international number;
- removes the token from uvicorn's access log. **Other logs are not covered.** A reverse proxy, load balancer or
  hosting platform in front of the app will log the full URL unless it's configured not to.

A forged callback can at worst create a case for the officer and send the fixed acknowledgement or consent prompt
to the number it names, which costs money. It cannot release an answer, because that still needs a signed-in
officer. Before real use, also consider:

- restricting the route to Africa's Talking's source IPs, if they publish them (not found; ask them);
- serving it only over HTTPS;
- rotating the token if it leaks.

## Still needed before any real use (none done)

1. **Account.** An Africa's Talking account and a live app (username and API key). Test first in the sandbox
   (`AT_USERNAME=sandbox`, `AT_SANDBOX=1`) with its simulator.
2. **A number farmers can text.** An alphanumeric sender ID can only send, so farmers can't reply to it. Two-way
   SMS needs a short code (dedicated, or shared with a keyword) or a long number, with the incoming-messages
   callback URL set to `https://<host>/channels/sms/inbound/<SMS_WEBHOOK_TOKEN>` in the dashboard (SMS -> SMS
   Callback URLs -> Incoming Messages). Ask Africa's Talking Ghana what's available and what it costs.
3. **Sender ID in Ghana.** The AT docs say test messages with the default sender only reach Airtel numbers in
   Kenya, and every other country needs a sender ID applied for through the dashboard. A third-party guide (e-MC,
   below) says Ghana approves alphanumeric IDs of up to 11 characters per network (MTN, Telecel, AirtelTigo), in
   about 9 days. That's unconfirmed.
4. **Costs are unknown for this use.** AT's public pages list Ghana bulk SMS from GHS 0.018 to GHS 0.053 per
   message depending on volume. Short code and inbound costs aren't listed. Every reply part is billed, including
   acknowledgements, consent prompts and opt-out confirmations.
5. **Sending hours and traffic class.** Third-party guidance says promotional SMS in Ghana is limited to 8 am to
   7 pm. Advisory replies are probably transactional, but check with the provider.
6. **Not built.** Delivery reports (the AT delivery-report callback), retries for failed sends, rate limits,
   monitoring, and the newer JSON endpoint `/version1/messaging/bulk`. That endpoint requires `senderId` and its
   sandbox is listed as "coming soon", so the adapter uses the form endpoint the official Python SDK uses.
7. **Consent wording.** The consent wording, privacy notice and data-retention rules need legal review against
   Ghana's Data Protection Act 2012 (Act 843), as for WhatsApp.
8. **Language.** Replies in Twi or Dagbani cost more than twice as many parts (UCS-2). Whether farmers' phones
   display ɛ and ɔ correctly needs checking on real handsets.

## Sources (checked 25 Oct 2026)

- Send SMS (form endpoint `/version1/messaging`, fields, status codes, example response):
  https://developers.africastalking.com/docs/sms/sending/bulk_(legacy)
- Newer JSON bulk endpoint (`/version1/messaging/bulk`, sandbox "coming soon"):
  https://developers.africastalking.com/docs/sms/sending/bulk
- Authentication (`apiKey` header; sandbox username is always `sandbox`):
  https://developers.africastalking.com/docs/authentication
- Incoming-message callback fields and dashboard path: https://developers.africastalking.com/docs/sms/notifications
- Default sender only for Kenya Airtel; sender IDs through the dashboard: https://developers.africastalking.com/docs/sms/overview
- Official Python SDK (form endpoint, `from`, `bulkSMSMode`):
  https://github.com/AfricasTalkingLtd/africastalking-python/blob/master/africastalking/SMS.py
- Ghana prices (public page, not a quote): https://africastalking.com/sms/bulksms and https://ghana.africastalking.com/
- Ghana sender ID rules (third party, unconfirmed): https://api.e-mc.co/en/resources/country-rules/

The developers.africastalking.com pages are behind a bot check, so they were read through search-engine copies,
not loaded directly. Re-check them before going live.
