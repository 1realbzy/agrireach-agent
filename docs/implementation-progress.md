# Safety hardening progress

Date: 26 October 2026.
Branch: work/safety-hardening.
Baseline and unchanged main: 94bff8880f744e50d6df4d515bdc8c6b7a110198.
No push, merge, deployment, purchased service or real farmer message is authorised or performed.

## Local checkpoints

| Checkpoint | Commit | Evidence |
| :--- | :--- | :--- |
| Fixture freeze | 7ce1717 | 40 legitimate, 40 unsafe and 3 uncertainty examples committed before the gate |
| 1: deterministic gate and approval integrity | 6e17ce6 | 107 targeted tests passed before checkpoint 2 |
| 2: transactional approval and delivery | 3a45aab | 119 targeted tests passed before integration; subsequent integration fixes are in checkpoint 3 |
| 3: integration and verification | See final checkpoint commit in git log | Implemented under the strict approved policy; acceptance remains pending historical compatibility and independent review |

Code remains on this branch. Historical raw evaluation files, the agricultural corpus and the frozen fixture labels are unchanged. Existing tests that intentionally released unsafe text now assert blocks; other contract updates require explicit farmer text/revisions, registered simulator credentials, preapproval SMS length enforcement, held unsupported languages, idempotent release and distinct definite versus unknown delivery failures. These are documented behaviour changes, not fixture relabelling or skipped tests.

## Implemented

The shared S1–S3 gate is enforced at database approval. API, simulator, release and direct advisory dispatch use the same workflow. Submitted text remains exact. Versioned SQLite migrations preserve legacy records and create immutable approval/submission/assessment evidence, acknowledgement challenges, atomic audit events and delivery jobs/attempts. Unsupported future schemas are rejected before bootstrap writes.

Acknowledgements expire after 10 minutes, bind exact candidate/context/officer credential/warnings and are consumed once with approval. Chemical, food safety and source conflict concerns are not routine acknowledgement cases. Required judge failures are 503 assessments, never successful checks.

Release rechecks fingerprints and deterministic rules. A delivery job has one active claim. Unknown outcomes cannot automatically retry. Claims older than 15 minutes become unknown on the next release or claim attempt. Provider IDs are retained when available. Already published historical web text is marked legacy_unvalidated; legacy approvals cannot be newly sent. Exact optional voice scripts require explicit review before synthesis.

## Verification state

Final full suite: 738 passed, 1 skipped in 178.75 seconds. Exact commands, runtime versions and limitations are in safety-verification.md. Developer testing is not independent QA. Grok Bot review has not occurred.

The original six API bypass cases and simulator unsafe approval regression are blocked. Direct database approval no longer substitutes the internal draft for missing farmer text. Tests cover exact payloads, source mutation, stale revisions, concurrent decisions/dispatch/acknowledgement consumption, replay/expiry/credential changes, failed audit rollback, interrupted claims, migration rollback, legacy backup preservation and unsupported future schema refusal.

## Acceptance issue requiring policy resolution

The specification puts every cited chemical passage in scope. Historical retrieval sometimes attaches a storage chemical passage to an armyworm case. The strict gate then requires that storage passage's preuse safeguard; keeping the armyworm source referral alone is insufficient.

Deterministic replay of runs 5–9 assesses 37 of 42 records. All 15 deliberate unsafe examples are blocked. Of 22 historically normal candidates, 9 pass, 9 are deterministically blocked and 4 require review. Two review holds are the intentional unsupported language restriction. Thus 11 of 20 English historical candidates are also held. Three records have unresolved source identifiers; two run 9 records lack submitted source evidence. Exact cases are in safety-historical-replay.json.

Historical author grades are not agronomic truth. These counts are compatibility holds, not independently verified agronomic false positives. Nevertheless the zero historical false block target is not established, and this is a substantial usability concern. No automatic relevance filter or looser template acceptance has been introduced to hide it. An owner decision is needed before changing the explicit all cited scope or accepting this compatibility cost.

## Remaining limits

Unknown products, indirect harmful phrasing, sentence combinations, source errors, broad language heuristics and model error remain. The uncertainty fixture set is inadequate for calibration because its three examples also violate S1. The deterministic legitimate set is dominated by source quotations. Fresh live model and real speech verification are unavailable in this environment. UI rendering has not received a browser driven visual acceptance test. External provider semantics and agricultural applicability need independent review. No field readiness, universal safety or exactly once external delivery is claimed.
