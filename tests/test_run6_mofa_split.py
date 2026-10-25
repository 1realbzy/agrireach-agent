"""Run 6 bug 5 (docs/live-eval-2026-10-25-run6-approval.md, EJ): the approval-time source check warned "'(MoFA) .' is
not supported by its citation". The rule SMS keeps the verbatim MoFA row "... to early Sept. (MoFA).". sms_claims
re-cited each sentence for the claim check as "... early Sept. (MoFA) [ids].", and the claim check's splitter ended the
sentence at "Sept.", leaving "(MoFA) [ids]." as a sentence of its own ("(MoFA) ." once the citation is stripped)."""
import json
from pathlib import Path

from agrireach import farmer_reply as fr, knowledge

FX = Path(__file__).parent / "fixtures"
IDS = ["IITA-MAIZE-2025:p15-three-good-rains", "MOFA-MAIZE:p11-transition-major", "IITA-MAIZE-2025:p16-transition-major",
       "MOFA-MAIZE:p12-transition-minor", "MOFA-MAIZE:p10-when-to-plant", "IITA-MAIZE-2025:p16-transition-minor"]
PS = [knowledge.reference(i) for i in IDS]
SEPT = "In the transition zone, plant minor-season maize from mid July through August to early Sept"


def judge():
    seen = []

    def call(user):
        items = [l for l in user.splitlines() if ". SENTENCE: " in l]
        seen.extend(items)
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(len(items))]})
    return seen, call


def test_recorded_ejura_sms_has_no_spurious_source_name_sentence():
    text = (FX / "run6_ej_proposal.txt").read_text()
    assert "early Sept. (MoFA)." in text
    seen, call = judge()
    problems = fr.sms_claims(text, PS, judge_call=call)
    assert not any("(MoFA)" in p or "(IITA)" in p for p in problems), problems
    assert problems == [], problems
    sept = [s for s in seen if SEPT in s]
    assert len(sept) == 1 and "(MoFA)" in sept[0], seen  # the row is checked whole, with its source name
    assert not any(s.split("SENTENCE: ", 1)[1].startswith("(") for s in seen), seen


def test_ejura_rule_text_from_the_recorded_draft_passes_the_approval_check():
    fd = fr.propose((FX / "run6_ej_draft.txt").read_text(), "When should I plant maize in Ejura?", conflicts=True,
                    passages=PS)
    assert "Sept. (MoFA)." in fd.text, fd.text
    assert fr.sms_claims(fd.text, PS, judge_call=judge()[1]) == []
