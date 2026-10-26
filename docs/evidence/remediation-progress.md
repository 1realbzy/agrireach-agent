# QA remediation, 26 October 2026

Reviewed remote commit fc00ae00b35270382827a60ecd629e401ba82188 and local
be2f7527212c758da986b1028b774f8ee69f8b0d have identical trees. Starting tree clean.
Local checkpoint history retained. No push authorised until owner reviews results.

## C1

Before changes all five reported product instructions passed the deterministic
gate with judge_status=required. Reproduced Gramoxone, mancozeb, Lambda Super,
Karate 5EC and Actellic. Unsupported material instruction grammar now requires
review even with no chemical source and regardless of product capitalization.
Exact source sentences and protective templates retain their provenance checks.
Policy version changed so old approvals require fresh review.

Targeted command: pytest tests/test_qa_remediation.py tests/test_safety_checkpoint1.py
Result: 106 passed. Ten product variants tested with and without chemical sources;
a judge spy proves deterministic holds never reach model assessment. Original six
API regressions and frozen labels pass. C1 verified before relevance changes.

Known bound: unfamiliar agricultural material instructions may be held conservatively;
grammar is not universal product recognition or semantic safety proof.

## H1

Local channel configuration/recipient/length refusals are definitely_failed;
ambiguous provider responses remain unknown. Authenticated POST
/officer/delivery-jobs/{job_id}/reconcile records verified provider evidence and
disposition atomically without sending. BEGIN IMMEDIATE serializes reconciliation.
Reject/request_info can preserve an unresolved delivery record without reapproving.
Reopening remains unavailable until an unknown send is reconciled.
Targeted delivery, SMS, transaction and QA regressions: 65 passed.

## H2 and functional corrections

S1 now classifies registered source topics using immutable question plus reply.
Unknown/changed topics remain in scope; field scouting of cobs is not storage.
S2/S3 still inspect every sentence independently. All frozen fixtures unchanged.
Complete registered templates/source sentences bypass probabilistic assessment;
critical uncertain instructions cannot. Harmful consultation bypass rewordings
block while protective negations remain valid. English replies to Twi proposals
are assessed from the reply; temperature symbols and place names alone do not
trigger a language hold. Language classification remains a bounded heuristic.
CLI returns nonzero on blocked operations. Acknowledgement binding uses stable
warning identity instead of stochastic explanation prose.

Historical replay: 17 normal passes, 5 normal holds, 0 normal blocks; 15/15 unsafe
blocks; 3 unresolved sources and 2 missing-evidence exclusions unchanged. These
labels do not establish agronomic correctness. Updated QA/approval tests: 38 passed.
Repaired real Whisper/Piper and QA/approval group: 39 passed (before five added
product/API/ack regressions). No live advisory-model configuration exists.

First full regression: 761 passed, 1 failed, 1 skipped. Failure identified an
overbroad SOURCE_CONFLICT hold for explicit deferral to the officer; corrected
without changing the existing test. Fresh complete run with speech assets pending.

## Final evidence

Final frozen code suite: 777 passed, zero failed, zero skipped in 135.38 seconds.
Command: PYTHONPATH=src python -m pytest -q -rs, with AGRIREACH_STT_DIR and
AGRIREACH_TTS_DIR pointing to pinned public model caches. All six real speech tests
ran. The CLI exit assertion also passed separately. Migration fixture verification,
Python compilation, workflow YAML structure and git diff checks passed.
Frozen set: 40 legitimate pass, 40 unsafe blocked, 3 uncertain blocked by missing
safeguards. Historical replay: 17 normal pass, 5 hold, 15 unsafe block.

Additional isolated fc00ae0 reproduction confirmed mancozeb and Lambda Super were
approved and delivered to a temporary simulator outbox with a favourable stub
judge. Gramoxone on a scouting-only source was held by lexical support in that
probe; the independent team's live Gramoxone finding is not our live test result.

Four remediation implementation commits: 6535597, 3746524, c25ae0f, 6b14a4b.
Report: qa-remediation-report.md. No production credentials, real recipients or
paid model calls used. No live advisory endpoint/key available. GitHub Actions
execution and independent acceptance await owner review and authorised push.
