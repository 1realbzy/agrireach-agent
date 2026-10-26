# Developer remediation report, 26 October 2026

Independent QA verdict against reviewed commit fc00ae0 remains FAIL until the
Grok Bot team issues its next verdict. This report records developer verification.

## Baseline and checkpoints

Reviewed GitHub baseline: fc00ae00b35270382827a60ecd629e401ba82188.
Starting local HEAD: be2f7527212c758da986b1028b774f8ee69f8b0d.
The trees were identical and the starting working tree was clean. Existing local
checkpoint history was preserved; no rebase was performed.

| Local commit | Responsibility |
| :--- | :--- |
| 6535597 | C1 material instruction hold, product regressions, reproduction record |
| 3746524 | H1 definite preflight failures, authenticated atomic reconciliation |
| c25ae0f | H2 relevance, shared referrals, language, S2, stable acknowledgements, CLI and voice tests |
| 6b14a4b | Recovery UI, additional concurrency/ambiguity tests, CI, migration fixture and documentation |

Verified implementation commit: 6b14a4b946d61e0ac2bf0c6a161c6103b6f778fc.
This report and final progress evidence are committed separately afterward; the
owner handoff records the final local HEAD including that evidence commit.
No corrections have been pushed. Main remains at 94bff88. Remote safety branch
remains at the reviewed fc00ae0 commit.

## Finding to correction mapping

| Finding | Correction and evidence |
| :--- | :--- |
| C1 | Reproduced all five named-product deterministic escapes before gate edits. Unsupported material instruction grammar now holds independently of chemical sources or capitalisation. Tests include unfamiliar names, contextual pronouns and application formulations; a judge spy proves no model can clear the hold. API, DB, release and delivery checks prevent publication. |
| H1 | Unconfigured channels, invalid SMS recipient and length refusals are definitely_failed. Timeouts and malformed/incomplete responses remain unknown. Rejection preserves unresolved job disposition. Authenticated API/UI reconciliation requires verified provider evidence, serializes concurrent actions and never sends. |
| H2 | Only registered classified incidental topics can be excluded from S1. Immutable question plus reply determine relevance; unknown/changed sources and ambiguous topics retain S1. Every applicable requirement remains checked. S2/S3 inspect all sentences. Findings quote the exact safeguard. |
| M1 | Registered complete Talk/Ask extension referrals and explicit inability to recommend pesticide wording share one template policy. Added wording is accepted only as complete sentences. |
| M2 | Complete supported source sentences and registered templates do not require a judge. Arbitrary paraphrases still require assessment. Judge failure remains unavailable, never supported. |
| M3, M9 | Reply content is assessed independently of proposal language. Unicode punctuation, temperature symbols and a place name alone no longer trigger a hold. Twi word markers and unsupported scripts retain review. This remains a bounded heuristic, not full language identification. |
| M4 | Known unsafe patterns block; other unsupported material instructions hold. Both prevent approval and acknowledgement. Source fingerprints deliberately require registration review after edits; no automatic acceptance of changed corpus content was added. |
| M5, M6 | Architecture/workflow body now describes current approval/delivery semantics. Existing rollback restrictions are retained and clarified: stop all writers/senders, preserve newer evidence, verify a separate restored copy and prefer forward repair. Never run vulnerable old code against the active upgraded DB. |
| M7 | Length, source support, figures and unavailable-judge returns now use named intermediate findings and readable multiline returns. |
| M8 | Added deterministic consultation bypass patterns and protective skip-negation regressions. |
| Voice tests | Repaired officer token/revision arguments. Model independent voice approval always runs. Real Whisper/Piper tests assess advisory intelligibility rather than brand-name phonetic spelling. |
| CLI exit | Blocked operations return 1; module propagates it through SystemExit. Existing unsafe CLI regression now asserts the exit code. |
| Ack prose | Challenge binding uses stable warning rule/sentence/evidence identity, not model explanation prose. Changing text, case, credential, warning identity or revision still invalidates it. |
| HTTP 409/428 | 409 is intentional for the approved application workflow conflict. 428 concerns HTTP conditional requests. Critical holds remain 422, assessment unavailability 503. Rationale documented. |
| Legacy data/backups | legacy_unvalidated publications remain visible as historical evidence but cannot be newly sent. Backups are logical SQLite snapshots after legacy bootstrap, not promised original-file byte copies. No destructive downgrade added. |

