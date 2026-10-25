"""A district named in the question text is used for the rainfall record when the place field is missing or only a
region. Officer-only notes; zone tagging and the farmer SMS are unchanged."""
import asyncio
from pathlib import Path

import pytest

from agrireach import agent, rainfall

FIX = Path(__file__).parent / "fixtures" / "rainfall"
run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))
TAMALE_ID = "RAINFALL-OPEN-METEO:tamale:2026-10-25"
KNEE = "My maize is knee-high in Tamale. When should I top dress?"
NOTE_WORDS = ("taken from the question text", "officer only", "Rainfall record", "confirm", "district")


@pytest.fixture
def rain(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    monkeypatch.setenv("AGRIREACH_RAINFALL_TODAY", "2026-10-25")


# --- matching rule ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,found", [
    ("my maize is knee-high in Tamale", ["Tamale"]),
    ("MY MAIZE IN TAMALE IS YELLOW", ["Tamale"]),
    ("I farm near ejura", ["Ejura/Sekyedumase"]),
    ("we are at Sefwi Wiawso", ["Sefwi-Wiawso"]),
    ("farm in Central Gonja", ["Central Gonja"]),
    ("I am from Ho and my maize is wilting", ["Ho"]),
    ("I farm in wa", ["Wa"]),
    ("Ho, the maize is tall. What do I do?", []),       # short name not after in/at/from/near
    ("who has seen this? oh ho", []),
    ("What do I do with my waist-high maize?", []),
    ("I farm in Tamale but buy seed in Kumasi", ["Kumasi", "Tamale"]),
    ("Tamale Tamale Metropolitan", ["Tamale"]),          # one district, matched twice
    ("bole is a word here", []),                         # ambiguous name without in/at/from/near
    ("near Bole the rains stopped", ["Bole"]),
])
def test_districts_in_text(text, found):
    assert rainfall.districts_in_text(text) == found


# --- agent --------------------------------------------------------------------------------------------------

def _facts(out):
    return [l for l in out["draft"].splitlines() if l.startswith(agent.OFFICER_FACT)]


def _sms_clean(out):
    sms = out["farmer_draft"]["text"]
    assert all(w not in sms for w in ("taken from the question text", "officer only", "Rainfall record",
                                       "No rainfall record", "confirm with the farmer"))


def test_region_field_northern_with_tamale_in_text_gets_the_record(rain):
    out = run(KNEE, region="Northern")
    assert TAMALE_ID in out["sources"] and out["rainfall"]["available"] and out["rainfall"]["district"] == "Tamale"
    assert f"{agent.OFFICER_FACT} District Tamale taken from the question text." in _facts(out)
    assert not any("No rainfall record" in f for f in _facts(out))
    _sms_clean(out)


def test_no_region_field_sms_with_tamale_in_text_gets_the_record(rain):
    out = run(KNEE)
    assert TAMALE_ID in out["sources"] and out["rainfall"]["available"]
    assert f"{agent.OFFICER_FACT} District Tamale taken from the question text." in _facts(out)
    _sms_clean(out)


def test_district_field_given_is_not_called_from_the_text(rain):
    out = run("My maize is knee-high. When should I top dress?", region="Tamale")
    assert TAMALE_ID in out["sources"] and not any("question text" in f for f in _facts(out))


def test_two_districts_attach_nothing_and_list_both(rain):
    out = run("My maize is knee-high in Tamale, my brother farms in Kumasi. When should I top dress?",
              region="Northern")
    assert out["rainfall"]["available"] is False and not any(s.startswith("RAINFALL") for s in out["sources"])
    assert (f"{agent.OFFICER_FACT} No rainfall record: the question text names more than one district (Kumasi and "
            "Tamale); confirm with the farmer which district they farm in.") in _facts(out)
    _sms_clean(out)


def test_district_in_another_region_than_given_is_a_conflict(rain):
    out = run(KNEE, region="Ashanti")
    assert out["rainfall"]["available"] is False and not any(s.startswith("RAINFALL") for s in out["sources"])
    assert (f"{agent.OFFICER_FACT} No rainfall record: the question text names Tamale (Northern Region), but the "
            "region given is Ashanti; confirm the district with the farmer.") in _facts(out)
    _sms_clean(out)


def test_short_word_in_english_is_not_a_district(rain):
    out = run("Ho, my maize is knee-high. When should I top dress?", region="Volta")
    assert out["rainfall"]["available"] is False
    assert any("No rainfall record: rainfall is looked up per district" in f for f in _facts(out))


def test_no_district_anywhere_keeps_the_existing_note(rain):
    out = run("My maize is knee-high. When should I top dress?", region="Northern")
    assert (f"{agent.OFFICER_FACT} No rainfall record: rainfall is looked up per district and 'Northern' is not a "
            "district AgriReach knows; ask the farmer which district they farm in.") in _facts(out)


def test_detected_district_does_not_change_zone_tagging(rain):
    with_d = run(KNEE, region="Northern")
    without = run("My maize is knee-high. When should I top dress?", region="Northern")
    assert with_d["zone"] == without["zone"] == "guinea_savannah"
    assert with_d["zone_mismatch"] == without["zone_mismatch"]
    assert with_d["region"] == without["region"] == "Northern"
    assert set(without["sources"]) <= set(with_d["sources"]) and set(with_d["sources"]) - set(without["sources"]) == {
        TAMALE_ID}


def test_short_word_picked_up_by_intake_is_not_used_for_rainfall(rain):
    # No place field: intake's own place detection may read "Ho," as the place; rainfall uses the stricter rule.
    out = run("Ho, my maize is knee-high. When should I top dress?")
    assert out["rainfall"]["available"] is False and not any(s.startswith("RAINFALL") for s in out["sources"])
    assert (f"{agent.OFFICER_FACT} No rainfall record: the question names no district; ask the farmer which district "
            "they farm in.") in _facts(out)
