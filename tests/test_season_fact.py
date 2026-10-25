"""Officer-only facts: the question's received date next to the cited planting windows, and why a rainfall record
is or is not attached for planting and top-dressing questions. Facts only: no next window, no 'plant now'."""
import asyncio
import json
import re
from datetime import date
from pathlib import Path

import pytest

from agrireach import agent, db, farmer_reply, knowledge, rainfall, season

FIX = Path(__file__).parent / "fixtures" / "rainfall"
run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))
P = {p["id"]: p for p in knowledge.load()["passages"]}
TRANSITION = [P["MOFA-MAIZE:p11-transition-major"], P["MOFA-MAIZE:p12-transition-minor"]]
ADVICE = re.compile(r"(?i)\b(?:next|upcoming|plant (?:now|in|from)|you (?:can|should)|wait until)\b")


def test_every_cited_window_in_the_corpus_can_be_read():
    windows = [p for p in P.values() if season.is_window(p)]
    assert len(windows) >= 15
    for p in windows:
        assert season.window(p), p["id"]


def test_outside_every_window_is_flagged_as_a_plain_fact():
    f = season.fact(date(2026, 10, 25), TRANSITION)
    assert f.startswith("Question received 25 Oct 2026. Windows cited: ")
    assert "MoFA major season, transition: Mid-March-end of April" in f
    assert "MoFA minor season, transition: Mid July through August-early Sept." in f
    assert f.endswith("The date is outside the cited windows.")
    assert not ADVICE.search(f) and rainfall.draft_problems(f) == []


@pytest.mark.parametrize("d", [date(2026, 3, 11), date(2026, 4, 30), date(2026, 8, 20), date(2026, 9, 10)])
def test_inside_a_window_is_not_flagged(d):
    f = season.fact(d, TRANSITION)
    assert "outside" not in f and not ADVICE.search(f)


@pytest.mark.parametrize("d,outside", [(date(2026, 3, 10), True), (date(2026, 9, 11), True),
                                        (date(2026, 7, 10), False), (date(2026, 7, 11), True)])
def test_window_edges(d, outside):
    ps = [TRANSITION[0], P["APNI-SARI-2023-MAIZE:p5-planting-window"]]  # mid-March-end April; early June-July 10th
    assert ("outside the cited windows" in season.fact(d, ps)) is outside


def test_no_window_passages_no_fact():
    assert season.fact(date(2026, 10, 25), [P["APNI-SARI-2023-MAIZE:p13-topdress-moisture"]]) == ""


def _case_date(out):
    row = db.get_case(db.connect(), out["case_id"])
    return date.fromisoformat(row["created_at"][:10])


def test_planting_question_shows_received_date_from_the_case_not_the_sms():
    out = run("When should I plant maize in Ejura?")
    d = _case_date(out)
    assert f"Question received {d.day} {d:%b %Y}. Windows cited: " in out["draft"]
    sms = out["farmer_draft"]["text"]
    assert "Question received" not in sms and "outside the cited windows" not in sms and "Windows cited" not in sms


def test_top_dress_question_with_district_gets_rainfall_record(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    monkeypatch.setenv("AGRIREACH_RAINFALL_TODAY", "2026-10-25")
    out = run("When should I top dress my maize in Kumasi?")
    rid = "RAINFALL-OPEN-METEO:kumasi:2026-10-25"
    assert rid in out["sources"] and out["rainfall"]["available"]
    assert "APNI-SARI-2023-MAIZE:p13-topdress-moisture" in out["sources"]
    line = next(l for l in out["draft"].splitlines() if l.startswith(f"{agent.OFFICER_FACT} Rainfall record"))
    assert f"[{rid}]" in line and "rain days" in line and "officer decides" in line
    assert "Rainfall record" not in out["farmer_draft"]["text"]
    assert rainfall.draft_problems(out["draft"]) == []


@pytest.mark.parametrize("q", ["When should I top dress my maize in Northern Region?",
                               "When should I plant maize in Northern Region?"])
def test_region_only_asks_officer_to_get_the_district(monkeypatch, q):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    out = run(q)
    assert out["rainfall"]["available"] is False and not any(s.startswith("RAINFALL") for s in out["sources"])
    assert f"{agent.OFFICER_FACT} No rainfall record" in out["draft"]
    assert "'Northern' is not a district" in out["draft"] and "ask the farmer which district" in out["draft"]


def test_top_dress_question_without_a_place_says_why_no_rainfall(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    out = run("Subsidised fertiliser arrived when the maize is knee-high, about two months after planting. "
              "Is it still worth applying?")
    assert out["rainfall"]["available"] is False
    assert f"{agent.OFFICER_FACT} No rainfall record: the question names no district" in out["draft"]


@pytest.mark.parametrize("bad", ["The rains are good, plant now.", "Rains have been enough, so you can plant now.",
                                 "Now is a good time to plant your maize.", "Go ahead and sow this week."])
def test_go_ahead_wording_is_rejected(bad):
    assert rainfall.draft_problems(bad)


@pytest.mark.parametrize("ok", ["Sow after the rains have stabilized to avoid wilting.",
                                "AgriReach does not say whether the rains are good enough; the officer decides.",
                                "Planting time should be informed by local weather information."])
def test_guide_wording_is_not_rejected(ok):
    assert rainfall.draft_problems(ok) == []


def test_sms_that_reads_as_plant_now_is_withheld(monkeypatch):
    real = farmer_reply.propose
    def go(officer_text, *a, **k):
        fd = real(officer_text, *a, **k)
        fd.text, fd.mode = "The rains are good, plant now.", "llm:fake"
        return fd
    monkeypatch.setattr(farmer_reply, "propose", go)
    out = run("When should I plant maize in Ejura?")
    fd = out["farmer_draft"]
    assert fd["text"] == "" and fd["needs_officer_text"] and any("plant now" in p for p in fd["problems"])
    assert out["status"] == "pending_review"


def test_officer_facts_never_reach_a_rule_based_sms_even_from_the_full_officer_text():
    # The officer screen can re-propose the SMS from the whole officer text (api.py); facts start with "Note:".
    out = run("When should I plant maize in Ejura?")
    assert agent.OFFICER_FACT in out["draft"]
    sms = farmer_reply.rule_rewrite(out["draft"])
    assert sms and "Question received" not in sms and "Rainfall" not in sms and "officer only" not in sms
