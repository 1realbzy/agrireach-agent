# Officer re-grade pack

For extension officers to grade AgriReach's answers to the 14 field-evidence questions (`evals/field_evidence.json`).

| File | What it is |
|---|---|
| `officer-regrade.pdf` | Printable sheet, 8 A4 pages: intro, each question with AgriReach's answer and a grading box, summary table. |
| `officer-regrade.md` | Same content as text, for officers who reply by email or chat. |
| `officer-regrade.html` | Source of the PDF. |
| `answers-2026-10-25.jsonl` | The raw run the sheet is built from. |

The answers come from one real run on 25 Oct 2026, 17:34:58 to 17:36:11 UTC. It used code version ae254ce (branch `feat/rainfall-signal`) and the drafting model `mistralai/mistral-small-3.2-24b-instruct`; the judge was off. Nothing was edited by hand. To rebuild the sheet:

    python scripts/officer_regrade.py run > docs/officer-regrade/answers-<date>.jsonl
    python scripts/officer_regrade.py render docs/officer-regrade/answers-<date>.jsonl
    google-chrome --headless --no-pdf-header-footer --print-to-pdf=docs/officer-regrade/officer-regrade.pdf docs/officer-regrade/officer-regrade.html

Questions not answered by the model:
- F12 (Twi) and F13 (Dagbani or Wali) were not run. They need a question written by a native speaker, and the sheet asks the officer to write one.
- F14 is built by code from an approved guide passage; no model is involved.

What this run shows, before any officer has graded it (my reading, not a grade):
- **F4:** both model drafts failed the figure check, so the officer sees the verbatim-passage fallback and the "sources differ" note. The earlier run Z1 (f1fc280) passed this question, so the model drafts vary from run to run.
- **F7:** the officer draft and the SMS both say to dispose of the mouldy maize. No cited passage says that.
- **F9:** the officer draft is "I do not know.", but the model's SMS rewrite tells the farmer to contact their extension officer. That sentence has no source. It passed the figure check because it contains no figures.
- **F8, F10, F11:** the model's SMS rewrites were rejected, and the rule-based "I do not know." is shown instead. For F11 the rejected rewrite contained spray doses (250g, 10L) that are not in any source. The check caught them.
- **F1:** the model's SMS rewrite was 620 characters, over the 600 limit. The rule-based SMS shown instead drops the closing sentence about asking the extension agent which pesticide to use.
- **Rainfall:** none of the 14 questions names a district and asks about planting, so no rainfall record appears in this pack.
