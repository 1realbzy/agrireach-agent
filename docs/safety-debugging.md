# Debugging approval and delivery

This branch has passed local automated regression checks, but acceptance is pending the historical compatibility decision and independent review. Consult implementation-progress.md for actual status. Do not treat these developer checks as deployment authorisation.

## Trace a case

Use the authenticated officer case endpoint for the case and legacy tool_log. Inspect the SQLite database locally with a read only connection for the newer records. Never copy contact numbers, authentication tokens or complete submissions into general logs.

The evidence chain is cases.id to advisory_submissions.case_id, safety_assessments.case_id, approvals.submission_id and approvals.assessment_id. approvals.payload contains the exact approved text and assessment snapshot. delivery_jobs.approval_id identifies the payload being dispatched. delivery_attempts.job_id and claim_id identify the particular send. audit_events contains structured events with referenced IDs in details.

Useful queries, with case_id supplied as a parameter:

```sql
SELECT id, revision, status FROM cases WHERE id = ?;
SELECT id, event_name, actor, details, created_at FROM audit_events WHERE case_id = ? ORDER BY id;
SELECT id, revision, provenance, fingerprint FROM approvals WHERE case_id = ? ORDER BY id;
SELECT j.* FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id = ?;
```

Full text and snapshot records are officer restricted evidence, not application log output. Inspect them only when needed. A source or text fingerprint mismatch requires fresh approval; never repair a hash to force a release. A stale revision requires reloading the case, not incrementing the request number blindly.

## Failure diagnosis

HTTP 422 carries deterministic findings or a review hold. Inspect rule_id, sentence, evidence and recovery. No routine acknowledgement overrides these outcomes. HTTP 409 can indicate a stale revision or an eligible acknowledgement challenge. HTTP 503 means the required model assessment did not succeed. A failed judge is never evidence of support.

Delivery state sending means a committed dispatch claim exists. unknown means acceptance cannot be established. Neither state permits automatic retry. An interrupted claim can be marked unknown using delivery.interrupted from trusted operator code. Reconciliation requires externally verified provider evidence, retained with the action. Do not use a speculative note to permit another send. Provider acceptance does not prove handset receipt.

## Targeted reproduction

```bash
PYTHONPATH=src python -m pytest -q tests/test_safety_checkpoint1.py
PYTHONPATH=src python -m pytest -q tests/test_safety_checkpoint2.py
PYTHONPATH=src python -m pytest -q tests/test_mcp.py tests/test_agent.py tests/test_channels.py
```

The first group covers frozen policy examples and original API bypasses. The second uses real temporary SQLite files, fault injection and separate connections for concurrency. These are developer tests, not independent QA or agricultural validation.
