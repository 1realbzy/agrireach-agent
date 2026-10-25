"""F5 live (25 Oct, a6222d1): "The subsidised fertiliser can still be applied, but only if the soil is moist." was
accepted twice, by the draft judge ("Passage implies") and the SMS judge. The passages give the ideal time (6 weeks)
and say nothing about applying at about two months. A "still / not too late" claim needs a passage on late timing."""
from agrireach import claim_check, farmer_reply

MOIST = {"id": "APNI-SARI-2023-MAIZE:p13-topdress-moisture", "source_id": "APNI-SARI-2023-MAIZE",
         "text": "Top dressing should be done when the soil is moist to enhance nutrient uptake. If the soil is very dry, "
                 "delay application until some rains are received."}
TIMING = {"id": "APNI-SARI-2023-MAIZE:p13-topdress-timing", "source_id": "APNI-SARI-2023-MAIZE",
          "text": "The ideal time for top dressing is at 6 weeks after planting."}
LATE = {"id": "X:late", "source_id": "X", "text": "Top dressing applied later than 8 weeks after planting still "
        "gives some yield benefit."}


def test_still_claim_without_a_late_timing_passage_is_rejected_even_if_the_judge_accepts():
    draft = (f"The subsidised fertiliser can still be applied, but only if the soil is moist [{MOIST['id']}]. "
             f"The ideal time for top dressing is at 6 weeks after planting [{TIMING['id']}].")
    r = claim_check.check_claims(draft, [MOIST, TIMING], judge=False)
    assert any("late" in p for p in r.problems), r.problems


def test_sms_still_claim_is_rejected():
    sms = "You can still apply the subsidised fertiliser, but only if the soil is moist."
    assert any("late" in p for p in farmer_reply.sms_claims(sms, [MOIST, TIMING]))


def test_still_claim_backed_by_a_late_timing_passage_passes_and_plain_advice_is_untouched():
    ok = f"Top dressing can still help after 8 weeks [{LATE['id']}]."
    assert not any("late" in p for p in claim_check.check_claims(ok, [LATE], judge=False).problems)
    plain = f"If the soil is very dry, delay application until some rains are received [{MOIST['id']}]."
    assert claim_check.check_claims(plain, [MOIST], judge=False).problems == []
