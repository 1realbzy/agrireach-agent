# Safety hardening progress

Baseline: 94bff8880f744e50d6df4d515bdc8c6b7a110198.
Branch: work/safety-hardening. Nothing pushed or deployed.

Fixture freeze: 7ce1717, 40 source based legitimate cases, 40 unsafe cases and 3 uncertainty cases. This is a bounded policy set, not agricultural validation.

Checkpoint 1: shared deterministic gate, database enforcement, explicit text/revision requirements, raw text preservation, API structured blocks, simulator credential requirement, foundational versioned schema and durable submission/assessment records. Model dependent candidates are held pending checkpoint 2. Local MCP and agent integration tests pass. Full legacy suite has not yet been adapted or run against the changed approval contract; its former warning and release expectations are intentionally incompatible and must receive explicit contract updates rather than exemptions.

Checkpoint 2 implementation: immutable approvals, atomic audit, secure acknowledgement and delivery jobs. The checkpoint 1 branch is not deployable: release still uses the baseline implementation until checkpoint 2.

Checkpoint 3 next: UI, documentation and complete regression verification. Separate Grok QA remains pending.


Checkpoint 1 commit: 6e17ce6. Targeted validation: 107 passed.
Checkpoint 2 targeted validation: 115 passed, including the frozen gate fixtures, exact approval fingerprints, immutable records, atomic audit rollback, concurrent dispatch and approval, interrupted claims, acknowledgement single use, judge failure, legacy data/backup preservation, migration rollback, MCP and agent integration.
The complete legacy suite is being run to inventory changed contract expectations. No failing tests have been removed or skipped. Checkpoint 2 still needs broader migration fault injection and acknowledgement race coverage before final acceptance. The schema now has versions 1 and 2; historical approvals are legacy_unvalidated.
