"""EVALS F14: an approved advisory as a voice-message script (sender first, length cap, every figure kept)."""
import pytest

from agrireach import citation_check, evalset, knowledge, voice_script

DRY_SPELL = (knowledge.reference("APNI-SARI-2023-MAIZE:p13-topdress-moisture")["text"] +
             " [APNI-SARI-2023-MAIZE:p13-topdress-moisture]")


def figures(t):
    return sorted((f.kind, f.value, f.unit, f.bound) for f in citation_check.extract_figures(t))


def test_dry_spell_advisory_script_opens_with_sender_and_purpose_and_keeps_figures():
    s = voice_script.build(DRY_SPELL, "Ama Mensah", "maize fertilizer")
    first = s.text.split("\n\n")[0]
    assert "AgriReach" in first and "Ama Mensah" in first and "maize fertilizer" in first
    assert s.ok and s.seconds <= voice_script.MAX_SECONDS
    assert figures(voice_script.speakable(DRY_SPELL)) == figures(citation_check.CITE_RE.sub("", DRY_SPELL))
    assert figures(s.text) == figures(citation_check.CITE_RE.sub("", DRY_SPELL))  # opening/closing add none
    assert "[" not in s.text


def test_overlong_advice_is_flagged_not_cut():
    s = voice_script.build(" ".join([DRY_SPELL] * 12), "Ama Mensah")
    assert not s.ok and "shorten" in s.problems[0] and s.text.count("6 weeks") == 12


def test_needs_a_named_officer():
    with pytest.raises(ValueError):
        voice_script.build(DRY_SPELL, " ")


def test_f14_is_now_a_runnable_eval():
    e = next(x for x in evalset.load() if x["id"] == "F14")
    assert not e.get("skip") and e["kind"] == "voice_script"
    assert evalset.grade_voice_script(e) == []


def test_stt_flags_looping_or_prompt_echo_transcripts():
    from agrireach.channels import stt
    for bad in ["Croppea. Croppea. Croppea. Croppea.",
                "The land of Wa, Bolgatanga, Wa, Bolgatanga, and the land of Wa, Bolgatanga, and the land of Wa."]:
        t = stt.check(stt.Transcript(bad, "en", 0.9, 5, "fake"))
        assert any("repeats itself" in w for w in t.warnings)
    ok = stt.check(stt.Transcript("When should I harvest my soybean? I farm near Tamale.", "en", 0.9, 5, "fake"))
    assert ok.warnings == []
