# Phase 2: inbound durability

Checkpoint 1 introduces an additive SQLite version 4 inbox table and three database operations: enqueue, claim and finish. This checkpoint is isolated from the live webhooks and does not yet solve message loss. No merge or deployment is authorized.

The table stores the provider message identifier, channel, original payload, processing state, attempts, optional case association and timestamps. Enqueue commits before acknowledgement. Claim uses a SQLite immediate transaction so only one worker can claim a pending item. Finish requires the same claim identifier.

A worker crash after case creation but before completion is ambiguous. Such a record must not be blindly retried, since that could duplicate cases or system replies. Recovery needs reconciliation with case and outbound evidence.

Next work: connect authenticated webhooks to persistent enqueue, build a durable worker and recovery mechanism, make held consent and location messages transactional, and extend opt out and retention deletion to the inbox.

Tests required: duplicate callbacks, concurrent claims, crash recovery at each boundary, migration integrity, privacy deletion, full Python regression suite, safety replay, and speech tests.

The existing officer approval and delivery safety rules must remain unchanged. This is not a production readiness signoff.
