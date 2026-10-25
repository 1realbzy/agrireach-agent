"""The pesticide safety line is a guarantee, not a wording fix (farmer_reply.ensure_safety_line).

F1 lost the safety line from the farmer SMS three different ways in the live runs:
- a5e9192 run 2: the late-timing check flagged "worms are still a problem" and the model SMS was rejected;
- a5e9192 run 2: the rule fallback dropped "Agriculture Extension Agent (AEA)" as an officer instruction;
- cc7cf4c B1 (docs/live-eval-2026-10-25-run4.md): the model SMS kept the line but was 723 characters, so it was
  rejected for length, and the rule fallback dropped "the officer should consult the local AEA ... pesticide".
So whenever a case passage carries a pesticide safety sentence, the final SMS carries that sentence word for word,
with its source name, right after the zone caveat, on every path. It is never shortened: if it can't fit, no SMS is
proposed and the officer writes it. The texts below are recorded live (cc7cf4c, B1 F1). Offline: the model rewrite
is replaced and the judge is the conftest one that supports every sentence."""
import pytest

from agrireach import farmer_reply as fr, knowledge, llm

F1_IDS = ["APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
          "APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p22-sacks"]
F1_PS = [knowledge.reference(i) for i in F1_IDS]
Q = ("Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. "
     "What next?")
CAVEAT = fr.zone_caveat("Adaklu")
# B1 F1 officer draft (passed the draft check) and its model SMS (723 characters with the caveat; rejected for length).
DRAFT_B1 = (
    "Caution: the curated sources cover Northern Ghana only. The guidance below comes from them and may not apply in "
    "Adaklu; the officer should confirm local timing.\n\n"
    "The farmer should scout the maize field at least once a week, looking for unusual patterns such as insect damage, "
    "larvae, or stunted growth [APNI-SARI-2023-MAIZE:p18-scouting]. If the infestation is severe and the recommended "
    "chemicals have not worked, the officer should consult the local Agricultural Extension Agent (AEA) for advice on "
    "the recommended fall army worm control pesticide in the area [APNI-SARI-2023-MAIZE:p20-faw-control]. "
    "Additionally, the farmer should consider rotating maize with non-host plants like groundnut, deep ploughing, and "
    "proper weeding to reduce future infestations [APNI-SARI-2023-MAIZE:p20-faw-prevention]. For storage, well-dried "
    "and shelled maize should be treated with recommended storage chemicals and stored in jute sacks lined with "
    "polythene bags [APNI-SARI-2023-MAIZE:p22-sacks].")
SMS_B1 = (
    "You should check your maize field at least once a week for unusual patterns like insect damage, larvae, or stunted "
    "growth. If the infestation is severe and the recommended chemicals have not worked, consult your local "
    "Agricultural Extension Agent for advice on the recommended fall armyworm control pesticide in your area. Consider "
    "rotating maize with non-host plants like groundnut, deep ploughing, and proper weeding to reduce future "
    "infestations. For storage, well-dried and shelled maize should be treated with recommended storage chemicals and "
    "stored in jute sacks lined with polythene bags.")
# The p20-faw-control passage's own sentence, word for word, with its source named the way farmer text names
# sources (row_sentence: "(MoFA)").
LINE = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)."


def llm_on(monkeypatch, sms):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    if isinstance(sms, Exception):
        def boom(*a, **k):
            raise sms
        monkeypatch.setattr(fr, "_llm_rewrite", boom)
    else:
        monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (sms, "llm:fake"))


def assert_line_first(text):
    assert text.startswith(f"{CAVEAT['sentence']} {LINE}"), text
    assert text.count(LINE) == 1, text
    assert len(text) <= fr.MAX_CHARS, len(text)


def test_recorded_b1_model_sms_is_723_characters_with_the_caveat():
    # Measured with the caveat as worded in run 4; since fix/run5-findings (item 5c) it ends "check this advice"
    # instead of "check the timing", one character longer.
    run4_caveat = ("This advice comes from guides for Northern Ghana and may not suit Adaklu, so check the timing with "
                   "your local extension agent.")
    assert len(f"{run4_caveat} {SMS_B1}") == 723
    assert len(f"{CAVEAT['sentence']} {SMS_B1}") == 724


def line_for(ps):
    """The sentence ensure_safety_line puts first, or None if it adds nothing."""
    text, _ = fr.ensure_safety_line("Weed well.", ps)
    return None if text == "Weed well." else text.removesuffix(" Weed well.")


def test_the_safety_sentence_is_the_passage_sentence_word_for_word():
    s = line_for(F1_PS)
    assert s == LINE
    assert s.removesuffix(" (APNI).") + "." in knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")["text"]
    assert fr.check(s, DRAFT_B1) == []


def test_herbicide_passage_gives_its_own_sentence():
    p = knowledge.reference("APNI-SARI-2023:weeds-herbicide")
    assert line_for([p]) == (
        "Before applying any herbicide, carefully read and follow instructions provided by the manufacturer or consult "
        "your local AEA (APNI).")


# (a) the over-length faithful model SMS is NOT trimmed (dropping trailing model sentences can leave half a piece of
# advice): model SMS + the source's line is over the limit, so it falls to the rule path, which fits at sentence
# boundaries and lists every dropped sentence for the officer.
STORAGE = ("For storage, well-dried and shelled maize should be treated with recommended storage chemicals and stored "
           "in jute sacks lined with polythene bags.")


def test_a_723_char_model_sms_is_not_trimmed_the_rule_path_carries_the_line(monkeypatch):
    llm_on(monkeypatch, SMS_B1)
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    assert fd.mode == "rule", fd.problems
    assert any(p.startswith("model rewrite rejected") and "over 600" in p for p in fd.problems), fd.problems
    assert_line_first(fd.text)
    assert "You should check your maize field" not in fd.text  # nothing from the rejected model SMS is kept
    assert "You should scout the maize field at least once a week" in fd.text
    assert STORAGE not in fd.text and any(STORAGE in p and "dropped" in p for p in fd.problems), fd.problems


