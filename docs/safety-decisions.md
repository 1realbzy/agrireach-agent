# Engineering decisions and migration recovery

## Acknowledgement response and identity

HTTP 409 is intentional for an application workflow conflict requiring explicit warning acknowledgement. HTTP 428 describes HTTP conditional requests and is not this API contract. Critical holds use 422 and failed assessments use 503. Acknowledgement binds the exact case/context/text/credential and stable warning rule, sentence and evidence identity; model explanation prose is retained as evidence but does not invalidate an otherwise identical warning challenge.

## Source applicability and unsupported materials

Only known registered topics can be excluded from S1; the immutable question plus reply determine applicability. Unclassified context and changed source hashes keep safeguards enabled. C1 was corrected and verified before introducing this filter. Unknown material instruction shapes require nonacknowledgeable review even on nonchemical cases; this conservative choice can also hold legitimate nonchemical material instructions. Source hashes deliberately require review after corpus edits. A typo correction requires explicit policy/source registration review, not automatic hash acceptance.

## Why full sentences and explicit templates

Word overlap accepted a negated consultation referral in the baseline. The shared gate therefore preserves polarity and conditions and holds unrecognised chemical paraphrases. This can restrict valid wording. It is intentionally not described as semantic proof.

## Why a revision and a fingerprint

A status alone does not identify the case content assessed. Revisions reject stale officer requests. Immutable snapshots and fingerprints also detect changed source contents and approval payloads. They do not protect against a database administrator who can remove triggers or edit the application.

## Why models run outside transactions

Holding the SQLite writer lock during a network call blocks other cases and extends failure windows. The service assesses first and checks the entire snapshot again under the write lock. A conflict requests a reload rather than trusting an obsolete result.

## Why unknown is distinct from failed

A timeout can occur after a provider accepted a request. Automatically retrying that result risks duplicate farmer messages. Unknown and interrupted claims remain held until provider evidence resolves the outcome. A retryable failure must establish nonacceptance.

## Migration and recovery

Version one adds revisions and durable submissions/assessments. Version two adds immutable approvals, acknowledgement challenges, audit events and delivery jobs/attempts. The migration ledger carries checksums. Unknown versions or checksum differences refuse startup. Each upgrade transaction commits its own ledger row with its DDL and backfill; an interrupted version two upgrade can leave a complete supported version one database.

The current connection path initializes legacy tables and calls the versioned upgrade. Nonempty legacy databases receive a SQLite backup before version one. A verified backup restore test and version two rollback test exist. A standalone operator CLI and a backup before upgrading a populated version one database are implemented. Broader fault injection remains a verification limitation. Run `PYTHONPATH=src python -m agrireach.migrations PATH` offline, then use the same command with `--verify-only` for a read only integrity and ledger check.

Historical approved/released rows are copied as legacy_unvalidated provenance without changing their original case rows. They cannot be newly released through the upgraded workflow without fresh assessment. Previously published historical text remains available through the web view with assessment_status=legacy_unvalidated; it cannot be sent anew.

Do not restore a backup over newer approval or audit evidence. Stop writers and sending first, preserve the failed database and any newer evidence, validate a separate restored copy and prefer a forward repair. Never start the vulnerable baseline implementation against an active upgraded database. There is no destructive automatic down migration.
