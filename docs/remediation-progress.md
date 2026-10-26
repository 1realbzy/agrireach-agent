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
