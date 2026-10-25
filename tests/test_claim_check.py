"""Claim check for sentences without figures (deterministic layers and the optional judge, offline)."""
import json
import sys
from pathlib import Path

import pytest

from agrireach import claim_check, judge, knowledge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import replay_drafts  # noqa: E402

P = {i: knowledge.reference(i) for i in [
    "APNI-SARI-2023:p11-planting-window", "IITA-SSPING-2022:p18-planting-window", "IITA-SSPING-2022:p18-moisture",
    "APNI-SARI-2023:p11-spacing", "IITA-SSPING-2022:p17-spacing", "APNI-SARI-2023:weeds-herbicide",
    "APNI-SARI-2023-MAIZE:p13-topdress-timing"]}
PS = list(P.values())
WINDOW = {"planting_window": [P["APNI-SARI-2023:p11-planting-window"], P["IITA-SSPING-2022:p18-planting-window"]]}
SPACING = {"plant_spacing": [P["APNI-SARI-2023:p11-spacing"], P["IITA-SSPING-2022:p17-spacing"]]}
check = lambda d, conflicts=None, **k: claim_check.check_claims(d, PS, conflicts, judge=False, **k)

# Real drafts from 23 Oct (EVALS runs C/E task 12 and D/E task 5).
BOTH_AGREE = "- Both sources agree that planting should be done when the rains are well established [IITA-SSPING-2022:p18-moisture]."
DIAGNOSIS = ("The farmer should consult the label and the officer for guidance on chemical use "
             "[APNI-SARI-2023:weeds-herbicide]. This is not a diagnosis. The officer should inspect the crop or refer "
             "the farmer to an expert for a proper diagnosis [APNI-SARI-2023:weeds-herbicide].")


def test_agreement_citing_one_source_fails():
    r = check(BOTH_AGREE, WINDOW)
    assert not r.ok and "cites only IITA-SSPING-2022" in r.problems[0]


def test_agreement_where_only_one_cited_source_says_it_fails():
    d = ("Both sources agree that planting should wait until the rains are well established "
         "[APNI-SARI-2023:p11-planting-window][IITA-SSPING-2022:p18-moisture].")
    r = check(d)
    assert not r.ok and "APNI-SARI-2023 does not say this" in r.problems[0]


def test_detected_disagreement_described_as_agreement_fails():
    d = ("The sources agree on when to plant soybean "
         "[APNI-SARI-2023:p11-planting-window][IITA-SSPING-2022:p18-planting-window].")
    r = check(d, WINDOW)
    assert not r.ok and "disagreement on planting window as agreement" in r.problems[0]


def test_agreement_on_a_figure_both_sources_give_passes():
    # Real 25 Oct run F2 task 11: true, both give 50 cm between rows, even though within-row spacing conflicts.
    d = "Both agree on 50 cm between rows [APNI-SARI-2023:p11-spacing][IITA-SSPING-2022:p17-spacing]."
    assert check(d, SPACING).ok


def test_disagreement_stated_as_disagreement_is_not_an_agreement_claim():
    d = ("The sources do not agree: one says late July [APNI-SARI-2023:p11-planting-window], the other mid-July "
         "[IITA-SSPING-2022:p18-planting-window].")
    assert check(d, WINDOW).ok


def test_named_source_must_be_cited():
    r = check("IITA says to wait until the rains are well established [APNI-SARI-2023:p11-planting-window].")
    assert not r.ok and "names IITA but cites no IITA passage" in r.problems[0]
    assert check("IITA says to wait until the rains are well established [IITA-SSPING-2022:p18-moisture].").ok


def test_herbicide_passage_cited_for_diagnosis_fails():
    r = check(DIAGNOSIS)
    assert not r.ok
    assert any("'This is not a diagnosis.'" in p for p in r.problems)
    assert any("proper diagnos" in p for p in r.problems)


def test_figure_only_and_officer_lines_are_not_false_rejects():
    d = ("The officer should not recommend a chemical or dose. The farmer should read and follow the "
         "manufacturer's instructions [APNI-SARI-2023:weeds-herbicide]. One source suggests 15 cm "
         "[APNI-SARI-2023:p11-spacing], while another recommends 10 cm [IITA-SSPING-2022:p17-spacing].")
    assert check(d, SPACING).ok


def test_sentence_splitting_attaches_next_citation_within_paragraph_only():
    ss = claim_check.sentences("First claim. Second claim [A].\nThird claim.")
    assert [(s.text, s.ids, s.inline) for s in ss] == [("First claim.", ["A"], False),
                                                       ("Second claim [A].", ["A"], True), ("Third claim.", [], False)]


# --- Recorded real drafts: what the deterministic layers flag (hand-labelled in EVALS.md) ----------------------
KNOWN_DEFECTS = {("B", "5"), ("D", "5"), ("E", "5"), ("C", "12"), ("E", "12")}


def _flags(**kw):
    out = set()
    for r in replay_drafts.recorded():
        ps, conflicts = replay_drafts.passages_and_conflicts(r["sources"])
        if not claim_check.check_claims(r["draft"], ps, conflicts, **kw).ok:
            out.add((r["run"], r["task"].split()[0]))
    return out


def test_deterministic_layers_flag_exactly_the_known_defects_in_recorded_drafts():
    assert len(replay_drafts.recorded()) == 69
    assert _flags(judge=False) == KNOWN_DEFECTS


