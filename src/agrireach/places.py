"""Ghana place names: 16 regions, 261 districts and their capitals (data/gazetteer.json, parsed from Wikipedia's
"Districts of Ghana", CC BY-SA 4.0; see the file's _source).

Used to keep place names out of what the optional judge model is asked (whether the Northern Ghana guides apply to
a place is decided in code, not by the judge), and to recognise a farmer's location.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "data" / "gazetteer.json"
# Regions covered by the Northern Ghana corpus.
NORTHERN_REGIONS = {"Northern", "Savannah", "North East", "Upper East", "Upper West"}
# Names that are also ordinary English words or bare directions; only matched inside a longer name.
AMBIGUOUS = {"sang", "bole", "central", "western", "eastern", "northern", "north", "south", "east", "west",
             "upper", "lower", "tease", "la", "bongo", "banda", "guan", "tain", "prang", "agogo"}
_SUFFIX = re.compile(r"\s+(?:Municipal|Metropolitan|Metro|District)$", re.I)


def _clean(name: str) -> str:
    return _SUFFIX.sub("", name.replace(" Region", "").strip()).strip()


@lru_cache(maxsize=1)
def gazetteer() -> dict[str, dict]:
    """lower-case name -> {"name", "region", "kind"} for regions, districts and district capitals."""
    rows = json.loads(PATH.read_text(encoding="utf-8"))["districts"]
    out: dict[str, dict] = {}
    for r in rows:
        region = _clean(r["region"])
        for name, kind in ((region, "region"), (_clean(r["district"]), "district"), (_clean(r["capital"]), "capital")):
            if name and name.lower() not in out:
                out[name.lower()] = {"name": name, "region": region, "kind": kind}
    return out


@lru_cache(maxsize=1)
def _pattern() -> re.Pattern:
    names = sorted((n for n in gazetteer() if n not in AMBIGUOUS), key=lambda s: (-len(s), s))
    return re.compile(r"(?<![A-Za-z0-9])(" + "|".join(re.escape(n).replace(r"\ ", r"[\s-]+") for n in names) +
                      r")(?![A-Za-z0-9])", re.I)


def find(text: str) -> list[dict]:
    """Place names in the text, longest match first, each with its region: [{"name", "region", "kind", "span"}]."""
    out = []
    for m in _pattern().finditer(text or ""):
        key = re.sub(r"[\s-]+", " ", m.group(1).lower())
        g = gazetteer().get(key) or gazetteer().get(m.group(1).lower())
        if g:
            out.append(g | {"span": m.span(), "text": m.group(1)})
    return out


def is_northern(region: str) -> bool:
    return region in NORTHERN_REGIONS


def mask(text: str, keep: str = "", replacement: str = "the farmer's area") -> str:
    """Replace place names in `text` that don't appear in `keep` (e.g. the cited passages)."""
    keep_l = (keep or "").lower()
    out, last = [], 0
    for p in find(text):
        s, e = p["span"]
        if p["text"].lower() in keep_l:
            continue
        out += [text[last:s], replacement]
        last = e
    return "".join(out) + text[last:]
