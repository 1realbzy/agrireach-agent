# AgriReach codebase audit, 5 November 2026

## Scope and evidence

Static review of the complete 35-module `src/agrireach` Python tree, repository structure, 84 test/fixture files, the CI workflow, knowledge corpus, and the existing security, safety, delivery and migration regression tests. The initial focused changes passed GitHub CI, including strict safety replay and migration verification. Later changes in this branch require a fresh CI result. This is not a live penetration test, independent agronomic review, field validation or production-readiness certification.

Review baseline: `main` at `3627ea2b8bbc3852b9c8fc29c5ce3e64f3460bdc`. Changes are isolated in `audit/security-reliability-2026-11-05` and PR #4.

## Findings

| ID | Severity | Component | Evidence and risk | Status |
| --- | --- | --- | --- | --- |
| A01 | High | `api.py`, `db.py`, `ui.py` | `GET /farmer/cases/{id}` returned approved text for a sequential case number with no farmer authorization. | Remediated for newly issued web case tokens, pending CI |
| A02 | High | `channels/service.py`, `db.py` | `first_time_seen` commits the inbound message ID before agent processing; failure or crash makes a retry look duplicate. | Open; requires durable processing states and recovery semantics |
| A03 | High | `channels/whatsapp.py` | Media URL was downloaded with bearer credentials without a destination allowlist or size cap. | Remediated with HTTPS host restrictions, redirect refusal and streaming size limit; pending broader security testing |
| A04 | Medium | `api.py` | Public `/ask` accepted arbitrarily long or blank questions; simulator read full audio before checking size. | Remediated and initial CI passed |
| A05 | Medium | `channels/whatsapp.py`, `channels/sms.py` | Webhook acknowledges HTTP 200 before background processing; a process crash can lose work. | Open; durable inbox/worker required |
| A06 | Medium | `channels/service.py`, `db.py` | Consent and location held messages are removed before processing completes, risking loss on exceptions. | Open; atomic claim/ack design required |
| A07 | Medium | `channels/service.py`, `api.py` | Audio and text retention depends on periodic inbound calls or manual cleanup; no guaranteed scheduled purge. | Open; operational scheduling required |
| A08 | Medium | `api.py`, `ui.py` | Legacy web cases created before access tokens were issued cannot be retrieved through the protected farmer endpoint. | Open; design authenticated recovery/claim flow, never automatically expose old cases |
| A09 | Medium | `channels/whatsapp.py` | Host allowlist is a partial SSRF mitigation, not DNS pinning; redirects are refused. Media lookup ID should be constrained and end-to-end mocked. | Open for further hardening |
| A10 | Medium | `agent.py`, `mcp_server.py` | Soybean search fallback was previously present; current main already requires explicit crop and tests cover omission. | Verified corrected before this audit branch |
| A11 | Medium | `agent.py`, `knowledge.py`, `zones.py` | Retrieval uses curated keyword ranking and region heuristics; coverage, agricultural validity and crop/zone generalization need independent domain evaluation. | Open, validation required |
| A12 | Medium | `judge.py`, `claim_check.py`, `safety_gate.py` | A model judge can misclassify claims; deterministic safeguards are valuable but not proof of agronomic safety. CI mocks the judge. | Open; independent live-model red-team and officer validation required |
| A13 | Medium | `requirements.txt`, `.github/workflows/regression.yml` | Dependency versions are pinned except `python-dotenv`; workflow uses SHA-pinned actions but no dependency vulnerability scan. | Open; add lock/hash policy and vulnerability audit |
| A14 | Low | `api.py` | Health endpoint exposes draft mode; useful for local operations but not needed on public deployments. | Open; deployment configuration review |
| A15 | Medium | `channels/sms.py` | SMS webhook uses a secret in the URL because provider callback signatures are unavailable; requires TLS, token rotation and access log controls. | Open, deployment risk |
| A16 | Medium | `migrations.py`, `db.py` | New farmer access tokens require a versioned, non-destructive SQLite migration and compatibility tests. | Implemented v3, pending CI |

## Non-negotiable invariants

1. Agent and MCP writes must not approve or release.
2. An officer must approve the exact farmer-facing text with immutable evidence.
3. S1, S2 and S3 safety holds must not be bypassed by acknowledgement.
4. Release must revalidate revision, source, policy and approval fingerprint.
5. Ambiguous delivery outcomes remain unknown until evidence-based reconciliation; never automatically resend.
6. Opt-out and retention controls must prevent sending.
7. The farmer-facing API must not expose internal drafts or other farmers' answers.
8. Never put case access tokens into URL paths or query strings; use the `X-Case-Access-Token` header.

## Verification matrix

- Full `python -m pytest -q` including `tests/test_api.py`, `tests/test_whatsapp.py` and migration tests.
- `python scripts/replay_safety.py --strict`.
- `python scripts/verify_legacy_migration.py`.
- Speech test job and safety remediation regression tests.
- Manual negative tests: case ID enumeration, wrong case token, oversized inputs, malicious media URL, oversized media, redirect response, missing crop, stale approval, unknown delivery outcome.
- Future work: crash/restart webhook replay tests; concurrent duplicate messages; failure between consent/location dequeue and case filing; production configuration and dependency audit; real model evaluation with domain experts.

## Change policy

Do not merge until the exact final head passes both CI jobs and the test output is inspected. Do not deploy to farmers. The webhook durability work requires its own reviewed migration and fault-injection tests rather than a superficial retry toggle. Existing web cases without tokens need a separate, verified recovery process.
