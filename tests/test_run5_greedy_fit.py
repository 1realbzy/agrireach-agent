"""Run 5 (Ghana Real Economy Research): fitting the rule-path farmer text skipped the whole tail once one long
sentence didn't fit. On Techiman the long scouting sentence pushed out "Rotate maize with non-host plants...", which
fits on its own. Now only the sentences that don't fit are skipped, later ones that fit are kept, the order is the
draft's, and every skipped sentence is named in the officer note."""
from agrireach import farmer_reply as fr, knowledge, llm

IDS = ["APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p18-scouting",
       "APNI-SARI-2023-MAIZE:p20-faw-prevention"]
PS = [knowledge.reference(i) for i in IDS]
Q = "Fall armyworm is eating my maize in Techiman. What should I do?"
SCOUT = ("When scouting, walk through the field and look out for unusual patterns such as insect damage on leaves, cobs "
         "or stems, presence of insect larvae or eggs on maize leaves, abnormal leaf colour, and stunted slow growing "
         "plants.")
ROTATE = "Rotate maize with non-host plants such as groundnut to help reduce Fall Army worm infestations."
PLOUGH = ("Deep ploughing and burial, or burning of infested maize residues helps to reduce populations in the following "
          "season.")
WEED = "Proper weeding of maize fields also helps to reduce infestations."
WALK = "It is recommended to have a walk through the maize field at least once a week."


def draft():  # the offline draft without its stub label, so the rule path builds the farmer text
    return "\n".join(l for l in llm.stub_draft(Q, PS, []).splitlines() if not l.startswith(llm.STUB_LABEL))


def test_techiman_keeps_later_sentences_that_fit_and_names_each_skipped_one():
    caveat = fr.zone_caveat("Techiman")
    fd = fr.propose(draft(), Q, zone_caveat=caveat, passages=PS)
    assert fd.mode == "rule" and fd.text.startswith(caveat["sentence"]), fd.text
    assert len(fd.text) <= fr.MAX_CHARS and not fr.sms_length_problem(fd.text)
    for s in (WALK, ROTATE, WEED):
        assert s in fd.text, (s, fd.text)
    assert fd.text.index(WALK) < fd.text.index(ROTATE) < fd.text.index(WEED)  # the draft's order
    assert SCOUT not in fd.text and PLOUGH not in fd.text
    note = [p for p in fd.problems if "dropped to fit the length limit" in p]
    assert len(note) == 1 and note[0].startswith("2 advice sentence(s)"), fd.problems
    assert f"'{SCOUT}'" in note[0] and f"'{PLOUGH}'" in note[0]
    assert fd.audit["dropped"] == [SCOUT, PLOUGH]


def test_greedy_fit_keeps_order_and_skips_only_what_does_not_fit():
    long_ = "Long " + "very " * 120 + "sentence."
    text = "First sentence here. " + long_ + " Short one after. Another short one."
    out, notes = fr.ensure_safety_line(text, [], fit=True)
    assert out == "First sentence here. Short one after. Another short one.", out
    assert any(f"'{long_}'" in n and n.startswith("1 advice sentence(s)") for n in notes), notes
