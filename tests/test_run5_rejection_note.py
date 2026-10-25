"""Run 5 item 6: a model SMS rejected for SMS length was reported with the approval prompt's own words ("Shorten it
... before approving (it is N now). Nothing is cut automatically."), which reads as if the officer had to shorten the
proposed text, and "Nothing is cut" next to a rule text that did drop sentences. The rejection note says what happened."""
import json

from agrireach import farmer_reply as fr, judge, llm
from agrireach.channels import sms
from tests.test_sms_safety_guarantee import DRAFT_B1, F1_PS, Q, SMS_B1

CAVEAT = fr.zone_caveat("Adaklu")


def accept(user):
    n = len([l for l in user.splitlines() if ". SENTENCE: " in l])
    return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(n)]})


def test_b1_model_sms_rejection_note_does_not_use_the_approval_prompt_words(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (SMS_B1, "llm:fake"))
    monkeypatch.setattr(judge, "_call", accept)
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    [note] = [p for p in fd.problems if p.startswith("model rewrite rejected")]
    assert "too long for SMS" in note and "the limit is 4" in note, note
    assert "Nothing is cut automatically" not in note and "before approving" not in note and "Shorten it" not in note
    assert "a model SMS is never shortened" in note and note.endswith("rule-based version shown"), note
    assert all("Nothing is cut automatically" not in r for r in fd.audit["model_rejected"]), fd.audit
    # the approval prompt itself is unchanged
    assert sms.length_prompt("a" * 613).endswith("before approving (it is 613 now). Nothing is cut automatically.")