# (b) the model call fails: the rule text carries the line
def test_b_model_call_failure_rule_path_keeps_the_safety_line(monkeypatch):
    llm_on(monkeypatch, RuntimeError("timeout"))
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    assert fd.mode == "rule"
    assert_line_first(fd.text)
    assert not any("safety line" in p for p in fd.problems), fd.problems


# (c) the rule rewrite still drops "the officer should consult..." (it is an officer instruction and is not
# reworded); the guarantee puts the source's own sentence back
def test_c_should_consult_draft_rule_path_keeps_the_safety_line():
    assert not fr.SAFETY_RE.search(fr.rule_rewrite(DRAFT_B1))  # the recorded drop, unchanged
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)  # stub mode: rule path
    assert fd.mode == "rule"
    assert_line_first(fd.text)
    assert not any("safety line" in p for p in fd.problems), fd.problems


def test_c_rule_path_after_a_rejected_model_sms_keeps_the_safety_line(monkeypatch):
    llm_on(monkeypatch, "Spray [X] now.")  # fails check()
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    assert fd.mode == "rule"
    assert_line_first(fd.text)


# (d) a model SMS that drops the line gets the source's sentence (it fits, so the model text is kept whole)
def test_d_model_sms_that_drops_the_line_gets_it_back(monkeypatch):
    no_line = ("You should check your maize field at least once a week for unusual patterns like insect damage, "
               "larvae, or stunted growth.")
    assert not fr.SAFETY_RE.search(no_line)
    llm_on(monkeypatch, no_line)
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    assert fd.mode == "llm:fake", fd.problems
    assert_line_first(fd.text)
    assert fd.text == f"{CAVEAT['sentence']} {LINE} {no_line}"


# (e) no safety passage: nothing is injected
F6_IDS = ["APNI-SARI-2023-MAIZE:p22-sacks", "APNI-SARI-2023-MAIZE:p22-drying", "APNI-SARI-2023-MAIZE:p22-shelling"]
F6_DRAFT = (
    "1. Dry the maize immediately after harvest to reduce moisture content to 10-12% [APNI-SARI-2023-MAIZE:p22-drying].\n"
    "2. Shell the maize and remove the husks before storage [APNI-SARI-2023-MAIZE:p22-shelling].\n"
    "3. Use recommended storage chemicals and store the maize in jute sacks lined with polythene bags "
    "[APNI-SARI-2023-MAIZE:p22-sacks].")


def test_e_no_safety_passage_no_line_injected(monkeypatch):
    ps = [knowledge.reference(i) for i in F6_IDS]
    assert line_for(ps) is None
    assert fr.ensure_safety_line("Dry the maize.", ps) == ("Dry the maize.", [])
    fd = fr.propose(F6_DRAFT, "Weevils in stored maize?", passages=ps)
    assert not fr.SAFETY_RE.search(fd.text) and "AEA" not in fd.text, fd.text
    llm_on(monkeypatch, "Dry the maize right after harvest. Shell it and remove the husks before storage.")
    fd = fr.propose(F6_DRAFT, "Weevils in stored maize?", passages=ps)
    assert fd.mode == "llm:fake" and fd.text == ("Dry the maize right after harvest. Shell it and remove the husks "
                                                 "before storage."), fd


def test_rainfall_record_is_never_the_source_of_the_line():
    rain = {"id": "RAINFALL-EJURA-2026", "text": "Spray when it is dry."}
    assert line_for([rain]) is None


# Never truncated: if the line can't fit, no SMS is proposed and the officer is told why
def test_line_that_cannot_fit_is_never_cut_the_officer_writes_it(monkeypatch):
    monkeypatch.setattr(fr, "MAX_CHARS", len(CAVEAT["sentence"]) + len(LINE) - 10)
    llm_on(monkeypatch, SMS_B1)
    fd = fr.propose(DRAFT_B1, Q, zone_caveat=CAVEAT, passages=F1_PS)
    assert fd.text == "" and fd.needs_officer_text
    assert any("pesticide sentence" in p and "does not fit" in p for p in fd.problems), fd.problems


def test_ensure_is_idempotent_and_does_not_duplicate_a_verbatim_line():
    text, notes = fr.ensure_safety_line(f"{CAVEAT['sentence']} Weed well.", F1_PS, caveat=CAVEAT)
    again, notes2 = fr.ensure_safety_line(text, F1_PS, caveat=CAVEAT)
    assert again == text and text.count(LINE) == 1 and notes2 == []
    # the stub verbatim fallback quotes the passage: the line is not repeated without its source name
    plain = LINE.replace(" (APNI).", ".")
    text, _ = fr.ensure_safety_line(f"Weed well. {plain}", F1_PS)
    assert text == f"{LINE} Weed well.", text


def test_confirm_sentence_stays_last_when_sources_differ():
    text, _ = fr.ensure_safety_line(f"Weed well. {fr.CONFIRM}", F1_PS)
    assert text == f"{LINE} Weed well. {fr.CONFIRM}"


@pytest.mark.parametrize("ids", [F1_IDS, ["APNI-SARI-2023:weeds-herbicide"]])
def test_every_stub_verbatim_case_with_a_safety_passage_carries_the_line(ids):
    ps = [knowledge.reference(i) for i in ids]
    draft = llm.stub_draft("Worms in my maize?", ps, [])
    fd = fr.propose(draft, "Worms in my maize?", passages=ps)
    assert fd.text.startswith(line_for(ps)), fd.text
