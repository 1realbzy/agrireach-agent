"""Farmer-facing text: plain, no citations, no officer wording, no invented figures, short, language-aware."""
from agrireach import farmer_reply as fr

OFFICER = ("For soybean in Tamale, the officer should advise the farmer to harvest when 9 out of 10 pods have turned "
           "brown [IITA-SOY-2009:p23-harvest]. Note: the source is from 2009.\n"
           "Advise the farmer to dry the grain to 12% moisture before storage [IITA-SOY-2009:p24-storage].")


def test_rule_rewrite_strips_citations_and_officer_wording():
    t = fr.rule_rewrite(OFFICER)
    assert "[" not in t and "officer should" not in t.lower() and "advise the farmer" not in t.lower()
    assert "9 out of 10 pods" in t and "12%" in t and "Note:" not in t
    assert fr.check(t, OFFICER) == []


def test_check_flags_brackets_officer_wording_length_and_new_figures():
    probs = fr.check("The officer should advise 50 kg [X:p1]. " + "word " * 150, OFFICER)
    joined = " ".join(probs)
    assert "citation" in joined and "officer" in joined and "600" in joined and "50" in joined
    assert fr.check("Your extension officer will confirm which to follow.", OFFICER) == []


def test_non_english_needs_officer_text():
    d = fr.propose(OFFICER, "Mɛdua soya bere bɛn?", language="twi")
    assert d.text == "" and d.needs_officer_text and d.language == "twi"


def test_bad_model_rewrite_falls_back_to_rule_text(monkeypatch):
    def bad(*a, **k):
        return "The officer should advise 80 kg per acre [IITA-SOY-2009:p23-harvest].", "llm"
    monkeypatch.setattr(fr, "_llm_rewrite", bad)
    monkeypatch.setattr(fr.llm, "mode", lambda: "llm")
    d = fr.propose(OFFICER, "When should I harvest soybean?", "en")
    assert d.mode == "rule" and "80" not in d.text and "[" not in d.text and d.problems


def test_region_caution_is_raised_to_the_officer_not_silently_dropped():
    officer = ("Caution: the curated sources cover Northern Ghana only. The guidance below comes from them and may not "
               "apply in Kumasi; the officer should confirm local timing.\n\nPlant when the rains are well "
               "established [IITA-SSPING-2022:p18-moisture].")
    d = fr.propose(officer, "When should I plant soybean in Kumasi?", "en")
    assert "Caution" not in d.text and "officer" not in d.text.lower()
    assert any("Northern Ghana" in p for p in d.problems)
