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
Legacy cases have no row. Migration 6 creates the three SMS tables and records
its checksum in the same explicit SQLite transaction. The migration checks
the ledger and schema before commit and checks the committed state before
reporting success. Missing bootstrap objects in a versioned database require
investigation. Partial, altered, or augmented SMS schemas are rejected.

If you can establish that a v5 copy contains the complete SMS schema from the
pre-ledger release, run `python -m agrireach.migrations PATH --adopt-legacy-sms`
to explicitly adopt that schema. Startup refuses unrecorded SMS tables.
Quiesce writers for offline migration and protect the backup as carefully as
the database. The migrator verifies SQLite integrity and foreign keys before
publishing a backup alongside the source. An interruption can leave a dedicated
`.agrireach-backup-*` staging directory. The CLI rejects those paths and old
`.partial` artifacts. A retry creates its own staging directory and preserves
the earlier artifact for inspection.

Run `python -m agrireach.migrations PATH --verify-only` to verify one read-only
snapshot, including all nine revision and evidence triggers, required tables,
migration records, integrity and foreign keys.

Retention purge deletes stored web numbers on the same cutoff as other contact
data. Cases remain.

## Migration 2 checksum investigation

The reviewed checkpoint and every available revision containing migration 2,
starting at `bb82ed9`, hash to
`7b197e86411612805f89cc83e24011853cb7c046d21193ab10dfe7489274c5c2`.
That matches the pilot ledger recorded by the audit. Hashing only the seven
literal statements gives the audit's other value,
`5283534006cb19119acefc776300c7e83691758ff67507f173b5fc2c801996f7`.
It omits the eight immutable-evidence triggers appended when the module loads.
This reproduces the discrepancy without changing any migration definition.

Proposed follow-up, subject to separate authorization: correct the audit method
to hash the complete runtime statement list from the pinned source. On a
verified backup or copy, confirm the original ledger and nine trigger
definitions before rehearsing migration 6. No ledger repair is indicated by
these hashes. If a verified copy fails strict validation, stop and investigate
the evidence before making any changes.

Logs, audit details, model prompts and public responses use a masked number or
omit it. The officer acknowledgement route returns the mask only.

## Reconciliation and logging

Authenticated reconciliation records the case, job, officer, revision,
disposition and timestamp. The legacy evidence field remains required as an
attestation that the officer checked a provider record. Its content is discarded.
Keep provider records in the authorised provider system.

If historical audit rows contain private data, restrict access to the database,
its exports and backups. Inventory the affected event IDs and copies in a
restricted environment. Obtain explicit approval for any evidence-preserving
redaction, retention or access-control changes. Document the approved method,
audit trail, and verification before applying it to any original record.

Uvicorn access logging retains the HTTP method, version and status. It omits
raw request targets and peer addresses. The inbound SMS webhook keeps a fixed
route label. The supported API launchers disable WebSocket upgrades. HTTPX and HTTP Core logging in the API process keeps only
fixed HTTP diagnostics. These controls apply to the application's loggers.
Configure reverse proxies, load balancers, external tracing and other
infrastructure to avoid recording private URLs, headers and request bodies.

## Known limitations

* No mNotify account is configured. Live mode was exercised with mocked HTTP only.
* The [quick-SMS contract](https://readthedocs.mnotify.com/) shows the
  local-number recipient list and explicit unscheduled fields. Only its HTTP
  200 success with body code 2000 and a campaign ID confirms acceptance.
  HTTP 422 indicates a definite validation refusal and HTTP 429 indicates rate
  limiting. Unrecognized body codes and server errors do not confirm acceptance.
* Provider acceptance is not handset delivery. The delivery-report endpoint was not called.
* The original Windows pilot database was not opened. It remains REQUIRES LOCAL PC.
* Inbound SMS is unchanged. In `channels/service.py`, `_location_reply` files a second case when a reply is not a location confirmation and contains more than three words. A later SMS, including a clarification answer, is also filed by `_file` as a new case because that path does not pass the existing case id. The web supplement path still updates the same draft. Two-way SMS is out of scope.
* SMS delivery of approved advice is not implemented.
