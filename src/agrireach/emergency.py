"""Crop-independent emergency check, run before any clarifying question or model call.

Deterministic word rules only. A match routes the question to an extension officer as an urgent case with a
visible "EMERGENCY:" reason, and the farmer gets a fixed referral message (call 112, a health facility or a
veterinary officer). Nothing here drafts or releases advice.

Rules (any one is enough; negation and words such as "not urgent" never remove a match, and words such as
"urgent", "emergency" or "mark as critical" never create one):
  A  poisoning words: poisoned, poisoning (and misspellings such as "poisining")
  B  symptoms: vomiting, unconscious, convulsions, seizures, foaming, breathing difficulty, dizziness;
     fainted/collapsed only when a person or animal is named nearby (maize can "collapse")
  C  swallowing, drinking, inhaling or splashing near a chemical or pesticide name (Gramoxone, paraquat ...)
  D  animal, livestock, bird, bee or fish deaths
  E  a person's death
Text is lower-cased, accents removed, look-alike characters inside words mapped (pestic1de -> pesticide,
g0ats -> goats), long letter runs collapsed (vomiiiting), and words of 7+ letters matched with a small edit distance.

Known false positives (accepted: an officer looks at them first, and missing a poisoning is worse):
  - "How do I protect myself from pesticide poisoning when spraying?"  (rule A)
  - "My father died last year and left me this farm."                 (rule E)
  - "Birds are eating my maize; the dead plants are near the field."  (rule D, words within the window)
  - "Is it safe if a goat ate grass sprayed with Roundup last month?"  (rule C)
Known misses: Twi or other local-language descriptions not covered by the keyword gloss; symptoms described
without any listed word (e.g. "my child is weak and shaking"); deaths of animals not in the animal list.
"""
from __future__ import annotations

import re
import unicodedata

PREFIX = "EMERGENCY:"

FARMER_MESSAGE = (
    "This may be an emergency. If a person has swallowed, breathed in or touched a farm chemical, or feels "
    "unwell, call 112 now or go to the nearest health facility. If animals are sick or have died, contact the "
    "nearest veterinary officer. An extension officer has been alerted to your message. AgriReach has not "
    "given any farming advice on this."
)

_LOOKALIKE = str.maketrans({"1": "i", "0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s",
                            "!": "i", "|": "l"})

POISONING = ("poisoned", "poisoning", "poisonings")
SYMPTOMS = ("vomit", "vomits", "vomited", "vomiting", "unconscious", "convulsion", "convulsions", "convulsing",
            "seizure", "seizures", "seizing", "foaming", "dizzy", "dizziness")
BREATH = ("breathe", "breathing", "breath")
BREATH_TROUBLE = ("difficulty", "difficult", "trouble", "cannot", "cant", "unable", "stopped", "not", "hard",
                  "short", "shortness", "struggling")
FAINT = ("fainted", "fainting", "faint", "collapsed", "collapse", "collapsing", "passedout")
INGEST = ("drank", "drink", "drinks", "drunk", "drinking", "swallowed", "swallow", "swallowing", "ate", "eaten",
          "licked", "inhaled", "breathed", "splashed", "spilled", "poured")
CHEMICAL = ("poison", "chemical", "chemicals", "pesticide", "pesticides", "insecticide", "insecticides",
            "herbicide", "herbicides", "weedicide", "weedicides", "weedkiller", "fungicide", "fungicides",
            "gramoxone", "paraquat", "glyphosate", "roundup", "dichlorvos", "ddvp", "sniper", "atrazine",
            "cypermethrin", "chlorpyrifos", "carbofuran", "furadan", "lambda", "karate", "dursban")
DEATH = ("died", "dead", "dying", "death", "deaths", "killed", "die", "dies")
ANIMALS = ("goat", "goats", "sheep", "cattle", "cow", "cows", "bull", "bulls", "calf", "calves", "livestock",
           "animal", "animals", "chicken", "chickens", "fowl", "fowls", "bird", "birds", "poultry", "pig", "pigs",
           "fish", "fishes", "dog", "dogs", "donkey", "donkeys", "duck", "ducks", "bee", "bees", "ram", "rams",
           "lamb", "lambs", "horse", "horses", "cat", "cats", "guinea", "turkey", "turkeys", "rabbit", "rabbits")
