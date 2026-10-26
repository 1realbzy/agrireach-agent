"""Three hard stops for unsourced advice lines; the judge and officer handle agronomy.

safety_gate records them as S3, S2, S4 (S1 is the separate chemical safeguard). S2 and
pesticide or spraying lines are blocked; other S3 and S4 hits are held for the officer.
S3 unsourced_input(): a product, dose or rate, a vague thing applied ("Pour it..."), or anything on plants.
S2 skips_officer(): an AEA mention that is not a plain referral ("Do not ask the AEA").
S4 burns_land(): burning or setting fire, unless it says not to or a cited source burns."""
import re

APPLY = r"put|pour|apply|sprinkle|add|soak|dip|coat|wipe|rub|mix|give|use|smear|paint|spread|scatter|place"
# Treating, dusting or drenching a crop is chemical work, whatever it is done with.
TREAT = re.compile(r"\b(?:treat|dust|drench|dress|fumigate|coat)\w*\b(?! with (?:water|ash)\b)", re.I)
# How often to apply is a dose too: an apply, spray or treat word with a repeat word, or a re-application.
REPEAT_VERB = r"(?:re-?)?(?:appl(?:y|ie[sd]|ying|ications?)|spray(?:s|ed|ing)?|treat(?:s|ed|ing|ments?)?)"
REPEAT_WORD = (r"twice|thrice|again|every|times|weekly|daily|fortnight\w*|intervals?|repeat\w*|keep applying|in a week|"
               r"once (?:a|per|every|more|again)|once\b.*\bonce|each (?:day|week|season)")
REPEAT = re.compile(rf"\b{REPEAT_VERB}\b.*\b(?:{REPEAT_WORD})\b|\b(?:{REPEAT_WORD})\b.*\b{REPEAT_VERB}\b|\bre-?appl|\bsecond (?:time|dose|application|treatment|spray)", re.I)
PRODUCT = re.compile(  # "sulphate of ammonia" is an ordinary fertiliser, not household ammonia
    r"\b(?:mancozeb|karate|lambda|actellic|phostoxin|gramoxone|paraquat|glyphosate|atrazine|attakan|emamectin|"
    r"tylosin|ampligo|coragen|kerosene|petrol|diesel|engine oil|detergent|bleach|carbide|battery|"
    r"(?<!sulphate of )(?<!sulfate of )ammonia|\w{3,}(?:thrin|phos|fos|carb|zeb|mectin|cides?|azole|oxone|"
    r"thoate|cloprid|phosphide))\b", re.I)
DOSE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ml|mg|g|kg|l|litres?|liters?|tablets?|sachets?|capfuls?|cups?|spoons?|"
                  r"bottles?|bags?)\b|\b(?:pinch|capful|sachet|bottle[- ]top|tablespoon|teaspoon|tablet)s?\b"
                  r"|\bper (?:acre|hectare|knapsack|litre|bucket)\b", re.I)
# What follows an application verb (or "with") when it is unclear what it is.
VAGUE = (r"it|them|some(?!\s+[a-z]{3,})|that|this|these|those|any|whatever|what|a little|a bit|one|two|three|a few|"
         r"(?:the |a |your )?(?:\w+ )?(?:powder|mixture|stuff|liquid|solution|product|medicine|remedy|thing|"
         r"chemical|control|treatment|one)s?\b")
UNCLEAR = re.compile(rf"\b(?:{APPLY}|with)\s+(?:{VAGUE})\b|\b(?:{APPLY})(?:\s*$|\s+(?:to|on|onto|over)\b)", re.I)
# A capitalised name as the thing applied is probably a brand ("Use Clear on the weeds").
CAPITALISED = re.compile(rf"\b(?i:{APPLY})\b(?:.*\b(?:in|with)\b)?\s+(?:the |some |a )?(?!PICS\b|NPK\b|MoFA\b)[A-Z]\w*")
# Anything "on the leaves" is held unless the line is about looking at them.
ON_PLANTS = re.compile(rf"\b(?:on|onto|over|(?:{APPLY})\s+\w+\s+to)\s+(?:the\s+|your\s+|each\s+)?(?:\w+\s+)?(?:leaf|leaves|plants?|crops?|"
                       r"weeds?|funnels?|cobs?|grains?|seeds?|stems?|roots?|maize|pods)\b", re.I)
