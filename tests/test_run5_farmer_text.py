"""Run 5 farmer-text findings (docs/live-eval-2026-10-25-run5-approval.md):
5a. EJ's SMS went to the farmer with heading labels ("Planting Window: ...", "Planting Time: ...") and double
    spaces: farmer text is tidied (markdown, heading labels, whitespace) on the rule and model paths, before checks.
5b. S-Kintampo repeated the pesticide referral: the model's own "Ask your local Agricultural Extension Agent for
    advice on recommended pesticides..." after the source's line. A near-identical safety sentence is removed
    (and named) before the length check, which matters under the 268-character Unicode limit."""
from pathlib import Path

from agrireach import farmer_reply as fr, knowledge, llm
from agrireach.channels import sms

EJ_DRAFT = (Path(__file__).parent / "fixtures/run5_ej_draft.txt").read_text()
EJ_IDS = ["IITA-MAIZE-2025:p15-three-good-rains", "MOFA-MAIZE:p11-transition-major",
          "IITA-MAIZE-2025:p16-transition-major", "MOFA-MAIZE:p12-transition-minor", "MOFA-MAIZE:p10-when-to-plant",
          "IITA-MAIZE-2025:p16-transition-minor"]
EJ_PS = [knowledge.reference(i) for i in EJ_IDS]
FAW_PS = [knowledge.reference(i) for i in ["APNI-SARI-2023-MAIZE:p20-faw-prevention",
                                           "APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p18-scouting"]]
LINE = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)."
KINTAMPO_REPEAT = "Ask your local Agricultural Extension Agent for advice on recommended pesticides to control Fall Armyworm."


def model(monkeypatch, text):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (text, "llm:fake"))


# --- 5a ---

def test_recorded_ejura_rule_text_has_no_heading_labels_or_double_spaces():
    fd = fr.propose(EJ_DRAFT, "When should I plant maize in Ejura?", conflicts=True, passages=EJ_PS)
    assert fd.mode == "rule"
    assert "Planting Window:" not in fd.text and "Planting Time:" not in fd.text and "**" not in fd.text
    assert "  " not in fd.text and " ." not in fd.text, fd.text
    assert ("The major season transition period is either from mid-March to end of April or from end of March to "
            "end of April.") in fd.text
    assert fd.text.startswith("The major season transition") and fd.text.endswith(fr.CONFIRM)


def test_model_text_is_tidied_before_the_checks(monkeypatch):
    model(monkeypatch, "**Planting window:** Plant after three good rains within the planting window to ensure "
                       "enough soil moisture.  Sow after the rains have stabilized   to avoid wilting .")
    fd = fr.propose(EJ_DRAFT, "When should I plant maize in Ejura?", passages=EJ_PS)
    assert fd.mode == "llm:fake", fd.problems
    assert fd.text == ("Plant after three good rains within the planting window to ensure enough soil moisture. "
                       "Sow after the rains have stabilized to avoid wilting.")


def test_tidy_keeps_ordinary_sentences_and_times():
    t = "In the transition zone, plant from mid-March (MoFA). Spray at 6:30 in the morning. Sow when the soil is moist."
    assert fr.tidy(t) == t
    assert fr.tidy("1. Planting time: plant after three good rains.") == "Plant after three good rains."


# --- 5b ---

def test_kintampo_repeat_of_the_safety_sentence_is_removed_and_named():
    caveat = fr.zone_caveat("Kintampo")
    text = (f"{caveat['sentence']} To manage Fall Armyworm in your maize, rotate crops with groundnut. Keep your "
            f"field well-weeded. {KINTAMPO_REPEAT}")
    out, notes = fr.ensure_safety_line(text, FAW_PS, caveat)
    assert out.startswith(f"{caveat['sentence']} {LINE}") and KINTAMPO_REPEAT not in out
    assert any(KINTAMPO_REPEAT in n and "repeat" in n for n in notes), notes
    # a different pesticide sentence is not a repeat
    other = "Application of recommended pesticides can help to control infestations once they occur."
    assert other in fr.ensure_safety_line(f"Weed well. {other}", FAW_PS)[0]


def test_repeat_is_removed_before_the_268_unicode_limit_is_checked(monkeypatch):
    s1 = "Check your maize field in Kɔforidua at least once a week for insect damage on the leaves."
    assert len(f"{LINE} {s1} {KINTAMPO_REPEAT}") > 268 >= len(f"{LINE} {s1}")
    model(monkeypatch, f"{s1} {KINTAMPO_REPEAT}")
    fd = fr.propose("\n".join(llm.stub_draft("q", FAW_PS, []).splitlines()[1:]), "q", passages=FAW_PS)
    assert fd.mode == "llm:fake", fd.problems
    assert fd.text == f"{LINE} {s1}" and sms.measure(fd.text).encoding == "UCS-2"
    assert sms.length_prompt(fd.text) is None