HUMANS = ("child", "children", "baby", "babies", "son", "daughter", "boy", "girl", "kid", "kids", "man", "men",
          "woman", "women", "person", "people", "husband", "wife", "brother", "sister", "father", "mother",
          "worker", "workers", "farmer", "farmers", "neighbour", "neighbor", "i", "he", "she", "they", "someone",
          "grandmother", "grandfather", "uncle", "aunt", "friend", "labourer", "laborer")
NOT_SIMILAR = {"prison", "prisons", "poisonous"}  # near a listed word by spelling, not an emergency word

WINDOW = 6


def _normalise(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    text = text.replace("can't", "cant").replace("can not", "cannot").replace("passed out", "passedout")
    tokens = []
    for raw in re.findall(r"[a-z0-9@$!|]+", text):
        raw = raw.strip("!|")
        if not raw:
            continue
        if re.search(r"[a-z]", raw):
            raw = raw.translate(_LOOKALIKE)
        raw = re.sub(r"([a-z])\1{2,}", r"\1", raw)
        tokens.append(raw)
    return tokens


def _distance(a: str, b: str, limit: int) -> int:
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def _matches(token: str, vocab: tuple[str, ...]) -> bool:
    if token in vocab:
        return True
    if token in NOT_SIMILAR or len(token) < 6:
        return False
    for word in vocab:
        if len(word) < 7 or word[0] != token[0]:  # short words (dying/drying, horses/houses) match exactly
            continue
        limit = 1 if len(word) < 9 else 2
        if _distance(token, word, limit) <= limit:
            return True
    return False


def _hits(tokens: list[str], vocab: tuple[str, ...]) -> list[int]:
    return [i for i, token in enumerate(tokens) if _matches(token, vocab)]


def _near(left: list[int], right: list[int], window: int = WINDOW) -> list[tuple[int, int]]:
    return [(a, b) for a in left for b in right if a != b and abs(a - b) <= window]


def detect(text: str) -> list[str]:
    """Officer-facing reasons, each starting with PREFIX. Empty when no rule matches."""
    tokens = _normalise(text)
    if not tokens:
        return []
    found: dict[str, set[str]] = {}

    def note(kind: str, *indexes: int) -> None:
        found.setdefault(kind, set()).update(tokens[i] for i in indexes)

    for i in _hits(tokens, POISONING):
        note("poisoning reported", i)
    for i in _hits(tokens, SYMPTOMS):
        note("poisoning symptoms reported", i)
    for b, t in _near(_hits(tokens, BREATH), _hits(tokens, BREATH_TROUBLE), 3):
        note("poisoning symptoms reported", t, b)
    living = _hits(tokens, HUMANS) + _hits(tokens, ANIMALS)
    for f, who in _near(_hits(tokens, FAINT), living):
        note("person or animal collapsed or fainted", f, who)
    for v, c in _near(_hits(tokens, INGEST), _hits(tokens, CHEMICAL), 8):
        note("chemical swallowed, inhaled or splashed", v, c)
    deaths = _hits(tokens, DEATH)
    for d, a in _near(deaths, _hits(tokens, ANIMALS)):
        note("animal, bird or fish deaths reported", d, a)
    humans = [i for i in _hits(tokens, HUMANS) if tokens[i] not in ("i", "he", "she", "they")]
    for d, h in _near(deaths, humans):
        note("a person's death reported", d, h)
    return [f"{PREFIX} {kind} (farmer wrote: {', '.join(repr(w) for w in sorted(words))}). "
            "Possible poisoning or chemical exposure: refer the farmer to emergency services (112), a health "
            "facility or a veterinary officer now. Crop-independent check; no advice was drafted."
            for kind, words in found.items()]


def is_emergency_reason(reason) -> bool:
    return isinstance(reason, str) and reason.startswith(PREFIX)