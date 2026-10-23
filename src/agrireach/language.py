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
    (r"(?:dua|gu\s+aba|nua)\b", "plant"),
    (r"\b\w*twa\b", "harvest"),
    (r"\b(?:soya|soja|soyabean)\b", "soybean"),
    (r"\b(?:ntam|kwan\s+ntam)\b", "spacing"),
    (r"\b(?:wura|nwura)\b", "weeds"),
    (r"\baba\b", "seed"),
]
CROP_WORDS = r"soy(?:a)?bean|\bsoya\b|\bsoja\b"


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