BURN = re.compile(r"\b(?:burn\w*|torch\w*|set\w* fire|with fire|fire to)\b", re.I)
LOOKING = re.compile(r"\b(?:look|check|scout|inspect|see|find|search|count|eggs?|holes|damage|frass|spots|signs)\b", re.I)
CLAIM = re.compile(r"\b(?:kills?|controls?|cures?|works? (?:on|against|for)|(?:is|are) (?:good|best|effective) "
                   r"(?:for|against|on))\s+(?:the |your )?(?:pests?|insects?|worms?|armyworms?|caterpillars?|weeds?|"
                   r"diseases?|cobs?|leaves|crops?|plants?|maize|soybeans?)\b|\bworks?$", re.I)


def unsourced_input(sentence: str) -> str | None:
    """Explain why an unsourced line about putting something on a crop needs editing, or return None."""
    s = re.sub(r"\btop[- ]dress\w*", "topdress", sentence.strip().rstrip(".!?"), flags=re.I)
    if PRODUCT.search(s):
        return "names a pesticide, chemical or household product"
    if DOSE.search(s):
        return "gives a dose or rate"
    label_only = re.match(r"for [\w ]{1,20}:\s*\w+\s*(?:,|$)", s, re.I)  # "For maize: X, before harvest"
    if TREAT.search(s) or UNCLEAR.search(s) or CAPITALISED.search(s) or label_only:
        return "does not say plainly what is applied"
    if (ON_PLANTS.search(s) and not LOOKING.search(s)) or CLAIM.search(s):
        return "puts something on the plants or claims a cure"


OFFICER = re.compile(r"\b(?:aeas?|extension|(?:the|your) agents?|agricultural (?:officer|agent)s?|officers?(?!-checked)|mofa staff)\b", re.I)
# The officer clause must read as sending the farmer to the officer.
REFERRAL = re.compile(
    r"^(?:(?:so|then|and|just|please|you should|you can|you may)\s+)*(?:consult|ask|talk to|speak to|see|visit|call|"
    r"contact|tell|check(?:\s+\w+){0,3}\s+with)\s+(?:your|the|a)\b"
    r"|^(?:your|the) (?:local )?aea can (?:help|confirm|advise|show)\b"
    r"|^(?:do not|don't|never) (?:skip|ignore|forget) (?:the|your) (?:local )?(?:aea|extension officer)$"
    r"|\b(?:until|before|after|once) (?:your|the) (?:local )?(?:aea|extension officer) (?:has |have )?"
    r"(?:seen|checked|visited|confirmed|advised)\b", re.I)
DEVALUE = re.compile(r"\b(?:no|not|never|don't|without|instead|unnecessary|skip|avoid|ignore|forget|bypass|waste|"
                     r"bother|wait|delay|yourself|alone|only|unless|rather|optional)\b|n't\b", re.I)


def skips_officer(sentence: str) -> bool:
    """True when a line steers the farmer from the officer: an officer clause must be a plain referral."""
    s = sentence.strip().rstrip(".!?")
    if re.search(r"\binstead\b", s, re.I) and re.search(r"\b(?:ask|consult|talk to|see|call)\b", s, re.I): return True
    for clause in re.split(r"[,;:]|\b(?:but|though|although)\b", s):
        clause = clause.strip()
        if not OFFICER.search(clause):
            if DEVALUE.search(clause) and re.search(r"\b(?:need|needed|necessary|required|worth)\b", clause, re.I):
                return OFFICER.search(s) is not None
            continue
        # A trailing condition ("... if you see no improvement") is about the farm, not the officer.
        core = re.split(r"\s+\b(?:if|when|before|after|until)\b(?! (?:your|the) (?:local )?aea)", clause, maxsplit=1, flags=re.I)[0]
        waits = re.match(r"(?:do not|don't|never) (?:skip|ignore|forget|\w+ (?:anything )?until)\b", clause, re.I)
        if not REFERRAL.search(clause) or (DEVALUE.search(core) and not waits):
            return True
    return False


def burns_land(sentence: str) -> bool:
    """True when a line advises burning; "Do not burn the bush" is fine."""
    return bool(BURN.search(sentence)) and not re.match(r"(?:do not|don't|never|avoid)\s+(?:burn|set|torch)|burn nothing", sentence.strip(), re.I)
