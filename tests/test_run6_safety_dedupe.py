"""Run 6 (docs/live-eval-2026-10-25-run6-approval.md, note 9): 3 of 5 pesticide proposals carried the guaranteed (APNI)
line and then the model's or rule text's own copy of it in other words (about 100 characters each); in F1-a the copy
drew a judge "too general" approval warning. A sentence that is only the same AEA-on-pesticides referral (another
citation, case, punctuation, "Agricultural Extension Agent" for "AEA", a leading "If ..." clause) is removed as a
repeat and named for the officer. A pesticide sentence that says anything more is kept."""
import json
from pathlib import Path

import pytest

from agrireach import farmer_reply as fr, judge, knowledge, llm

REC = json.loads((Path(__file__).parent / "fixtures" / "run6_pesticide_proposals.json").read_text())
LINE = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)."
COPIES = {
    "F1-a": "You should consult the local Agricultural Extension Agent (AEA) for advice on recommended pesticides.",
    "F1-b": "If the worms are still a problem, talk to your local Agricultural Extension Agent about the right pesticide "
            "to use.",
    "S-Kintampo": "If you find infestations, consult your local Agricultural Extension Agent for advice on recommended "
                  "pesticides.",
}


def passages(case):
    return [knowledge.reference(i) for i in REC[case]["sources"]]


def accept(user):
    n = len([l for l in user.splitlines() if ". SENTENCE: " in l])
    return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(n)]})


@pytest.mark.parametrize("case", sorted(COPIES))
def test_recorded_proposal_loses_its_copy_of_the_safety_line(case):
    rec = REC[case]
    assert COPIES[case] in rec["proposed_sms"] and LINE in rec["proposed_sms"]
    caveat = fr.zone_caveat(rec["q"].split(" in ")[-1].split(".")[0] if case == "S-Kintampo" else "Adaklu")
    out, notes = fr.ensure_safety_line(rec["proposed_sms"], passages(case), caveat)
    assert COPIES[case] not in out and out.count("pesticide") == 1 and LINE in out, out
    assert any(n.startswith("removed as a repeat") and COPIES[case] in n for n in notes), notes


@pytest.mark.parametrize("case", ["F1-b", "S-Kintampo"])
def test_model_path_proposal_has_one_safety_sentence(monkeypatch, case):
    rec = REC[case]
    caveat = fr.zone_caveat("Kintampo" if case == "S-Kintampo" else "Adaklu")
    model_sms = rec["proposed_sms"].replace(caveat["sentence"] + " ", "").replace(LINE + " ", "")
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (model_sms, "llm:fake"))
    monkeypatch.setattr(judge, "_call", accept)
    fd = fr.propose(rec["draft"], rec["q"], zone_caveat=caveat, passages=passages(case))
    assert fd.mode == "llm:fake", fd.problems
    assert LINE in fd.text and COPIES[case] not in fd.text and fd.text.count("pesticide") == 1, fd.text
    assert fd.audit["repeats"] == [COPIES[case]]


def test_rule_path_f1a_has_one_safety_sentence():
    rec = REC["F1-a"]
    fd = fr.propose(rec["draft"], rec["q"], zone_caveat=fr.zone_caveat("Adaklu"), passages=passages("F1-a"))
    assert fd.mode == "rule" and LINE in fd.text and fd.text.count("pesticide") == 1, fd.text
    assert any(p.startswith("removed as a repeat") and COPIES["F1-a"] in p for p in fd.problems), fd.problems


@pytest.mark.parametrize("s", [
    "consult your local aea for advice on the recommended fall army worm control pesticide in your area [APNI-SARI-2023-MAIZE:p20-faw-control]",
    "Consult your local Agricultural Extension Agent for advice on the recommended fall armyworm control pesticide in your area!",
    "CONSULT YOUR LOCAL AEA FOR ADVICE ON THE RECOMMENDED FALL ARMY WORM CONTROL PESTICIDES IN YOUR AREA (MoFA).",
])
def test_same_sentence_other_citation_case_punctuation_or_aea_wording(s):
    assert fr._repeats(s, LINE)


@pytest.mark.parametrize("s", [
    "Consult your local AEA before spraying, and wear gloves and a mask when you spray.",
    "Do not spray pesticide near streams or wells.",
    "Spray the recommended pesticide in the evening, into the funnel of the plant.",
    "If you find infestations, consult your local AEA and keep children away from sprayed fields.",
])
def test_pesticide_sentences_that_say_more_are_kept(s):
    assert not fr._repeats(s, LINE)
