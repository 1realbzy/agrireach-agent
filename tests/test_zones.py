"""Agroecological zones: every passage is tagged, every district is mapped, and planting windows follow the farmer's
zone (reviewer pass criteria a, b, d; 25 Oct 2026). Offline stub mode."""
import asyncio

import pytest

from agrireach import agent, knowledge, places, zones

ZONES = {"sudan_savannah", "guinea_savannah", "transition", "deciduous_forest", "rain_forest", "coastal_savannah"}
run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))


def test_every_passage_is_tagged_with_known_zones():
    for p in knowledge.load()["passages"]:
        assert p.get("zones") and set(p["zones"]) <= ZONES, p["id"]


def test_every_district_and_region_maps_to_a_zone():
    g = places.gazetteer()
    missing = [n for n in g if zones.zone_for(n) is None]
    assert missing == []


@pytest.mark.parametrize("place,zone", [
    ("Ejura", "transition"), ("Techiman", "transition"), ("Kumasi", "deciduous_forest"),
    ("Sefwi Wiawso", "deciduous_forest"), ("Brong Ahafo", "transition"), ("Nkwanta", "guinea_savannah"),
    ("Tamale", "guinea_savannah"), ("Bolgatanga", "sudan_savannah"), ("Accra", "coastal_savannah"),
    ("Wa", "guinea_savannah")])
def test_zone_for_reviewer_places(place, zone):
    assert zones.zone_for(place)["zone"] == zone


def test_new_maize_window_passages_carry_source_page_and_verbatim_cells():
    kb = knowledge.load()
    new = [p for p in kb["passages"] if p["source_id"] in ("MOFA-MAIZE", "IITA-MAIZE-2025")]
    assert len(new) >= 15
    for p in new:
        assert p["page"] and p["source_id"] in kb["sources"]
        if p.get("cells"):
            assert all(c in p["text"] or c.replace("-\n", "-") in p["text"] for c in p["cells"][1:]), p["id"]
    texts = {p["id"]: p["text"] for p in new}
    assert any("Mid July-early Sept." in t for t in texts.values())
    assert any("Mid of July - Early September" in t for t in texts.values())


def _windows(out):
    return [s for s in out["sources"] if "planting-window" in s or "window" in s]


@pytest.mark.parametrize("place,zone_word", [("Ejura", "Transition"), ("Techiman", "Transition"),
                                              ("Kumasi", "Forest"), ("Sefwi Wiawso", "Forest"),
                                              ("Brong Ahafo", "Transition")])
def test_criterion_a_southern_maize_question_gets_its_own_zone_window(place, zone_word):
    out = run(f"When should I plant maize in {place}?")
    assert out["status"] == "pending_review"
    assert any(s.startswith("MOFA-MAIZE:") for s in out["sources"]), out["sources"]
    assert "APNI-SARI-2023-MAIZE:p5-planting-window" not in out["sources"]  # northern window not offered
    assert f"| {zone_word} |" in out["draft"] or f"{zone_word} |" in out["draft"]
    assert out["zone_mismatch"] is False


def test_criterion_b_kumasi_minor_season_gets_mid_july_to_early_september():
    out = run("When should I plant maize in Kumasi for the minor season?")
    assert "Mid July-early Sept." in out["draft"] and "Mid of July - Early September" in out["draft"]
    assert "July 10th" not in out["draft"] and "early June" not in out["draft"]
    assert "Early March-end of April" not in out["draft"]  # major season left out when minor is asked


def test_criterion_d_nkwanta_is_northern():
    out = run("When should I plant maize in Nkwanta?")
    assert out["zone_mismatch"] is False
    assert "APNI-SARI-2023-MAIZE:p5-planting-window" in out["sources"]
    assert not any("no local reference" in r or "zone" in r and "differs" in r for r in out["urgent_reasons"])


def test_cross_zone_caution_and_urgent_flag_when_no_passage_matches_the_zone():
    out = run("When should I plant soybean in Kumasi?")  # soybean guides are Northern Ghana only
    assert out["zone_mismatch"] is True and out["priority"] == "urgent"
    assert any("deciduous forest" in r for r in out["urgent_reasons"])


def test_zone_planting_tool_over_mcp_returns_the_zone_windows_with_sources():
    from test_mcp import _session_calls
    import json
    _, res = asyncio.run(_session_calls([
        ("get_zone_planting_guidance", {"crop": "maize", "place": "Kumasi", "season": "minor"}),
        ("get_zone_planting_guidance", {"crop": "maize", "place": "Atlantis"}),
    ]))
    out = json.loads(res[0].content[0].text)
    assert out["zone"]["zone"] == "deciduous_forest"
    ids = [p["id"] for p in out["passages"]]
    assert "MOFA-MAIZE:p12-forest-minor" in ids and "IITA-MAIZE-2025:p16-forest-minor" in ids
    assert not any("major" in i for i in ids)
    assert all(p["source"]["url"].startswith("https://") and p["page"] for p in out["passages"])
    assert json.loads(res[1].content[0].text) == {"zone": None, "passages": []}  # unknown place: nothing invented


def test_detect_season():
    assert zones.detect_season("for the minor season") == "minor"
    assert zones.detect_season("second season maize") == "minor"
    assert zones.detect_season("major season") == "major"
    assert zones.detect_season("When should I plant maize?") == ""
