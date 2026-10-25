"""Live run3 on a5e9192 (docs/live-eval-2026-10-25-run3.md): sentences that carry no advice were judged, and rejected,
because they were slightly outside the whole-sentence exemption shapes in claim_check.NOT_JUDGED_RE. The shapes are
widened only by fixed, advice-free parts; anything added beyond a shape (a clause, a comma, ";", ":", a figure) is still
judged. The exempt sentences below are the recorded live texts (citations removed, as not_judged sees them)."""
import pytest

from agrireach import claim_check

NOW_EXEMPT = [
    # core task 12: a bold heading in front of an allowed shape
    "- **Planting Window:** Sources disagree.",
    "- **Planting Depth:** Sources disagree.",
    "- **Plant Spacing:** Sources disagree.",
    "Planting window: Sources disagree.",
    "**Plant Spacing**: sources differ on the spacing.",
    # core task 11: the bare choice instruction
    "Choose which planting window to follow.",
    "Choose which planting depth to follow.",
    "Choose which plant spacing to follow.",
    # A2 F7: "do not know if" with no subject
    "Do not know if the maize is safe to sell or feed.",
    # EJB2-4, core task 11: describing the attached rainfall record
    "A rainfall record is attached for your reference.",
    "A rainfall record is attached for the officer's reference.",
    "A rainfall record for Ejura is attached.",
    "This is a model estimate.",
    # A2 F6 / A1 F6: an officer inspection detail and a referral to an allowed person
    "The officer should inspect the maize for signs of infestation or refer to a specialist for a diagnosis.",
    "Inspect the maize for signs of infestation or refer to a specialist if unsure.",
]

STILL_JUDGED = [
    # heading prefix + advice
    "**Planting Window:** Sources disagree, plant in June.",
    "Planting window: plant in June.",
    "**Planting Window:** plant in June.",
    "Spray mancozeb weekly: Sources disagree.",
    "Plant early: Sources disagree.",
    "Planting window: Sources disagree; plant in June.",
    # bare choice + advice
    "Choose which window to follow and spray now.",
    "Choose which planting window to follow, then plant in June.",
    "Choose which of 15 ppb or 4 ppb applies.",
    # subjectless "do not know" + advice, and imperatives that are not "do not know"
    "Do not know if the maize is safe, so do not sell it.",
    "Do not know if the maize is safe or spray it now.",
    "Do not know if the maize is safe to sell, feed it to animals.",
    "Do not say the maize is mouldy.",
    "Do not confirm whether the maize exceeds these limits.",
    # rainfall record + advice or figures
    "A rainfall record is attached; apply 50 kg NPK.",
    "A rainfall record is attached, so plant now.",
    "A rainfall record is attached and shows 185.5 mm of rain.",
    "A rainfall record for 24 of 30 days is attached.",
    "This is a model estimate, so plant now.",
    "Use this data to inform your planting decision, but note that this is a model estimate and may differ from local conditions.",
    # inspection/referral + advice
    "The officer should inspect the maize for signs of infestation and spray it.",
    "Refer to a specialist and spray mancozeb weekly.",
    "Inspect the maize for signs of infestation or refer to a specialist if the farmer sprays.",
    "Refer to the label for the dose.",
    # deliberately left judged (see report): not a pure officer action / fixed descriptive shape
    "Choose the appropriate window based on local conditions and weather information.",
    "**Soybean Planting Advice for Tamale**",
]


@pytest.mark.parametrize("s", NOW_EXEMPT)
def test_recorded_live_false_rejects_are_exempt(s):
    assert claim_check.not_judged(s), s


@pytest.mark.parametrize("s", STILL_JUDGED)
def test_advice_added_to_the_new_shapes_is_still_judged(s):
    assert not claim_check.not_judged(s), s
    assert not claim_check.NOT_JUDGED_RE.search(s), s


def test_cited_rainfall_record_sentence_is_not_sent_to_the_judge():
    rid = "RAINFALL-OPEN-METEO:ejura:2026-10-25"
    rain = {"id": rid, "source_id": "RAINFALL-OPEN-METEO",
            "text": "Rainfall record for Ejura (model estimate): 24 of 30 days with at least 1 mm of rain."}
    seen = []

    def call(user):
        seen.append(user)
        raise AssertionError("judge must not be called")
    r = claim_check.check_claims(f"A rainfall record is attached for your reference [{rid}].", [rain], judge=True,
                                 judge_call=call)
    assert not seen and not any("judge" in p for p in r.problems), r.problems
