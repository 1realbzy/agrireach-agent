"""Bounded vocabulary boundary for novel advice, independent of instruction verbs.

This classifies uncertainty, not semantic truth. A model may assess source support
only after all material/entity terms have a known nonchemical interpretation.
Names outside the vocabulary require review even in fragments or passive voice.
Common-word product names remain a limitation; do not claim universal recognition.
"""
import re

# Ordinary grammatical and agricultural words are not evidence of a product.
# This set permits model assessment, not automatic source support or approval.
GENERAL_WORDS = set("""a an the this that these those i you your we our they their it its them and or but
with without to from into onto on in at by for of as if when while before after
is are was were be been being should could would can may must will do does did
not no never only also then than very more less some any all each every once twice
one two three four five six seven eight nine ten first second day days week weeks
month months morning evening daily weekly need needs local recommended which what
how why where about until well use using used put pour add added sprinkle soak
scout scouting inspect check look monitor observe remove harvest mature pods leaves
leaf field crop crops plant plants planting maize soybean soybeans seed seeds soil
ground water clean dry wet damp keep kept storage stored store bag bags sacks sack
jute knife hoe tool tools cut cutting weeds weed weeding roots root stem stems cobs
cob grain grains ready brown green turned turn most carefully regularly gently
proper properly clear away damaged damage insect insects larvae pests pest holes
rotating rotate rotation plough ploughing deeply burn bury residues growth stunted
compost manure ash mulch organic decomposed mature matter healthy ripe sow sowing
apply applied applying mix mixed mixing spread place scatter cover top around near
row rows between separate spacing apart wash drying sunlight shade ventilation
farmer farmers advice advise officer extension agent agricultural aea consult ask
talk seeing see visit confirm follow help safety safe gloves label protect wear
temperature c kɔforidua tamale adaklu ejura kintampo northern ghana area region
so guides guide comes suit like future weeded timing looking manage color consider
problems think infestation signs find prevent ashanti farm armyworm fall apni
zone zones answer b checked kumasi
recommend know unsure sure thank please information carefully advice necessary
""".split())
DOSE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ml|mg|g|kg|litres?|liters?|tablets?|capsules?|percent|%)\b", re.I)
CONSULTATION = re.compile(r"\b(?:aea|extension (?:officer|agent))\b", re.I)


def words(text: str) -> set[str]:
    """Return lexical terms without interpreting punctuation or capitalization."""
    return set(re.findall(r"[^\W\d_]+", text.casefold()))


def unresolved_terms(sentence: str, source_texts: list[str]) -> set[str]:
    """Return unknown entities/materials; full source support is checked elsewhere.

    The cited source vocabulary supplies provenance context. The reviewed general
    vocabulary supplies nonchemical interpretations. Neither is semantic proof.
    Do not add reported brands here or whitelist whole sentences containing them.
    """
    known = GENERAL_WORDS | {w for text in source_texts for w in words(text)}
    return words(sentence) - known


def consultation_bypass(sentence: str) -> bool:
    """Recognize devaluing/refusing consultation regardless of chemical sources.

    Ambiguous consultation language is held by the caller. Protective negations
    do not become harmful solely because they mention a negative predicate.
    """
    if not CONSULTATION.search(sentence):
        return False
    value = sentence.casefold()
    protective = re.search(r"\b(?:do not|don't|never) (?:skip|avoid|ignore|bypass)\b", value)
    if protective:
        return False
    return bool(re.search(r"\b(?:no point|pointless|unnecessary|irrelevant|waste of time|"
                          r"need not|needn't|not necessary|don't bother|do not bother|"
                          r"skip|avoid|ignore|bypass)\b", value))
