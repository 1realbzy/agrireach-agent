"""F1 live regression (25 Oct, a5e9192, docs/live-eval-2026-10-25-run3.md): the farmer SMS lost the pesticide safety
line in run 2. Two bugs stacked:
1. LATE_CLAIM_RE matched any "is/are still", so the faithful model SMS "If the worms are still a problem, talk to your
   local Agriculture Extension Agent..." was rejected as a late-timing claim (in both runs).
2. The rule-based fallback then dropped "consult your local Agriculture Extension Agent (AEA)...": ALLOWED_OFFICER
   only knew "Agricultural Extension Agent", so the leftover "(AEA)" read as an officer instruction.
The texts below are the recorded live ones. Offline: the model rewrite and the judge's network call are replaced."""
import json

import pytest

from agrireach import claim_check, farmer_reply as fr, judge, knowledge, llm

IDS = ["APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
       "APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p22-sacks"]
PS = [knowledge.reference(i) for i in IDS]
Q = ("Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. "
     "What next?")
CAUTION = ("Caution: the curated sources cover Northern Ghana only. The guidance below comes from them and may not "
           "apply in Adaklu; the officer should confirm local timing.\n\n")
# Officer drafts that passed the draft check (A1, A2).
DRAFT_RUN1 = CAUTION + (
    "The farmer should scout the maize field at least once a week, looking for unusual patterns such as insect damage, "
    "larvae, or stunted growth [APNI-SARI-2023-MAIZE:p18-scouting]. If the infestation persists despite spraying, "
    "consult your local Agricultural Extension Agent (AEA) for advice on recommended fall armyworm control pesticides in "
    "your area [APNI-SARI-2023-MAIZE:p20-faw-control]. Additionally, consider rotating maize with non-host plants like "
    "groundnut, deep ploughing, and proper weeding to reduce future infestations [APNI-SARI-2023-MAIZE:p20-faw-prevention].")
DRAFT_RUN2 = CAUTION + (
    "If the infestation continues, consult your local Agriculture Extension Agent (AEA) for advice on the recommended "
    "fall army worm control pesticide in your area [APNI-SARI-2023-MAIZE:p20-faw-control]. Additionally, consider "
    "rotating maize with non-host plants like groundnut to reduce future infestations "
    "[APNI-SARI-2023-MAIZE:p20-faw-prevention]. Ensure proper weeding of the maize field to minimize infestations "
    "[APNI-SARI-2023-MAIZE:p20-faw-prevention]. For storage, treat well-dried and shelled maize with recommended storage "
    "chemicals and store in jute sacks lined with polythene bags [APNI-SARI-2023-MAIZE:p22-sacks].")
# The model SMS the late-timing layer rejected (A1, A2).
SMS_RUN1 = ("You should check your maize field at least once a week for unusual patterns like insect damage, larvae, or "
            "stunted growth. If the worms are still a problem after spraying, talk to your local Agricultural Extension "
            "Agent for advice on recommended pesticides. Also, think about rotating maize with plants like groundnut, "
            "deep ploughing, and proper weeding to reduce future worm problems.")
SMS_RUN2 = ("If the worms are still a problem, talk to your local Agriculture Extension Agent for advice on the right "
            "pesticide to use. Also, think about planting groundnut or other non-host plants next time to reduce worm "
            "infestations. Make sure to weed your maize field well. When storing your maize, dry and shell it properly, "
            "then treat it with the recommended storage chemicals. Store it in jute sacks lined with polythene bags.")
CAVEAT = fr.zone_caveat("Adaklu")


def accepting_judge():
    seen = []

    def call(user):
        items = [l for l in user.splitlines() if ". SENTENCE: " in l]
        seen.extend(items)
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(len(items))]})
    return seen, call


# --- Bug 1: "is/are still <state>" is not a late-timing claim ---

@pytest.mark.parametrize("s", [
    "Fall armyworms are still a problem in the field.",
    "If the worms are still a problem, talk to your local Agriculture Extension Agent for advice on the right pesticide.",
    "If the worms are still a problem after spraying, talk to your local Agricultural Extension Agent.",
    "The larvae are still present in the whorl.",
    "If the infestation is still there, consult your local AEA.",
])
def test_present_tense_still_is_not_a_late_timing_claim(s):
    assert not claim_check.LATE_CLAIM_RE.search(s), s


