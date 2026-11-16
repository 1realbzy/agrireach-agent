# Provisional officer queue priority triage

This branch adds deterministic, read-only triage labels to officer case views.
It is an experimental routing aid, not an agricultural diagnosis, incident
severity certification, service-level promise, or permission to release advice.

The policy `triage-demo-v1` assigns four levels from the original question text
and existing intake flags: critical for explicit reports of certain immediate
chemical safety concerns; high for certain restricted chemical treatment
questions and reports of possible spread; medium for other intake flags; routine
otherwise. Results include human-readable reasons and a policy version.

The API presents the result under `case.triage`, sorts the officer queue by the
derived rank, and shows the reason in the officer UI. No migration is needed:
the assessment is recomputed from existing stored case inputs. The source case
and existing priority fields are not modified. Existing audit records preserve
the case input, but **triage decisions themselves are not persisted**. A durable
decision ledger and policy version history remain required before operational use.

The current mandatory officer approval and safety gate are completely unchanged.
The triage response explicitly reports `autonomous_release_permitted: false`.

Before a real institutional pilot, a qualified agricultural team must validate
the taxonomy, missed critical cases, false alerts, local language inputs, response
deadlines, source quality, and supervisor override procedures. The keyword rules
are intentionally narrow and may miss paraphrased reports or regional languages.
