# Local engineering evidence

This package records implementation and developer tests, not independent QA. Independent Grok Bot engineering/security/maintainability review is pending. Acceptance is not signed off.

## Reproducible baseline and environment

Repository: https://github.com/1realbzy/agrireach-agent

Baseline: 94bff8880f744e50d6df4d515bdc8c6b7a110198.
Branch: work/safety-hardening.
Main stays at the baseline. Checkpoint SHAs are in implementation-progress.md; the final SHA and working tree status are supplied with the review bundle.

Python 3.12.14; SQLite 3.53.1. Installed project versions: mcp 1.30.0, mcp-server-fetch 2026.10.10, langgraph 1.2.15, FastAPI 0.143.0, Pydantic 2.14.1, httpx 0.28.1, OpenAI 3.29.0, pytest 9.1.1, Streamlit 1.65.0. No runtime dependency was added.

## Changed responsibilities

| Area | Changes |
| :--- | :--- |
| safety_gate.py | Full sentence/template policy, source requirement mapping, evidence and protective negation handling |
| approval.py | Detached context snapshots, structured source/model assessments, atomic approvals/audit and acknowledgement consumption, release fingerprints |
| migrations.py | Checksum ledger, transactional schema versions 1–2, backups, legacy provenance, future schema refusal and offline verification CLI |
| delivery.py | Unique dispatch claims, matching attempt completion, 15 minute expiry to unknown, evidence based reconciliation |
| db.py | Enforced workflow delegation, revisions, explicit text, safe reopening and transaction compatible legacy logging |
| api.py and ui.py | Revision and acknowledgement contracts, exact voice preview approval, actionable errors and recovery, immutable farmer output |
| channel base/service/SMS/WhatsApp/simulator | Structured outcomes, provider identifiers, no duplicate dispatch or unsafe retry; registered simulator officer identity |
| judge.py | Duplicate/unexpected verdict item rejection |
| scripts/run_evals.py | Explicit source backed farmer text and revision for the evaluation approval |
| scripts/replay_safety.py | Offline historical replay with explicit exclusions and no personal data in its output |
| Tests | Original bypasses, frozen policy data, new transaction/migration/concurrency cases and explicit legacy contract updates |
| Documentation | Five focused guides, progress/evidence reports, current behaviour notes and appended EVALS evidence |

LangGraph orchestration, custom MCP tools, model choices, source corpus, source licences and historical raw evaluation evidence are not redesigned or rewritten.

## Safety and error contracts

S1 requires each applicable chemical safeguard, or its specifically registered alternative. S2 blocks established reversals, preserving benign negative statements. S3 requires chemical instructions to be complete source sentences or accepted complete templates; unknown chemical wording is held. Source sentence matching establishes provenance, not agricultural correctness.

HTTP 422 reports safety_blocked/review_required, 409 reports a conflict or acknowledgement_required, and 503 reports an unavailable required assessment. No critical finding or model outage can be routinely acknowledged away. Informational zone concerns remain displayed and logged. Exact policy registry and examples are in safety-rules.md and safety_gate.py.

Approval records bind source contents, raw farmer text, officer text, policy, revision, credential and warnings. Spoken scripts are also bound where enabled. The agent cannot approve through MCP. Direct Python workflow calls remain trusted local code; a database administrator can remove triggers and rewrite SQL and is outside this security boundary.

## Migration and recovery evidence

Version one creates revisions and durable submission/assessment evidence. Version two adds immutable approvals, challenges, audit and delivery tables. Version ledger, DDL and backfill commit together per version; rollback can leave the complete prior supported version, never a half committed version. Unsupported/incomplete upgraded layouts refuse bootstrap.

Tests verify a legacy case row is preserved exactly, its prior publication is recorded as legacy_unvalidated, the SQLite backup opens with matching content and integrity, repeated migration is a no op, injected version two SQL failure leaves only version one, and unknown future schema does not regain dropped legacy columns. Foreign key and integrity checks pass in test databases. These are synthetic fixtures, not a migration of production data.

Offline commands:

```bash
PYTHONPATH=src python -m agrireach.migrations DATABASE_PATH
PYTHONPATH=src python -m agrireach.migrations DATABASE_PATH --verify-only
```

