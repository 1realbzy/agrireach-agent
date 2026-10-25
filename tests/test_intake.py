"""Intake routing for crops beyond soybean, contact requests and food-safety questions (offline stub mode)."""
import asyncio

import pytest

from agrireach import agent, language

run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))


@pytest.mark.parametrize("q,crop", [
    ("When should I plant soybean?", "soybean"), ("my soya is yellow", "soybean"), ("Can I still plant corn?", "maize"),
    ("Buyers offer GH¢60 a bucket of tomatoes.", "tomato"), ("cocoa pods turning black", "cocoa"),
    ("No rain for weeks. Should I apply fertiliser now?", ""),
    ("I grow maize and cowpea", "maize"),  # first crop named wins
])
def test_detect_crop(q, crop):
    assert language.detect_crop(q) == crop


def test_uncovered_crop_goes_to_officer_without_clarifying_or_searching():
    out = run("Heavy rain and my cocoa pods are turning black. What do I spray?")
    assert out["crop"] == "cocoa" and not out["clarification"]
    assert out["status"] == "pending_review" and out["priority"] == "urgent"
    assert any("crop 'cocoa' is not covered" in r for r in out["urgent_reasons"])
    assert out["sources"] == []  # another crop's guidance is never offered for cocoa


def test_contact_request_goes_to_officer_not_crop_question():
    out = run("No extension officer has visited for a long time. Who should I call?")
    assert not out["clarification"] and out["status"] == "pending_review" and out["priority"] == "urgent"
    assert any("how to reach an extension officer" in r for r in out["urgent_reasons"])
    assert out["sources"] == []


def test_no_crop_still_asks_which_crop_listing_corpus_crops():
    out = run("No rain for weeks after planting in Upper West. Should I apply fertiliser now?")
    assert out["status"] == "draft"
    assert out["clarification"] == "Which crop is this about? AgriReach currently covers maize and soybean only."


def test_after_planting_and_when_as_conjunction_do_not_trigger_region_question():
    out = run("Subsidised fertiliser arrived when the maize is knee-high, about two months after planting. "
              "Is it still worth applying?")
    assert not out["clarification"] and out["status"] == "pending_review"
    assert "APNI-SARI-2023-MAIZE:p13-topdress-timing" in out["sources"]


def test_maize_planting_question_without_region_still_asks_region():
    out = run("When should I plant maize?")
    assert out["clarification"].startswith("Which district or region")


def test_maize_planting_in_northern_region_retrieves_maize_window_only():
    out = run("Rains came late. Can I still plant maize in Northern Region at the end of July?")
    assert out["region"] == "northern" and out["status"] == "pending_review"
    assert "APNI-SARI-2023-MAIZE:p5-planting-window" in out["sources"]
    assert all(s.startswith("APNI-SARI-2023-MAIZE:") for s in out["sources"])


def test_mouldy_maize_is_urgent_food_safety_with_aflatoxin_limit():
    out = run("Some of my stored maize is mouldy. Can I sell it or feed it to animals?")
    assert out["priority"] == "urgent" and any("food safety" in r for r in out["urgent_reasons"])
    assert "AGBETIAMEH-2018:aflatoxin-limits" in out["sources"]
    assert "cannot clear produce" in out["draft"]


def test_adaklu_is_outside_the_northern_corpus():
    out = run("Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no "
              "effect. What next?")
    assert out["region"] == "adaklu"
    assert any("no local reference for region 'adaklu'" in r for r in out["urgent_reasons"])
    assert any("chemical" in r for r in out["urgent_reasons"])
    assert "APNI-SARI-2023-MAIZE:p20-faw-control" in out["sources"]


def test_source_page_check_uses_the_passage_crop():
    assert agent._crop_pattern("soybean") == r"soy(a)?bean"
    assert agent._crop_pattern("maize") == "maize"