## Verification

All commands use an isolated Python 3.12.14 environment, temporary SQLite files
and simulator recipients. No advisory model credentials were configured.

* C1 checkpoint: 106 tests passed before S1 relevance changes.
* H1 targeted group: 65 passed.
* Expanded safety/transaction/QA group: 150 passed.
* SMS and QA group after incomplete-response correction: 53 passed.
* Real speech plus QA/approval group: 39 passed, including repaired voice approval.
* CLI exit regression: 1 passed.
* Full final frozen suite: 777 passed, zero failed, zero skipped in 135.38 seconds,
  with both speech model caches configured. All six real speech tests ran.
* Legacy migration script: upgrade/backfill, exact original case/log row preservation,
  backup permissions, integrity, foreign keys and readonly ledger verification passed.
* Python compilation, workflow YAML structure and git diff whitespace checks passed.

The first full run found one regression (761 passed, 1 failed, 1 skipped): a source
conflict hold also blocked explicit deferral to the officer. The code was corrected;
the existing test and fixture expectations were preserved.

An isolated read-only checkout of reviewed fc00ae0 subsequently confirmed end to
end mancozeb and Lambda Super approval and simulator delivery with a favourable
stub judge. Gramoxone with the scouting-only source was held by lexical source
support; the independent report's live Gramoxone result is not claimed as our live
reproduction. The temporary checkout and outbox were removed after testing.

All six original API unsafe regressions still block. Direct DB approval requires
explicit text/revision; unsafe CLI returns nonzero; release requires assessed
approval; delivery requires a unique claim. Existing acknowledgement replay,
concurrent approval/dispatch and migration rollback/preservation regressions pass.
New reconciliation concurrency has exactly one winner and one audit event.

## Historical replay

New output: safety-remediation-replay.json. Original historical replay JSON, raw
evaluation records, knowledge corpus and frozen labels were not rewritten.

| Historical label | Pass | Block | Hold |
| :--- | ---: | ---: | ---: |
| Normal candidates | 17 | 0 | 5 |
| Deliberately unsafe | 0 | 15 | 0 |

Three unresolved-source records and two missing-evidence records remain excluded.
These normal labels are compatibility evidence, not agronomic ground truth.
The constructed frozen set retains 40 legitimate passes and 40 unsafe hard blocks;
its small quotation-heavy sample does not establish universal detection accuracy.

## CI and limitations

.github/workflows/regression.yml triggers on PRs to main and pushes to main/work/**.
Deterministic job runs pytest, safety replay (fails on an unsafe pass), and upgrade
verification of a temporary representative legacy SQL fixture. Separate speech
job installs existing optional requirements, caches pinned public Whisper/Piper
revisions, and runs real speech plus QA regressions. Permissions are contents:read;
no secrets are passed, no paid models or real farmer transports are configured.
Local command equivalents passed; GitHub execution is pending authorised push.

No live advisory-model regression could run without endpoint/key configuration.
Browser interaction with the officer UI has not been visually verified. Provider
tests use mocked HTTP; reconciliation trusts an officer's verified external record,
not a machine-verified proof. Unknown sends never automatically retry. No guarantee
of exactly once external delivery, complete product recognition, multilingual
semantic safety, source accuracy, field readiness or challenge compliance is made.
Unfamiliar nonchemical material instructions may be held conservatively. These
changes require independent Grok Bot review before acceptance.
