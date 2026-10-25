"""Place names after speech-to-text: spot a likely mis-heard Ghana place and ask the farmer, never guess silently.

Whisper turns short or unfamiliar place names into English words ("Wa" -> "war", "Tamale" -> "tamali"). After a
voice note is transcribed, suggest() looks for a word in a location slot ("I farm near X", "in X district") that is
not a known place but sounds like one (a small table of confusions seen or expected, else a close spelling match
against the gazetteer). It only proposes; the farmer is asked "Did you mean Wa (Upper West)?" and the transcript is
changed only if they say yes or name a place.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from agrireach import places

# Heard -> gazetteer name. Keys are words Whisper produced, or plausibly produces, for these names.
CONFUSIONS = {"war": "wa", "wah": "wa", "walk": "wa", "tamali": "tamale", "tamaley": "tamale", "tamari": "tamale",
              "temale": "tamale", "yendee": "yendi", "yandi": "yendi", "bolga": "bolgatanga", "kumasie": "kumasi",
              "damongoh": "damongo", "savanna": "savannah"}
LOCATION_BEFORE = r"(?:in|at|near|from|around|close to|outside)"
LOCATION_AFTER = r"(?:district|region|municipal|area|town)"
# Words that commonly follow "in/at/near" in farming questions and must never be "corrected" into a place.
NOT_PLACES = {"the", "my", "our", "a", "an", "this", "that", "time", "season", "rain", "rains", "rainy", "dry",
              "farm", "field", "village", "town", "house", "home", "morning", "evening", "night", "week", "month",
              "year", "january", "february", "march", "april", "may", "june", "july", "august", "september",
              "october", "november", "december", "rows", "row", "bags", "bag", "storage", "store", "market", "soil",
              "water", "sun", "shade", "general", "between", "case", "order", "front", "pods", "plants", "all",
              "it", "them", "there", "here", "one", "two", "kg", "acre", "acres", "hectare", "hectares"}
YES = {"yes", "y", "yeah", "yep", "correct", "right", "aane", "aanee", "ane", "ok", "okay"}


@dataclass
class Suggestion:
    heard: str          # the word in the transcript
    place: dict         # gazetteer entry {"name", "region", "kind"}
    span: tuple[int, int]

    def question(self) -> str:
        p = self.place
        where = p["name"] if p["kind"] == "region" else f"{p['name']} ({p['region']} Region)"
        return (f'I heard "{self.heard}". Did you mean {where}? Reply YES, or tell me your district or town.')

    def apply(self, text: str) -> str:
        s, e = self.span
        return text[:s] + self.place["name"] + text[e:]


def _candidates(text: str):
    for m in re.finditer(rf"\b{LOCATION_BEFORE}\s+([A-Za-z'-]+)", text, re.I):
        yield m.group(1), m.span(1)
    for m in re.finditer(rf"\b([A-Za-z'-]+)\s+{LOCATION_AFTER}\b", text, re.I):
        yield m.group(1), m.span(1)


def _match(word: str) -> dict | None:
    w = word.lower().strip("'-")
    g = places.gazetteer()
    if w in NOT_PLACES or w in g:
        return None
    if w in CONFUSIONS:
        return g[CONFUSIONS[w]]
    if len(w) < 5:  # short words have too many close spellings to guess from
        return None
    names = [n for n in g if n not in places.AMBIGUOUS and " " not in n and len(n) >= 4]
    best = difflib.get_close_matches(w, names, n=1, cutoff=0.8)
    return g[best[0]] if best else None


def suggest(text: str) -> Suggestion | None:
    """A likely mis-heard place in a location slot, or None if a known place is already named (or nothing fits)."""
    if not text or places.find(text):
        return None
    for word, span in _candidates(text):
        p = _match(word)
        if p:
            return Suggestion(word, p, span)
    return None


def parse_reply(reply: str) -> tuple[str, dict | None]:
    """('yes', None) | ('place', entry) | ('other', None) for the farmer's answer to Suggestion.question()."""
    r = (reply or "").strip()
    words = re.findall(r"[^\W\d_]+", r.lower())
    found = places.find(r)
    if found:
        return "place", {k: found[0][k] for k in ("name", "region", "kind")}
    if words and words[0] in YES and len(words) <= 4:
        return "yes", None
    return "other", None