@pytest.mark.parametrize("s", [
    "The fertiliser can still be applied.",
    "You can still apply the subsidised fertiliser, but only if the soil is moist.",
    # F5 drafts recorded live on a5e9192 (A1, A2)
    "The subsidised fertiliser can still be applied, but only if the soil is moist to enhance nutrient uptake.",
    "If the soil is moist, it is still worth applying the fertiliser to enhance nutrient uptake.",
    "It is not too late to top dress.",
    "Top dressing is still possible at two months.",
    "Maize could still be planted in July.",
    "There is still time to apply fertiliser.",
])
def test_late_action_claims_are_still_caught(s):
    assert claim_check.LATE_CLAIM_RE.search(s), s


def test_faw_still_a_problem_sentence_passes_the_late_layer_but_late_claim_does_not():
    faw = "APNI-SARI-2023-MAIZE:p20-faw-control"
    ok = f"Fall armyworms are still a problem in the field [{faw}]."
    assert not any("late" in p for p in claim_check.check_claims(ok, PS, judge=False).problems)
    # shares words with the passage, so the lexical layer passes and only the late-timing layer can reject it
    bad = f"Recommended pesticides can still be applied to control infestations [{faw}]."
    assert any("not too late" in p for p in claim_check.check_claims(bad, PS, judge=False).problems)


@pytest.mark.parametrize("sms", [SMS_RUN1, SMS_RUN2])
def test_recorded_f1_model_sms_passes_the_sms_claim_check(sms):
    seen, call = accepting_judge()
    assert fr.sms_claims(f"{CAVEAT['sentence']} {sms}", PS, judge_call=call, caveat=CAVEAT) == []
    assert seen


# --- Bug 2: the rule fallback keeps "Agriculture Extension Agent (AEA)" ---

def test_allowed_officer_accepts_agriculture_extension_agent():
    for t in ("consult your local Agriculture Extension Agent (AEA) for advice on the recommended pesticide",
              "consult your local Agricultural Extension Agent (AEA) for advice on the recommended pesticide"):
        assert not fr.OFFICER_RE.search(fr.ALLOWED_OFFICER.sub("", t)), t


@pytest.mark.parametrize("draft", [DRAFT_RUN1, DRAFT_RUN2])
def test_rule_rewrite_keeps_the_safety_line_and_the_referral(draft):
    text = fr.rule_rewrite(draft)
    assert "Extension Agent (AEA) for advice on" in text and fr.SAFETY_RE.search(text), text
    assert not any("safety line" in p for p in fr.check(text, draft))


# --- The live paths, offline ---

@pytest.mark.parametrize("draft,sms", [(DRAFT_RUN1, SMS_RUN1), (DRAFT_RUN2, SMS_RUN2)])
def test_faithful_model_sms_is_proposed_with_the_safety_line(monkeypatch, draft, sms):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (sms, "llm:fake"))
    monkeypatch.setattr(judge, "_call", accepting_judge()[1])
    fd = fr.propose(draft, Q, zone_caveat=CAVEAT, passages=PS)
    assert fd.mode == "llm:fake", fd.problems
    assert fd.text.startswith(CAVEAT["sentence"]) and "pesticide" in fd.text and "Extension Agent" in fd.text
    assert not any("safety line" in p or "model rewrite rejected" in p for p in fd.problems), fd.problems


@pytest.mark.parametrize("draft", [DRAFT_RUN1, DRAFT_RUN2])
def test_rule_fallback_keeps_the_safety_line(monkeypatch, draft):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: ("Spray [X] now.", "llm:fake"))  # fails check()
    monkeypatch.setattr(judge, "_call", accepting_judge()[1])
    fd = fr.propose(draft, Q, zone_caveat=CAVEAT, passages=PS)
    assert fd.mode == "rule" and fd.text.startswith(CAVEAT["sentence"])
    assert "Extension Agent (AEA) for advice on" in fd.text and "pesticide" in fd.text, fd.text
    assert not any("safety line" in p for p in fd.problems), fd.problems
