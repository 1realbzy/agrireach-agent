"""Scoffer's and QA's review of ae53dc3: the judge exemptions (claim_check.NOT_JUDGED_RE) matched a phrase anywhere in
a sentence, so advice tacked on with "and", ";", ":" or a comma skipped the judge. Exemptions are now whole-sentence
shapes: anything beyond the allowed shape is judged. Offline: the judge's network call is replaced."""
import json

import pytest

from agrireach import claim_check, farmer_reply as fr

# Each of these adds advice to an exempt-looking opening, so it must reach the judge.
SMUGGLED = [
    "The officer should inspect the field and tell the farmer to spray it now.",
    "We do not know the variety so plant early.",
    "Choose the appropriate window and plant before the rains end.",
    "Apply 50 kg of NPK per acre; the timing varies by source.",
    "The officer should inspect the field and tell the farmer to burn all affected plants.",
    "The officer should refer the farmer to spray mancozeb every week.",
    "We do not know the exact dose and the farmer should spray mancozeb weekly.",
    "Choose the appropriate option: spray mancozeb weekly.",
    "Sources disagree, but mouldy maize is safe to feed to animals.",
    "Feed the mouldy maize to your animals, it is not disputed.",
    "The officer should inspect the field because the maize is safe to feed to animals.",
    "The passages do not mention this method because it always works.",
    "One source says 5 cm, another says 3 cm, and mouldy maize is safe to feed to animals.",
    "Spray mancozeb weekly since sources differ.",
]

# Short shapes that give no advice: they stay exempt (live false rejects, docs/live-eval-2026-10-25-run2.md).
EXEMPT = [
    "Refer the farmer to your local AEA.",
    "The officer should inspect the field.",
    "The officer should refer the farmer to an expert for a proper diagnosis.",
    "Choose the appropriate window.",
    "We do not know the variety.",
    "The curated sources do not cover this pest.",
    "The timing varies by source.",
    "Sources disagree on the planting window.",
    "For plant spacing, sources disagree.",
    "Plant spacing is disputed.",
    "The farmer asks when to plant soybeans in Tamale.",
]

MOULD = {"id": "TEST-MOULD:p1", "source_id": "TEST-MOULD", "title": "Test guide",
         "text": "Mouldy maize can contain aflatoxin. Do not eat or sell mouldy maize."}
BAD = "Mouldy maize is safe to feed to animals."


@pytest.mark.parametrize("s", SMUGGLED)
def test_advice_added_to_an_exempt_shape_is_judged(s):
    assert not claim_check.NOT_JUDGED_RE.search(s), s
    assert not claim_check.not_judged(s), s


@pytest.mark.parametrize("s", EXEMPT)
def test_short_shapes_with_no_advice_stay_exempt(s):
    assert claim_check.not_judged(s), s


def rejecting_judge():
    seen = []

    def call(user):
        items = [l for l in user.splitlines() if ". SENTENCE: " in l]
        seen.extend(items)
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "not_supported", "why": "not in the passage"}
                                        for i in range(len(items))]})
    return seen, call


@pytest.mark.parametrize("extra", ["", " Sources disagree, but", " It is not disputed:"])
def test_officer_draft_with_shared_words_reaches_the_judge(extra):
    # "mouldy" and "maize" are in the passage, so the lexical layer passes; only the judge can reject it.
    seen, call = rejecting_judge()
    sent = (extra.strip() + " " + BAD[0].lower() + BAD[1:]) if extra else BAD
    r = claim_check.check_claims(f"{sent} [TEST-MOULD:p1]", [MOULD], judge=True, judge_call=call)
    assert seen and not r.ok and any("according to the judge" in p for p in r.problems)


def test_farmer_sms_with_shared_words_reaches_the_judge():
    seen, call = rejecting_judge()
    problems = fr.sms_claims("Sources disagree, but mouldy maize is safe to feed to animals.", [MOULD],
                             judge_call=call)
    assert seen and any("according to the judge" in p for p in problems)
    seen2, call2 = rejecting_judge()
    assert any("according to the judge" in p for p in fr.sms_claims(BAD, [MOULD], judge_call=call2)) and seen2
