"""Rainfall record for the officer: daily rainfall estimates for the farmer's district over the last 30 days.

Read-only, cached, cites its provider and licence. It is an INPUT for the extension officer, not guidance: the cited
guides say to plant "after three good rains" (IITA) or "after the rains have stabilized" (MoFA) but give no rainfall
amount for that, so AgriReach never says whether onset has been reached. See docs/rainfall-plan.md.

Default provider: Open-Meteo (model-based daily precipitation for past days; data CC BY 4.0; free API for
non-commercial use). Optional cross-check: NASA POWER (AGRIREACH_RAINFALL_CROSSCHECK=nasa_power), only days at least
7 days old. Values that are negative (NASA POWER's -999 fill value) or null are missing: never shown, counted.

AGRIREACH_RAINFALL: "open-meteo" (default) | "off" | "fixture:<dir>" (recorded responses, for tests and demos).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import urllib.request
from functools import lru_cache
from pathlib import Path

from agrireach import places

COORDS = Path(__file__).resolve().parents[2] / "data" / "district_coords.json"
DAYS = 30
THRESHOLD_MM = 1.0   # display convention for a "rain day" (a common wet-day threshold); NOT an onset rule
CROSSCHECK_MIN_AGE_DAYS = 7
CAVEAT = ("Model and satellite rainfall estimates for one point per district can differ a lot from a local rain gauge "
          "and from each other (for Kumasi on 11 Oct 2026, Open-Meteo gave 5.6 mm and NASA POWER 71.28 mm). The guides "
          "give no rainfall amount that marks onset; AgriReach does not say whether onset has been reached. The officer "
          "decides.")
OPEN_METEO = {"provider": "Open-Meteo (model-based estimate, forecast API past days)",
              "provider_url": "https://open-meteo.com/", "licence": "CC BY 4.0",
              "licence_url": "https://open-meteo.com/en/license", "attribution": "Weather data by Open-Meteo.com",
              "terms": "free API for non-commercial use only"}
NASA_POWER = {"provider": "NASA POWER (daily PRECTOTCORR, MERRA-2 based)", "provider_url": "https://power.larc.nasa.gov/",
              "licence": "No restrictions on use; NASA asks to be cited (CC BY 4.0 per the AWS Open Data registry)",
              "attribution": "Data obtained from the NASA Langley Research Center POWER Project"}
ONSET_CLAIM = re.compile(r"\bonset\b[^.;,]{0,40}?\b(?:has|have|is|was)\s+(?:now\s+)?(?:been\s+)?"
                         r"(?:reached|started|begun|arrived|come|set\s+in|established)\b"
                         r"|\bthe\s+rains\s+(?:have|has)\s+(?:now\s+)?(?:stabili[sz]ed|started|set\s+in|established)\b"
                         r"|\bonset\s+(?:reached|confirmed)\b", re.I)
# Quoting the guide's condition or denying the claim is fine: "sow after the rains have stabilized", "does not say
# whether onset has been reached".
_NOT_A_CLAIM = re.compile(r"\b(?:after|once|when|until|whether|if|not|no|never|before)\b[^.]{0,25}$", re.I)


class Unavailable(Exception):
    pass


@lru_cache(maxsize=1)
def _coords_doc() -> dict:
    return json.loads(COORDS.read_text(encoding="utf-8"))


def coords() -> dict[str, dict]:
    return _coords_doc()["districts"]


@lru_cache(maxsize=1)
def _district_index() -> dict[str, str]:
    """lower-case district or capital -> district name (as in data/district_coords.json)."""
    out = {}
    for d, c in coords().items():
        for n in (d, c["capital"]):
            out.setdefault(re.sub(r"[\s-]+", " ", n.lower()), d)
    return out


def locate(place: str) -> dict | None:
    """{"district", "region", "lat", "lon", "point", ...} for a district or district capital; None otherwise
    (region names on purpose: one point cannot stand for a whole region)."""
    key = re.sub(r"[\s-]+", " ", (place or "").strip().lower())
    d = _district_index().get(key)
    if not d:
        g = places.gazetteer().get(key)
        if g and g["kind"] != "region":
            d = _district_index().get(re.sub(r"[\s-]+", " ", g["name"].lower()))
    return {"district": d, **coords()[d]} if d else None


def _today() -> dt.date:
    t = os.getenv("AGRIREACH_RAINFALL_TODAY")
    return dt.date.fromisoformat(t) if t else dt.datetime.now(dt.timezone.utc).date()


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _http(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "AgriReach/0.1 (extension-officer decision support)"})
    with urllib.request.urlopen(req, timeout=float(os.getenv("AGRIREACH_RAINFALL_TIMEOUT", "15"))) as r:
        return json.loads(r.read().decode())


def _default_fetch(district: str):
    mode = os.getenv("AGRIREACH_RAINFALL", "open-meteo")
    if mode in ("off", "0", "none"):
        def off(url):
            raise Unavailable("rainfall lookups are switched off (offline mode)")
        return off
    if mode.startswith("fixture:"):
        folder = Path(mode.split(":", 1)[1])

        def fixture(url):
            name = ("nasa_power_" if "power.larc" in url else "open_meteo_") + _slug(district.split("/")[0]) + ".json"
            if not (folder / name).exists():
                raise Unavailable(f"no recorded response {name}")
            return json.loads((folder / name).read_text())
        return fixture
    return _http


def _cache_path(key: str) -> Path:
    base = Path(os.getenv("AGRIREACH_RAINFALL_CACHE", Path.home() / ".cache" / "agrireach" / "rainfall"))
    return base / (hashlib.sha256(key.encode()).hexdigest()[:24] + ".json")


def _clean(pairs) -> tuple[list[dict], list[str]]:
    """Daily values -> (shown days, missing dates). Negative (e.g. -999 fill) or null values are missing."""
    daily, missing = [], []
    for date, mm in pairs:
        if mm is None or not isinstance(mm, (int, float)) or mm < 0:
            missing.append(date)
        else:
            daily.append({"date": date, "mm": round(float(mm), 1)})
    return daily, missing


def _open_meteo(loc: dict, start: dt.date, end: dt.date, fetch) -> tuple[list[dict], list[str], str]:
    past = (_today() - start).days + 1
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={loc['lat']}&longitude={loc['lon']}"
           f"&daily=precipitation_sum&past_days={past}&forecast_days=1&timezone=GMT")
    raw = fetch(url)["daily"]
    pairs = {t: v for t, v in zip(raw["time"], raw["precipitation_sum"])}
    want = [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    daily, missing = _clean((d, pairs.get(d)) for d in want)
    return daily, missing, url


def _nasa_power(loc: dict, start: dt.date, end: dt.date, fetch) -> dict:
    last = min(end, _today() - dt.timedelta(days=CROSSCHECK_MIN_AGE_DAYS))
    url = (f"https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR&community=AG"
           f"&longitude={loc['lon']}&latitude={loc['lat']}&start={start:%Y%m%d}&end={last:%Y%m%d}&format=JSON")
    vals = fetch(url)["properties"]["parameter"]["PRECTOTCORR"]
    want = [(start + dt.timedelta(days=i)) for i in range((last - start).days + 1)]
    daily, missing = _clean((d.isoformat(), vals.get(f"{d:%Y%m%d}")) for d in want)
    return {**NASA_POWER, "url": url, "period": {"start": start.isoformat(), "end": last.isoformat()},
            "daily": daily, "missing_days": len(missing), "missing_dates": missing,
            "total_mm": round(sum(d["mm"] for d in daily), 1),
            "note": f"Only days at least {CROSSCHECK_MIN_AGE_DAYS} days old are used."}


def recent(place: str, days: int = DAYS, threshold_mm: float = THRESHOLD_MM, fetch=None,
           max_age_hours: float = 6) -> dict:
    """Last `days` complete days (UTC) of daily rainfall for the place's district. Never raises."""
    loc = locate(place)
    if not loc:
        return {"available": False, "place": place,
                "reason": f"rainfall unavailable: '{place}' is not a district or district capital AgriReach has "
                          "coordinates for (rainfall is looked up per district, not per region)"}
    end = _today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    fetch = fetch or _default_fetch(loc["district"])
    key = f"open-meteo|{loc['lat']}|{loc['lon']}|{start}|{end}"
    path = _cache_path(key)
    cached = json.loads(path.read_text()) if path.exists() else None
    now = dt.datetime.now(dt.timezone.utc)
    if cached:
        age = (now - dt.datetime.fromisoformat(cached["retrieved_at"])).total_seconds() / 3600
        if age <= max_age_hours:
            return {**cached, "cache": {"hit": True, "stale": False, "age_hours": round(age, 2)}}
    try:
        daily, missing, url = _open_meteo(loc, start, end, fetch)
    except Exception as e:
        if cached:
            return {**cached, "cache": {"hit": True, "stale": True, "age_hours": round(age, 2),
                                        "refresh_error": str(e)[:160]}}
        return {"available": False, "place": place, "district": loc["district"],
                "reason": f"rainfall unavailable: {str(e)[:160]}"}
    rain_days = sum(1 for d in daily if d["mm"] >= threshold_mm)
    total = round(sum(d["mm"] for d in daily), 1)
    stamp = now.replace(microsecond=0).isoformat()
    rid = f"RAINFALL-OPEN-METEO:{_slug(loc['district'].split('/')[0])}:{_today().isoformat()}"
    text = (f"Rainfall record ({OPEN_METEO['provider']}; {OPEN_METEO['licence']}) for {loc['district']} district "
            f"(point: {loc['point']}, {loc['lat']}, {loc['lon']}), {start.isoformat()} to {end.isoformat()}: "
            f"{rain_days} of {len(daily)} days with at least {threshold_mm:g} mm; total {total} mm"
            + (f"; {len(missing)} days missing" if missing else "")
            + f". Retrieved {stamp}. {CAVEAT}")
    out = {"available": True, "place": place, "district": loc["district"], "region": loc["region"],
           "lat": loc["lat"], "lon": loc["lon"], "point": loc["point"], "coords_source": loc["source"],
           **OPEN_METEO, "url": url, "retrieved_at": stamp,
           "period": {"start": start.isoformat(), "end": end.isoformat()}, "daily": daily,
           "missing_days": len(missing), "missing_dates": missing, "threshold_mm": threshold_mm,
           "rain_days": rain_days, "total_mm": total, "caveat": CAVEAT, "record_id": rid, "record_text": text}
    if os.getenv("AGRIREACH_RAINFALL_CROSSCHECK") == "nasa_power":
        try:
            out["cross_check"] = _nasa_power(loc, start, end, fetch)
        except Exception as e:
            out["cross_check"] = {**NASA_POWER, "available": False, "reason": str(e)[:160]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return {**out, "cache": {"hit": False, "stale": False, "age_hours": 0}}


def as_passage(r: dict, zone: str | None) -> dict:
    """The record as a citable passage (kind 'record'), so a draft can cite it like a guide passage."""
    return {"id": r["record_id"], "kind": "record", "source_id": "RAINFALL-OPEN-METEO", "crop": "", "topic": "rainfall",
            "claim_key": "rainfall_record", "page": f"retrieved {r['retrieved_at']}", "text": r["record_text"],
            "zones": [zone] if zone else [], "region": r["region"],
            "source": {"title": OPEN_METEO["provider"], "url": r["url"], "landing_url": OPEN_METEO["provider_url"],
                       "licence": OPEN_METEO["licence"], "attribution": OPEN_METEO["attribution"]}}


def draft_problems(text: str) -> list[str]:
    """A draft must not say onset has been reached: the guides give no rainfall amount for it."""
    text = text or ""
    m = next((m for m in ONSET_CLAIM.finditer(text) if not _NOT_A_CLAIM.search(text[max(0, m.start() - 40):m.start()])),
             None)
    return [f"draft says '{m.group(0)}': the guides give no rainfall amount for onset, so AgriReach must not say "
            "whether onset has been reached; show the rainfall record and let the officer decide"] if m else []
