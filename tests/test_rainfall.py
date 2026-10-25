"""Rainfall signal: recorded Open-Meteo / NASA POWER responses (tests/fixtures/rainfall, fetched 25 Oct 2026), never the
network. The record informs the officer; it never says onset has been reached."""
import asyncio
import json
from pathlib import Path

import pytest

from agrireach import agent, farmer_reply, rainfall

FIX = Path(__file__).parent / "fixtures" / "rainfall"
TODAY = "2026-10-25"
run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))


def fixture_fetch(name, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return json.loads((FIX / name).read_text())
    return fetch


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL_TODAY", TODAY)


def test_every_district_has_coordinates_with_a_source():
    coords = rainfall.coords()
    assert len(coords) == 261
    for d, c in coords.items():
        assert 4.5 <= c["lat"] <= 11.2 and -3.3 <= c["lon"] <= 1.3, d
        assert c["source"] in ("GeoNames", "OpenStreetMap Nominatim"), d


@pytest.mark.parametrize("place,district", [("Tamale", "Tamale"), ("Ejura", "Ejura/Sekyedumase"),
                                            ("Kumasi", "Kumasi"), ("Sefwi Wiawso", "Sefwi-Wiawso")])
def test_place_resolves_to_its_district(place, district):
    assert rainfall.locate(place)["district"] == district


def test_region_name_is_not_a_district(today):
    r = rainfall.recent("Ashanti", fetch=fixture_fetch("open_meteo_kumasi.json"))
    assert r["available"] is False and "district" in r["reason"]


def test_summary_from_recorded_open_meteo_response(today):
    r = rainfall.recent("Kumasi", fetch=fixture_fetch("open_meteo_kumasi.json"))
    raw = json.loads((FIX / "open_meteo_kumasi.json").read_text())["daily"]
    days = dict(zip(raw["time"], raw["precipitation_sum"]))
    assert r["available"] and r["period"] == {"start": "2026-09-25", "end": "2026-10-24"}
    assert [d["date"] for d in r["daily"]][0] == "2026-09-25" and len(r["daily"]) == 30  # today (partial) left out
    assert r["rain_days"] == sum(1 for d in r["daily"] if d["mm"] >= 1.0) and r["threshold_mm"] == 1.0
    assert r["daily"][-1]["mm"] == days["2026-10-24"] and r["missing_days"] == 0
    assert r["provider"].startswith("Open-Meteo") and r["licence"] == "CC BY 4.0" and r["retrieved_at"]
    assert "rain gauge" in r["caveat"] and rainfall.draft_problems(r["record_text"]) == []
    assert r["record_id"] == "RAINFALL-OPEN-METEO:kumasi:2026-10-25"
    assert "cross_check" not in r  # NASA POWER is not in the default path


def test_negative_or_missing_values_are_missing_never_shown(today):
    raw = json.loads((FIX / "open_meteo_kumasi.json").read_text())
    vals = raw["daily"]["precipitation_sum"]
    i = raw["daily"]["time"].index("2026-10-20")
    vals[i], vals[i + 1], vals[i + 2] = -999.0, None, -0.5
    r = rainfall.recent("Kumasi", fetch=lambda url: raw)
    assert r["missing_days"] == 3 and len(r["daily"]) == 27
    assert set(r["missing_dates"]) == {"2026-10-20", "2026-10-21", "2026-10-22"}
    assert all(d["mm"] >= 0 for d in r["daily"]) and "-999" not in r["record_text"]
    assert "3 days missing" in r["record_text"]


def test_offline_means_unavailable_and_no_claim(today):
    r = rainfall.recent("Kumasi")  # conftest: AGRIREACH_RAINFALL=off, empty cache
    assert r["available"] is False and r["reason"].startswith("rainfall unavailable")
    assert "daily" not in r and "rain_days" not in r


def test_cached_then_stale_when_offline(today):
    calls = []
    a = rainfall.recent("Ejura", fetch=fixture_fetch("open_meteo_ejura.json", calls))
    b = rainfall.recent("Ejura", fetch=fixture_fetch("open_meteo_ejura.json", calls))
    assert len(calls) == 1 and a["daily"] == b["daily"] and b["cache"]["hit"]

    def down(url):
        raise OSError("no network")
    c = rainfall.recent("Ejura", fetch=down, max_age_hours=0)
    assert c["available"] and c["cache"]["stale"] and c["daily"] == a["daily"]


def test_nasa_power_cross_check_only_finalised_days_and_no_fill_values(today, monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL_CROSSCHECK", "nasa_power")

    def fetch(url):
        return json.loads((FIX / ("nasa_power_kumasi.json" if "power.larc" in url else "open_meteo_kumasi.json")).read_text())
    r = rainfall.recent("Kumasi", fetch=fetch)
    cc = r["cross_check"]
    assert cc["provider"].startswith("NASA POWER") and cc["licence"]
    assert all(d["date"] <= "2026-10-18" for d in cc["daily"])  # only days at least 7 days old
    assert all(d["mm"] >= 0 for d in cc["daily"])
    assert "-999" not in json.dumps(cc)


def test_draft_must_not_claim_onset():
    assert rainfall.draft_problems("The rains have stabilized, so onset has been reached. Plant now.")
    assert rainfall.draft_problems("Onset of the rains has started in Kumasi.")
    assert not rainfall.draft_problems("The guides say to sow after the rains have stabilized; the officer decides.")


def test_planting_question_gets_cited_rainfall_record(today, monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    out = run("When should I plant maize in Kumasi?")
    rid = "RAINFALL-OPEN-METEO:kumasi:2026-10-25"
    assert rid in out["sources"] and f"[{rid}]" in out["draft"]
    assert "Rainfall record" in out["draft"] and "Sow after the rains have stabilized" in out["draft"]
    assert out["rainfall"]["available"] and out["rainfall"]["rain_days"] >= 0
    assert rainfall.draft_problems(out["draft"]) == []  # mentions onset only to say it is not decided
    assert "Rainfall record" not in out["farmer_draft"]["text"]  # officer input, not farmer advice
    assert out["status"] == "pending_review"


def test_offline_planting_question_says_rainfall_unavailable():
    out = run("When should I plant maize in Kumasi?")
    assert not any(s.startswith("RAINFALL") for s in out["sources"])
    assert "rainfall unavailable" in out["draft"].lower() and out["rainfall"]["available"] is False


def test_non_planting_question_does_not_fetch_rainfall(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    out = run("When should I harvest my soybean? I farm near Tamale.")
    assert out.get("rainfall") is None and not any(s.startswith("RAINFALL") for s in out["sources"])


def test_model_draft_claiming_onset_is_regenerated(today, monkeypatch):
    from test_eval_failures import fake_llm
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    bad = "Onset has been reached in Kumasi, so plant now."
    calls = fake_llm(monkeypatch, [bad, bad])
    out = run("When should I plant maize in Kumasi?")
    assert len(calls) == 2 and "onset" in " ".join(calls[1]["feedback"]).lower()
    assert bad not in out["draft"]
