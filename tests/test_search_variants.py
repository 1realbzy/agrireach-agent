"""Wording-tolerant retrieval and verified Twi crop names (review re-test, 25 Oct 2026). Offline stub mode."""
import asyncio

import pytest

from agrireach import agent, knowledge, language

run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))
DRY_SOIL = "APNI-SARI-2023-MAIZE:p13-topdress-moisture"


@pytest.mark.parametrize("q", ["When should I top dress my maize?", "When do I top-dress maize?",
                               "When is top-dressing done for maize?", "topdress maize", "Top dressing maize when?",
                               "When should I topdress?"])
def test_top_dress_wordings_find_the_dry_soil_passage(q):
    assert DRY_SOIL in [h["id"] for h in knowledge.search(q, crop="maize")]


@pytest.mark.parametrize("q,pid", [
    ("When should I harvest my soybeans?", "APNI-SARI-2023:harvest"),      # plural crop word
    ("Is spraying herbicides safe for soybean?", "APNI-SARI-2023:weeds-herbicide"),  # -ing / plural
    ("my maize cobs are drying slowly", "APNI-SARI-2023-MAIZE:p22-drying"),
])
def test_plurals_and_simple_stems(q, pid):
    crop = language.detect_crop(q)
    assert pid in [h["id"] for h in knowledge.search(q, crop=crop)]


def test_agent_top_dress_question_with_place_gets_dry_soil_passage():
    out = run("When should I top dress my maize in Tamale?")
    assert DRY_SOIL in out["sources"] and out["crop"] == "maize"


@pytest.mark.parametrize("word,crop", [("aburo", "maize"), ("aburoo", "maize"), ("bankye", "cassava"),
                                       ("bayerɛ", "yam"), ("ɛmo", "rice"), ("borɔdeɛ", "plantain")])
def test_verified_twi_crop_names(word, crop):
    assert language.detect_crop(f"Mɛdua {word} bere bɛn?") == crop


def test_unverified_or_wrong_twi_crop_names_are_not_mapped():
    assert language.detect_crop("adua") != "cowpea"   # adua is pea, not cowpea
    assert language.detect_crop("nkateɛ") == ""        # groundnut name not verified: not added
    assert "plant" not in language.gloss("adua no ayɛ") .split()  # 'adua' (pea) is not the verb 'dua' (plant)


def test_aburo_retrieves_maize_passages():
    out = run("When do I plant aburo in Tamale?")
    assert out["crop"] == "maize" and "APNI-SARI-2023-MAIZE:p5-planting-window" in out["sources"]


def test_twi_ejura_aburo_question_gets_maize_and_transition_zone():
    out = run("Me te Ejura, mɛdua aburo bere bɛn?")
    assert out["language"] == "twi" and out["crop"] == "maize" and out["zone"] == "transition"
    assert "MOFA-MAIZE:p11-transition-major" in out["sources"]
    assert out["status"] == "pending_review" and out["priority"] == "urgent"  # Twi always goes to the officer
