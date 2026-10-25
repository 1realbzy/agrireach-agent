"""Minimal Twi (Akan) handling. This is NOT a translator: it detects that a question is probably in Twi and
glosses a few agricultural keywords into English so retrieval can find candidate passages. A Twi question is
always flagged urgent for the officer, who must confirm the meaning and reply in Twi."""
from __future__ import annotations

import re

# Strong markers: words/stems that are common in Twi questions and rare in English.
TWI_MARKERS = {"bere", "berɛ", "ɛberɛ", "ben", "bɛn", "sɛn", "sen", "deɛn", "dɛn", "wɔ", "mɛ", "yɛ", "ye", "ɛhe",
               "ahe", "afuo", "mfuo", "nnɔbae", "aduane", "dua", "nua", "twa", "otwa", "metumi", "mɛtumi", "ɛsɛ",
               "ese", "nhwiren", "mmoa", "nkɔsoɔ", "ɛne", "ɛyɛ", "nti", "anaa"}
# Keyword gloss -> English query words (covers the corpus topics only).
GLOSS = [
    (r"\b(?:bere|berɛ|ɛberɛ)\s+(?:ben|bɛn)\b|\bda\s+(?:ben|bɛn)\b", "when"),
    (r"(?<!\ba)dua\b|gu\s+aba\b|nua\b", "plant"),  # not 'adua' (pea/bean), which is a crop, not the verb
    # Twi crop names, verified 25 Oct 2026 (Wikidata Q11575 Akan label 'aburo'; Wiktionary 'aburoo', 'bankye',
    # 'bayerɛ', 'ɛmo', 'borɔdeɛ'). Not added: 'nkateɛ' (groundnut, unconfirmed); 'adua' means pea, not cowpea.
    (r"\baburo+\b", "maize"),
    (r"\bbankye\b", "cassava"),
    (r"\bbayer[ɛe]\b", "yam"),
    (r"(?<![a-zɛɔ])ɛmo\b", "rice"),
    (r"\bbor[ɔo]de[ɛe]\b", "plantain"),
    (r"\b\w*twa\b", "harvest"),
    (r"\b(?:soya|soja|soyabean)\b", "soybean"),
    (r"\b(?:ntam|kwan\s+ntam)\b", "spacing"),
    (r"\b(?:wura|nwura)\b", "weeds"),
    (r"\baba\b", "seed"),
]
CROP_WORDS = r"soy(?:a)?bean|\bsoya\b|\bsoja\b"
# Crops AgriReach can recognise in a question. Recognising a crop is not the same as covering it: coverage comes from
# the corpus (knowledge.crops_covered()), and a recognised but uncovered crop goes to the officer.
CROPS = {
    "soybean": CROP_WORDS,
    "maize": r"\bmaize\b|\bcorn\b|\baburo+\b",
    "cocoa": r"\bcocoa\b",
    "tomato": r"\btomato(?:es)?\b",
    "rice": r"\brice\b|(?<![a-zɛɔ])ɛmo\b",
    "cassava": r"\bcassava\b|\bbankye\b",
    "yam": r"\byams?\b|\bbayer[ɛe]\b",
    "groundnut": r"\bgroundnuts?\b|\bpeanuts?\b",
    "cowpea": r"\bcowpeas?\b",
    "pepper": r"\bpeppers?\b",
    "sorghum": r"\bsorghum\b",
    "millet": r"\bmillet\b",
    "plantain": r"\bplantains?\b|\bbor[ɔo]de[ɛe]\b",
    "cashew": r"\bcashews?\b",
    "onion": r"\bonions?\b",
}


def detect_crop(q: str) -> str:
    """The first crop named in the question (by position), or "" if none is recognised."""
    ql = q.lower()
    found = [(m.start(), crop) for crop, pat in CROPS.items() for m in [re.search(pat, ql)] if m]
    return min(found)[1] if found else ""


def is_twi(q: str) -> bool:
    ql = q.lower()
    if re.search(r"[ɛɔƐƆ]", ql):
        return True
    toks = re.findall(r"[a-zɛɔ]+", ql)
    hits = sum(1 for t in toks if t in TWI_MARKERS or (len(t) > 4 and t.endswith(("dua", "twa"))))
    return hits >= 2


def gloss(q: str) -> str:
    """English keyword gloss of a Twi question (place names are kept as written)."""
    ql = q.lower()
    words = [en for pat, en in GLOSS if re.search(pat, ql)]
    return " ".join(dict.fromkeys(words))