# --- Optional judge, offline with recorded replies -----------------------------------------------------------
FIX = json.loads((ROOT / "tests/fixtures/judge_replies.json").read_text())
RAW = {(r["run"], r["task"]): r["raw"] for r in FIX["replies"]}
# Judge-only flags in the recorded replies, labelled by hand: True = the sentence really adds an unsupported claim.
JUDGE_LABELS = {("A", "11"): True,   # "up to 5 cm but not deeper than 3 cm": flipped bound (figure check also fails it)
                ("F1", "F5"): True, ("F2", "F5"): True,   # "It is still worth applying the subsidised fertiliser"
                ("F1", "F7"): True, ("F2", "F7"): True,   # "should not be sold ... or used as animal feed": not in source
                ("F1", "F2"): False}  # "Scout ... at least once a week ... for armyworm signs": supported paraphrase
# Before place-name masking the judge also rejected the Kumasi planting draft in all 7 runs ("Kumasi not mentioned"):
# 8/59 false rejects. Masked, it passes; the region caveat for Kumasi is added by code, not judged.


def test_judge_parse_requires_a_verdict_for_every_item():
    items = [("a", [P["IITA-SSPING-2022:p18-moisture"]]), ("b", [P["IITA-SSPING-2022:p18-moisture"]])]
    with pytest.raises(ValueError):
        judge.parse('{"verdicts": [{"n": 1, "verdict": "supported"}]}', items)
    out = judge.parse('noise {"verdicts": [{"n": 1, "verdict": "supported"}, {"n": 2, "verdict": "not_supported", '
                      '"why": "adds claim"}]}', items)
    assert [v["verdict"] for v in out] == ["supported", "not_supported"]


def test_judge_error_is_recorded_and_fails_closed():
    # Changed 25 Oct (review item 2): a judge outage used to reject nothing; it now fails the check.
    def boom(_):
        raise TimeoutError("provider down")
    d = "Plant when the rains are well established [IITA-SSPING-2022:p18-moisture]."
    r = claim_check.check_claims(d, PS, judge=True, judge_call=boom)
    assert not r.ok and r.judge_failed and "provider down" in r.judge["error"]


def _replay_judge(raw):
    """Recorded verdicts for the sentences the judge was asked about when the reply was recorded. Since 25 Oct the
    judge also gets officer-addressed and uncited sentences; the recordings have no verdict for those, so they are
    answered 'supported' here. Their false-reject rate is measured live (EVALS.md), not by this offline replay."""
    recorded = {int(v["n"]): v for v in json.loads(raw[raw.find("{"):])["verdicts"]}

    def call(user):
        n = user.count(". SENTENCE: ")
        return json.dumps({"verdicts": [recorded.get(i + 1, {"n": i + 1, "verdict": "supported", "why": "unrecorded"})
                                        for i in range(n)]})
    return call


def test_judge_replay_flags_and_false_reject_rate():
    flagged_by_judge = set()
    for r in replay_drafts.recorded():
        key = (r["run"], r["task"].split()[0])
        ps, conflicts = replay_drafts.passages_and_conflicts(r["sources"])
        raw = RAW.get((r["run"], r["task"]))
        res = claim_check.check_claims(r["draft"], ps, conflicts, judge=raw is not None,
                                       judge_call=_replay_judge(raw) if raw else None)
        assert not (res.judge or {}).get("error")
        if any("judge model" in p for p in res.problems):
            flagged_by_judge.add(key)
    assert flagged_by_judge == set(JUDGE_LABELS)
    defective = KNOWN_DEFECTS | {k for k, v in JUDGE_LABELS.items() if v}
    clean = 69 - len(defective)
    false_rejects = [k for k, v in JUDGE_LABELS.items() if not v]
    assert (len(false_rejects), clean) == (1, 59)  # 1/59 = 1.7% of clean drafts (was 8/59 before masking)


def test_live_run_false_rejects_fixed():
    """From the 25 Oct live runs: officer directives ("Choose one.") failed the lexical check, and list markers
    ("1.") and "one source says X, another says Y" lines were sent to the judge and rejected."""
    d = ("Plant 15 cm apart [APNI-SARI-2023:p11-spacing], or 10 cm apart [IITA-SSPING-2022:p17-spacing]. Choose one.\n"
         "Choose which to follow. Rows are 50 cm apart [APNI-SARI-2023:p11-spacing].")
    assert check(d, SPACING).ok
    asked = []

    def fake(prompt):
        asked.append(prompt)
        n = prompt.count(". SENTENCE: ")
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "not_supported", "why": "x"} for i in range(n)]})

    d2 = ("1. One source says 15 cm between plants [APNI-SARI-2023:p11-spacing], another says 10 cm "
          "[IITA-SSPING-2022:p17-spacing].\n2. Plant spacing is disputed [APNI-SARI-2023:p11-spacing].")
    r = claim_check.check_claims(d2, PS, SPACING, judge=True, judge_call=fake)
    assert r.ok and asked == []  # nothing left to ask the judge about


def test_place_names_are_masked_before_the_judge_unless_the_passage_has_them():
    seen = []

    def fake(prompt):
        seen.append(prompt)
        return json.dumps({"verdicts": [{"n": 1, "verdict": "supported", "why": "ok"}]})

    d = "For soybean planting in Kumasi, plant between mid-June and late July [APNI-SARI-2023:p11-planting-window]."
    r = claim_check.check_claims(d, PS, judge=True, judge_call=fake)
    assert r.ok and "Kumasi" not in seen[0] and "the farmer's area" in seen[0]
    assert r.judge["verdicts"][0]["sentence"] == d  # the officer sees the original sentence
    assert "northern region" in seen[0].lower()  # the passage's own place name is kept


def test_gazetteer_has_all_districts_and_skips_english_words():
    from agrireach import places
    assert len({v["region"] for v in places.gazetteer().values()}) == 16
    assert [p["name"] for p in places.find("Jirapa and Wa, not Kumasi")] == ["Jirapa", "Wa", "Kumasi"]
    assert places.find("she sang to tease her friend about la la land") == []
    assert places.is_northern(places.find("Nadowli-Kaleo")[0]["region"])
