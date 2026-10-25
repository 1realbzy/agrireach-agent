"""Agroecological zones of Ghana: which zone a place is in, and which knowledge-base passages apply there.

Place -> zone comes from data/zones.json (AgriReach curation, approximate; see its _source): a default zone per
region, overrides for districts known to lie in another zone, and 'boundary' flags for districts that straddle two
zones. Passage -> zones comes from each passage's 'zones' tag in data/knowledge.json.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from agrireach import knowledge, places

PATH = Path(__file__).resolve().parents[2] / "data" / "zones.json"
ALL_ZONES = ("sudan_savannah", "guinea_savannah", "transition", "deciduous_forest", "rain_forest", "coastal_savannah")
NORTHERN_ZONES = {"sudan_savannah", "guinea_savannah"}
WINDOW_KEYS = {f"{c}_{k}" for c in ("maize", "soybean") for k in
               ("planting_window", "planting_window_major_season", "planting_window_minor_season", "planting_rule",
                "onset_rule")} | {"planting_window"}
MINOR = re.compile(r"\bminor\b|\bsecond\s+(?:cropping\s+)?season\b|\bsecond\s+rains?\b", re.I)
MAJOR = re.compile(r"\bmajor\b|\bmain\s+season\b|\bfirst\s+(?:cropping\s+)?season\b|\bfirst\s+rains?\b", re.I)


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def label(zone: str) -> str:
    """Readable name, e.g. 'deciduous forest'."""
    return _data()["zones"].get(zone, zone.replace("_", " "))


@lru_cache(maxsize=1)
def _district_of() -> dict[str, tuple[str, str]]:
    """lower-case district or capital name -> (district, region), from the gazetteer."""
    rows = json.loads(places.PATH.read_text(encoding="utf-8"))["districts"]
    out: dict[str, tuple[str, str]] = {}
    for r in rows:
        district, region = places._clean(r["district"]), places._clean(r["region"])
        for name in (district, places._clean(r["capital"])):
            out.setdefault(name.lower(), (district, region))
    return out


def zone_for(place: str) -> dict | None:
    """{"zone", "zones", "region", "district", "boundary"} for a region, district, capital or alias; None if unknown.
    'zones' is the set a passage must overlap to apply ('Northern Ghana' in general covers both savannah zones)."""
    key = re.sub(r"[\s-]+", " ", (place or "").strip().lower()).replace(" region", "")
    d = _data()
    if key in d["alias"]:
        a = d["alias"][key]
        return {"zone": a["zone"], "zones": a.get("zones", [a["zone"]]), "region": a["region"], "district": "",
                "boundary": False}  # only a district can be on a zone edge, never a region name
    regions = {r.lower(): r for r in d["region_default"]}
    if key in regions:
        region = regions[key]
        zone = d["region_default"][region]
        return {"zone": zone, "zones": [zone], "region": region, "district": "", "boundary": False}
    hit = _district_of().get(key) or _district_of().get(place.strip().lower())
    if not hit:
        return None
    district, region = hit
    zone = d["district_override"].get(district) or d["region_default"].get(region)
    if not zone:
        return None
    return {"zone": zone, "zones": [zone], "region": region, "district": district,
            "boundary": district in d["boundary"]}


def covers(passage: dict, zones: list[str] | set[str]) -> bool:
    """True if the passage applies in any of the given zones (untagged passages are treated as Northern Ghana)."""
    return bool(set(passage.get("zones") or NORTHERN_ZONES) & set(zones))


def zone_specific(passage: dict) -> bool:
    return set(passage.get("zones") or NORTHERN_ZONES) != set(ALL_ZONES)


def detect_season(question: str) -> str:
    """'minor', 'major' or '' from the farmer's wording."""
    if MINOR.search(question or ""):
        return "minor"
    if MAJOR.search(question or ""):
        return "major"
    return ""


def planting_passages(crop: str, place: str, season: str = "") -> dict:
    """Planting-time passages for the crop that apply in the place's zone: the zone's window rows (only the asked
    season, if one is given) plus national planting rules. Empty if the place or the crop's windows are unknown."""
    z = zone_for(place)
    if not z:
        return {"zone": None, "passages": []}
    kb = knowledge.load()
    out = []
    for p in kb["passages"]:
        if p.get("crop") != crop or not any(k in WINDOW_KEYS for k in knowledge.claim_keys(p)):
            continue
        if not covers(p, z["zones"]) or (season and p.get("season") and p["season"] != season):
            continue
        out.append(p | {"source": kb["sources"][p["source_id"]]})
    return {"zone": z, "passages": out}