Stop writers/sending before upgrading. Restore only a verified separate backup while stopped and only before new evidence exists. After new writes, preserve the upgraded database and newer evidence and use a forward repair or explicit operator recovery; never discard new audit records through an automatic destructive rollback.

## Commands and measurements

```bash
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m pytest -q tests/test_safety_checkpoint1.py tests/test_safety_checkpoint2.py
PYTHONPATH=src python -m pytest -q tests/test_mcp.py tests/test_agent.py tests/test_channels.py
PYTHONPATH=src python scripts/replay_safety.py
AGRIREACH_SOURCE_CHECK=0 AGRIREACH_RAINFALL=off PYTHONPATH=src python scripts/run_evals.py core
```

The original baseline produced 619 passed and 1 optional speech module skipped. Final full suite: **738 passed, 1 skipped in 178.75 seconds**. The skipped item is the unavailable optional real speech module. This run includes the final migration refusal, concurrency, strict safeguard mapping, critical warning classification, voice preview and claim expiry changes. No failing test was skipped to produce a pass. The real speech module remains unavailable because its optional dependency/model cache is absent.

Core offline evaluation completed successfully: 8 agent runs, 0 model calls attempted, release without approval blocked and explicit source backed officer approval released. This is not a fresh live evaluation. The project still supports live model configuration, but no endpoint/key was configured here. No real SMS/WhatsApp transmission or TTS intelligibility claim is made.

Frozen deterministic fixture measurements: 0/40 legitimate false blocks; 40/40 unsafe examples blocked, 0/40 unsafe releases in that bounded gate set. Before the final explicit consultation bypass rule, two unsafe cases were only held; that gap was corrected without changing fixture labels. Three uncertainty examples are also S1 violations, so their blocks do not demonstrate calibrated uncertainty detection.

Historical replay: 42 records, 37 assessed, 5 explicitly excluded. All 15 deliberate unsafe records are blocked. Historically normal candidates: 9/22 pass, 9/22 blocked, 4/22 held. Two held candidates are Twi; English compatibility holds are 11/20. These are retrospective compatibility measurements against author grades, not external agricultural validation. Deterministic passes requiring a judge are labelled as such and are not counted as fresh complete approvals. The historical zero false block target remains unmet/unproven; see implementation-progress.md for the required policy resolution.

## Bypass and concurrency evidence

The six reproduced API attack patterns return blocks and retain pending_review. Full submitted text remains in advisory_submissions. The CLI regression invokes the actual simulator command with a valid registered token and unsafe text, and verifies no outbox message. Missing direct database farmer text cannot expose the internal draft.

Real temporary SQLite and synchronized threads verify one winning approval, one winning acknowledgement consumption and one active external dispatch. Tests cover changed officer, text, case, source, policy, credential and expiry; replay after consumption; source mutation during assessment; audit failure rollback; source change before release; immutable approval updates; interrupted and expired send claims; and no automatic resend of unknown outcomes. Low level channel adapters remain transport primitives, not authenticated public approval endpoints.

## Remaining risks and review gate

Source applicability is the unresolved material compatibility issue. All cited chemical passages currently remain in scope, including incidental retrieval hits. Weakening that policy would require an explicit decision. No claim that 13 historical holds are all agronomic false positives is justified without review.

The independent team must challenge the final diff, source/template consistency, bypasses, migration failure handling, real provider rejection semantics, races, acknowledgement security, logging redaction, UI behaviour, code readability and documentation. Passing these developer tests is insufficient for independent approval. No universal zero bypass, field readiness or exactly once delivery claim is made.


## Final local validation record

* Full suite: 738 passed, 1 skipped; zero failures.
* Final focused gate/transaction/usage/SMS length/channel group: 143 passed.
* Migration/agent/MCP group after future schema refusal: 129 passed.
* Offline core evaluation: process exited successfully; 8 runs, 0 attempted model calls.
* Migration CLI create/upgrade and read only verification: both exited successfully; verification preserved database bytes.
* Python compilation and git diff whitespace checks passed.
* Frozen safety fixtures, corpus, field evidence JSON and historical raw run files have no changes from their committed versions.

These groups overlap and are not additive sample counts. No independent review has been performed. Historical compatibility remains an unresolved acceptance criterion, notwithstanding the passing automated suite.
