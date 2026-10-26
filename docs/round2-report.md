# Round 2 developer remediation

Independent acceptance remains with Grok Bot. No corrections published.

## Recovery and root causes

Recovered work/safety-hardening at 079bd36fb3cba09d5ee78a6666b974476708c5d0,
with no staged changes. Preserved the UI rewrite, WhatsApp validation, vocabulary
updates and three untracked UI/test helpers. The failed patch had not applied.
See round2-progress.md for original investigation and checkpoint results.

The four remaining failures were API approval, competing approvals, officer draft
independence and zone caveat retention. They shared lexical uncertainty over
ordinary words (checked, answer, zone) and Kumasi. Reviewed general vocabulary
now permits model source assessment for those words. Source/template acceptance,
mandatory holds and fixture labels are unchanged. Four retests passed in 4.93s.

Original blockers came from verb enumeration and incomplete consultation phrases.
Both reached simulator delivery in the reviewed detached checkout. The boundary
now evaluates unresolved entities/materials in all unsupported sentences, including
fragments and passive instructions. Novel terms/doses/material context cause a
mandatory hold before the judge. Known ordinary agricultural vocabulary only
permits source assessment. Consultation devaluation is independently enforced.
This is conservative lexical uncertainty handling, not semantic safety proof.

## UI and browser

Signed out screens make no authenticated request. Empty/whitespace tokens cannot
create a Bearer header. Public feedback maps workflow outcomes without exception
or model diagnostic JSON. Confirmation is marked required and disables approval;
notes accompany decisions; retry assessment resubmits the same current candidate.
Reconciliation is visible in history for unknown jobs irrespective of case status.
Voice-note listening and exact voice-script review remain available.

Chromium 134 localhost acceptance verified signed out rendering, disabled
unconfirmed approval, unsafe product hold, request-info note persistence,
assessment-unavailable recovery button and source-supported release. Screenshots
are in round2-browser/. Servers and browser share a network namespace; no public
tunnel or authentication exception was used. The script always stops its servers.
Browser acknowledgement and reconciliation interactions remain unverified;
their application/API and concurrency paths retain automated coverage.

## Verification and limitations

193 initial safety tests passed before interruption; ten independent nonchemical
controls passed classification without claiming agricultural validation.
The resumed security/UI/concurrency group passed 71 tests. Strict historical replay:
17 normal pass, 5 hold, all 15 unsafe blocked. Three unresolved-source and two
missing-evidence cases remain unassessed. Strict replay compares record identities
and exclusion reasons against the retained evidence inventory, rejects new missing
records/exclusions and enforces at least 17 normal passes. It does not claim complete
historical coverage. Frozen fixture labels and original evaluation data preserved.

Legacy SQL fixture now includes released and pending cases plus historical log
rows. Migration/backfill/backup/integrity/readonly verification passed. No migration
schema changed; existing rollback fault injection and concurrency tests retained.

Speech restoration: the recovered Piper file was only 23,248,896 bytes and failed
ONNX protobuf parsing. Downloaded the pinned public model into a separate cache
(63,201,294 bytes). No test was skipped to hide corruption. Optional ONNX telemetry
was disabled through test-only startup after automatic approval review blocked
an unapproved Microsoft telemetry destination. tests:src startup propagates to
speech subprocesses. No live advisory model configuration or farmer recipients.

CI actions pinned to verified repository commit SHAs. Speech job fails on any skip;
strict replay tracks evidence inventory and minimum normal compatibility. Workflow
YAML/pins/skip setting verified locally. No GitHub execution for unpublished work.
Making jobs required branch checks remains an external repository configuration
step; main/settings have not been changed.

Remaining risks: unknown common-word product names, source accuracy, misleading
combinations, unfamiliar ordinary terms causing holds and bounded language checks.
Duplicate logical migration backups under simultaneous startup remain a low
priority operational limitation. Provider reconciliation still relies on the
officer verifying external evidence. No field-readiness claim is made.

Final full suite: 825 passed, zero failed/skipped in 214.28 seconds, including six
real speech tests. Targeted safety/UI/transaction group: 167 passed. Checkpoints:
079bd36, 92ce86d and 98c23f7. Final documentation commit is identified in the owner
handoff. Working tree verified clean after committing final evidence.
