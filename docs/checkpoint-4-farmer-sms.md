# Checkpoint 4: farmer phone number and mNotify acknowledgement

This note is the recovery and privacy record for the administrative acknowledgement.
It does not authorize a live send. Approved agricultural advice is still released
only through the existing officer approval path.

## What is sent

After a web case is committed, and only when the farmer checked SMS consent and
entered a valid Ghana mobile number, AgriReach can queue one fixed text:

`AgriReach: We have received your farming question. Reference: {case id}. We will notify you when an extension officer has reviewed the advice.`

The case id is the only inserted value. The question, the draft, the access
token and the phone number are not inserted. This text is not agricultural advice.
Officer approval is still required before any advice can be released.

## Modes

`MNOTIFY_SMS_MODE` is `disabled` unless it is exactly `simulated` or `live`.
Any other value, including a missing variable, is disabled.

* Disabled: the consented number may be stored. No job is queued and no provider is called.
* Simulated: a local result is stored and labelled simulated. Nothing is sent.
* Live: `POST https://api.mnotify.com/api/sms/quick` is called only when `MNOTIFY_API_KEY` and `MNOTIFY_SENDER_ID` are present. The sender must be 1 to 11 characters and must not be all digits. The host must be `api.mnotify.com`. A missing or rejected setting does not call Africa's Talking.

`SMS_ENABLED` and the Africa's Talking settings do not send this acknowledgement.

## States

Jobs are separate from advice `delivery_jobs`.

* `pending` can be claimed.
* `sending` is claimed. A second worker does not send.
* A `sending` claim older than 15 minutes becomes `unknown`.
* `definitely_failed` means the provider refused the message, or the request never connected. A later dispatch may claim it.
* `unknown` means the request may have reached mNotify. It is not claimed again.
* `accepted` means the provider, or the simulator, accepted the campaign. It does not mean a handset received it.
* `undeliverable` means the stored number was removed before send.

An officer can record provider evidence for an `unknown` job at
`POST /officer/acknowledgement-jobs/{id}/reconcile`. That action does not send.

## Failure boundaries

The case commit finishes before the acknowledgement job is inserted. The provider
is called only after the claim commits. If queueing the job fails, the case stays
saved, no message is sent, and the farmer is told not to submit the question again.
If the provider fails or the outcome is unknown, the case stays saved.

## Phone numbers

Numbers are stored as E.164 on `farmer_sms_contacts`, only after explicit consent.
Legacy cases have no row. The tables are created with `CREATE TABLE IF NOT EXISTS`
when the application opens a database, including a database already at schema
versions 1 through 5. The migration ledger is not given a new version, because
existing ledger checks require versions 1–5. Retention purge deletes stored web
numbers on the same cutoff as other contact data. Cases remain.

Logs, audit details, model prompts and public responses use a masked number or
omit it. The officer acknowledgement route returns the mask only.

## Known limitations

* No mNotify account is configured. Live mode was exercised with mocked HTTP only.
* mNotify does not publish a numeric rate limit. Code 405 is documented as Too Many Requests.
* The quick-SMS curl sample includes schedule fields. They are omitted because this message is not scheduled.
* Provider acceptance is not handset delivery. The delivery-report endpoint was not called.
* The original Windows pilot database was not opened. It remains REQUIRES LOCAL PC.
* Inbound SMS is unchanged. In `channels/service.py`, `_location_reply` files a second case when a reply is not a location confirmation and contains more than three words. A later SMS, including a clarification answer, is also filed by `_file` as a new case because that path does not pass the existing case id. The web supplement path still updates the same draft. Two-way SMS is out of scope.
* SMS delivery of approved advice is not implemented.
