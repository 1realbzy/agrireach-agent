# Phase 2: inbound durability

Checkpoint 1 introduces an additive SQLite version 4 inbox table and three database operations: enqueue, claim and finish. This checkpoint is isolated from the live webhooks and does not yet solve message loss. No merge or deployment is authorized.

The table stores the provider message identifier, channel, original payload, processing state, attempts, optional case association and timestamps. Enqueue commits before acknowledgement. Claim uses a SQLite immediate transaction so only one worker can claim a pending item. Finish requires the same claim identifier.

A worker crash after case creation but before completion is ambiguous. Such a record must not be blindly retried, since that could duplicate cases or system replies. Recovery needs reconciliation with case and outbound evidence.

Next work: connect authenticated webhooks to persistent enqueue, build a durable worker and recovery mechanism, make held consent and location messages transactional, and extend opt out and retention deletion to the inbox.

Tests required: duplicate callbacks, concurrent claims, crash recovery at each boundary, migration integrity, privacy deletion, full Python regression suite, safety replay, and speech tests.

The existing officer approval and delivery safety rules must remain unchanged. This is not a production readiness signoff.

## Checkpoint 1 review corrections

The review found seven issues. This branch now uses a separate SQLite connection for inbox writes to avoid committing unrelated caller transactions; explicit conflict handling; generated claim tokens; conservative transition of interrupted processing to `uncertain`; and a terminal-state-only purge primitive. Tests cover these properties. A second connection cannot write while the caller holds a SQLite write transaction, so callers must not invoke inbox functions inside an active writer transaction. No automatic replay or outbound send is performed.

**Still open before checkpoint 2:** a scheduled purge and STOP integration; error/reconciliation reason evidence; complete migration upgrade matrix for versions 1 through 3 and corrupt ledgers; durable case-to-inbox association; worker recovery decisions based on case and outbound evidence. Existing live webhook processing is unchanged. The audit findings are not all closed. Do not merge or deploy this foundation as a complete reliability fix.

## Review remediation checkpoint 2

SQLite version 5 adds a sender association and outcome reason without changing the version 4 checksum. Inbox operations now close their separate SQLite connections and roll back on failure. STOP erasure removes sender-associated inbox records. Existing retention purge deletes expired inbox events, including unprocessed events, rather than preserving sensitive payloads indefinitely. Failed and uncertain completion requires an explicit reason; interrupted claims receive a reconciliation reason. Regression coverage includes sender erasure, expiry, evidence and historical migration paths.

**Not yet complete:** The live webhook handlers do not persist inbound events into the inbox. A scheduled retention job, case-to-inbox atomic linkage and recovery decision logic still need implementation and verification. The current sender association is optional for legacy/foundation callers and must become mandatory at the webhook boundary. This branch remains non-deployable and must not be merged as a full Phase 2 fix.

## Completion checkpoint (2026-11-05)

The earlier sections are historical checkpoints. Authenticated SMS/WhatsApp callbacks now commit inbox events before acknowledgement and run claim-once durable processing. The remaining case-link gap is closed: the worker passes its claim through LangGraph to the MCP action tool; case insertion and inbox association share one immediate SQLite transaction. No historical migration or immutable approval evidence is rewritten. A second creation for the same claim is refused; failed/uncertain completion preserves the existing case association and cannot replace it with a different case.

STOP deletes sender-scoped inbox entries, invalidating active claims. Durable case creation and contact attachment revalidate that claim inside a write transaction, so a worker cannot recreate an erased contact after STOP. System sends revalidate the claim; advisory transport rereads the committed contact immediately before calling the channel. A provider call already underway, or STOP in the last check-to-call interval, cannot be cancelled. Sending/unknown jobs stay nonretryable until verified reconciliation. This is a documented limitation, not a promise of exactly-once external delivery.

Recovery remains conservative: pending means unclaimed; completed means a case or classified system outcome was returned; failed requires a reason; stale processing becomes uncertain with its case evidence preserved. Case creation alone does not establish successful downstream processing or delivery. `scripts/reconcile_inbox.py` reports counts and linked/missing evidence, defaults to dry run, and never invokes an agent or channel. Stop writers before applying reconciliation. Pending events are not automatically drained on server startup; uncertain events must never be reset for automatic replay. Consent/location batches can contain multiple questions but a durable claim permits only one case; later attempts are held uncertain for manual review rather than creating duplicates. The legacy simulator and direct service path remain outside the durable provider inbox.

See [Windows pilot guide](windows-local-pilot.md) for the deliberately limited offline trial, setup, officer registration, expected results and acceptance checklist. Controlled local testing does not establish readiness for live messaging or production.
