"""Read-only access to the curated corpus in data/knowledge.json."""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT = Path(__file__).resolve().parents[2] / "data" / "knowledge.json"

# Small curated synonym map so farmer wording reaches corpus topics.
SYNONYMS = {
    "plant": "planting", "sow": "planting", "sowing": "planting",
    "spacing": "spacing", "space": "spacing", "distance": "spacing", "apart": "spacing",
    "seed": "seed", "seeds": "seed", "kg": "seed", "rate": "seed",
    "weed": "weeding", "weeds": "weeding", "weeding": "weeding",
    "herbicide": "herbicide", "spray": "herbicide", "glyphosate": "herbicide", "paraquat": "herbicide",
    "harvest": "harvest", "harvesting": "harvest", "pods": "harvest",
    "rotate": "rotation", "rotation": "rotation",
    "plough": "land preparation", "prepare": "land preparation", "preparation": "land preparation",
    "deep": "planting", "depth": "planting",
    "fertiliser": "fertilizer", "fertilizer": "fertilizer", "topdress": "fertilizer", "basal": "fertilizer",
    "npk": "fertilizer", "urea": "fertilizer",
    "armyworm": "pest", "armyworms": "pest", "worms": "pest", "worm": "pest", "pest": "pest", "pests": "pest",
    "insects": "pest", "larvae": "pest", "scout": "pest", "scouting": "pest", "whorl": "pest", "funnel": "pest",
    "store": "storage", "storage": "storage", "stored": "storage", "storing": "storage", "weevils": "storage",
    "weevil": "storage", "sacks": "storage", "sack": "storage", "bags": "storage", "drying": "storage",
    "mould": "aflatoxin", "mouldy": "aflatoxin", "mold": "aflatoxin", "moldy": "aflatoxin", "aflatoxin": "aflatoxin",
}
STOP = set("a an the is are of to in on for my i we do how what should can and or with at be it".split())


@lru_cache
def load(path: str | None = None) -> dict:
    return json.loads(Path(path or os.getenv("AGRIREACH_KNOWLEDGE", DEFAULT)).read_text())


def tokens(s: str) -> list[str]:
    # "top dress", "top-dress", "top dressing" and "topdress" are one term in the corpus and in farmer wording.
    s = re.sub(r"\btop[\s-]*dress(?:ing|ed|es)?\b", "topdress", s.lower())
    return [t for t in re.findall(r"[a-z]+", s) if t not in STOP]


def _in_scope(p: dict, crop: str | None, region: str | None) -> bool:
    """Crop/region filter shared by ranked hits and conflict-completion hits."""
    return (not crop or p["crop"] == crop.lower()) and (not region or p["region"] in region.lower())


def search(query: str, crop: str | None = None, region: str | None = None, limit: int = 4) -> list[dict]:
    kb = load()
    q = tokens(query)
    topics = {SYNONYMS[t] for t in q if t in SYNONYMS}
    out = []
    for p in kb["passages"]:
        if not _in_scope(p, crop, region):
            continue
        words = set(tokens(p["text"]))
        score = 3 * (p["topic"] in topics) + sum(t in words for t in q if len(t) > 3)
        if score >= 3:
            out.append({**p, "score": score, "source": kb["sources"][p["source_id"]]})
    out.sort(key=lambda r: -r["score"])
    out = out[:limit]
    # Conflict completeness: if a hit states a claim, also return every other source's passage on the same claim,
    # so a disagreement is never hidden just because the other source scored lower or fell past `limit`.
    keys = {k for r in out for k in claim_keys(r)}
    have = {r["id"] for r in out}
    for p in kb["passages"]:
        if p["id"] in have or not _in_scope(p, crop, region):
            continue
        if keys & set(claim_keys(p)):
            out.append({**p, "score": 0, "source": kb["sources"][p["source_id"]], "added_for_conflict_check": True})
            have.add(p["id"])
    return out


def claim_keys(p: dict) -> list[str]:
    """The claim a passage makes, plus any secondary claims it also states (e.g. a depth passage giving hole spacing)."""
    return [p["claim_key"], *p.get("also_claims", [])]


def crops_covered() -> list[str]:
    """Crops with at least one curated passage, sorted."""
    return sorted({p["crop"] for p in load()["passages"]})


def reference(passage_id: str) -> dict | None:
    kb = load()
    for p in kb["passages"]:
        if p["id"] == passage_id:
            return {**p, "source": kb["sources"][p["source_id"]]}
    return None


def calendar(crop: str, region: str | None = None) -> list[dict]:
    kb = load()
    rows = [c for c in kb["crop_calendar"] if c["crop"] == crop.lower()
            and (not region or c["region"] in region.lower())]
    return [{**c, "passage": reference(c["passage_id"])} for c in rows]
