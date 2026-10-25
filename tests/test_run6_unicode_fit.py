"""Run 6 bug 1 (docs/live-eval-2026-10-25-run6-approval.md): the B1 recorded draft with "in Kɔforidua" added to the
scouting sentence. One "ɔ" makes the whole text UCS-2 (268-character limit), and dropping advice from the end lost
storage, then rotation, then the scouting sentence: the proposal was caveat + safety line, no advice. Each candidate is
measured with the real encoding, and dropping the Unicode sentence is tried first when that lets the text use the
GSM-7 limit."""
from pathlib import Path

from agrireach import farmer_reply as fr, knowledge
from agrireach.channels import sms

IDS = ["APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
       "APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p22-sacks"]
PS = [knowledge.reference(i) for i in IDS]
Q = "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?"
B1 = (Path(__file__).parent / "fixtures" / "run6_b1_draft.txt").read_text()
PROBE = B1.replace("stunted growth [APNI", "stunted growth in Kɔforidua [APNI")
CAVEAT = fr.zone_caveat("Adaklu")
SCOUT = ("You should scout the maize field at least once a week, looking for unusual patterns such as insect damage, "
         "larvae, or stunted growth in Kɔforidua.")
ROTATE = ("You should consider rotating maize with non-host plants like groundnut, deep ploughing, and proper weeding to "
          "reduce future infestations.")
STORE = ("For storage, well-dried and shelled maize should be treated with recommended storage chemicals and stored in "
         "jute sacks lined with polythene bags.")


def test_run6_unicode_probe_keeps_rotation_and_storage_as_gsm7():
    assert PROBE != B1
    fd = fr.propose(PROBE, Q, zone_caveat=CAVEAT, passages=PS)  # offline: the rule path
    assert fd.mode == "rule"
    m = sms.measure(fd.text)
    assert m.encoding == "GSM-7" and not sms.length_prompt(fd.text), (m, fd.text)
    assert ROTATE in fd.text and STORE in fd.text, fd.text
    assert fd.text.index(ROTATE) < fd.text.index(STORE)
    assert "Kɔforidua" not in fd.text
    note = [p for p in fd.problems if "dropped to fit the length limit" in p]
    assert len(note) == 1 and f"'{SCOUT}'" in note[0], fd.problems
    assert fd.audit["dropped"] == [SCOUT]


def test_an_early_short_unicode_sentence_is_dropped_when_that_keeps_more_advice():
    a = "Weed the field in Kɔforidua now."
    b = "Check the maize field at least once a week for insect damage on leaves, cobs or stems, larvae or eggs. " * 2
    c = "Rotate maize with non-host plants such as groundnut to help reduce Fall Army worm infestations next season. " * 2
    b, c = b.strip(), c.strip()
    out, notes = fr.ensure_safety_line(f"{a} {b} {c}", [], fit=True)
    assert out == f"{b} {c}", out  # 268 UCS-2 would keep only a + b; GSM-7 keeps b + c
    assert sms.measure(out).encoding == "GSM-7"
    assert [n for n in notes if "dropped to fit" in n] == [f"1 advice sentence(s) dropped to fit the length limit; "
                                                          f"check the reply still makes sense: '{a}'"], notes


def test_unicode_kept_when_it_costs_nothing():
    a = "Weed the field in Kɔforidua now."
    b = "Check the maize field at least once a week."
    out, _ = fr.ensure_safety_line(f"{a} {b}", [], fit=True)
    assert out == f"{a} {b}"
