"""Claim check: sentences WITHOUT figures must still be backed by the passages they cite.

Runs after the figure check in citation_check.py, in code, before a draft reaches the officer. Three layers:

1. Named sources (deterministic). A sentence that names a source ("IITA says...") must cite a passage from it.
2. Agreement claims (deterministic). A sentence that says sources agree ("both sources agree", "all guides
   recommend") must cite passages from at least two sources, and EACH cited source must back it on its own:
   every figure in the sentence is in that source's passage, or, with no figures, at least 60% of the sentence's
   content words are in that source's passage. Calling a detected disagreement agreement fails, unless the sentence states a
   figure every cited source shares ("both give 50 cm between rows").
3. Support (lexical, deterministic). A cited sentence must share at least one content word with the passages
   it cites (officer-facing lines that only borrow the next sentence's citation are exempt). This catches a citation that has nothing to do with the sentence (e.g. a herbicide passage cited
   for "this is not a confirmed diagnosis"); it can NOT tell a paraphrase from a contradiction.

Optional layer 4: a model judge (agrireach.judge), separate from the drafting model, asked whether each cited
sentence is supported. Always on (judge.enabled()). Only sentences that are WHOLLY one of the no-advice shapes in
NOT_JUDGED_RE (an officer inspect/visit/refer line, restating the question, "we do not know X", "the sources differ",
"one source says X, another Y" with measurement words only, a figure-free note that a rainfall record is attached,
optionally behind a short topic heading such as "**Planting Window:**") and sentences with no content words (list markers like
"1.") are not sent to it; anything added to a shape is judged. See judge.py.

Sentences attach to citations the same way figures do in citation_check: a sentence takes the citations inside
it, or else the next citation in the same paragraph. Sentences after a paragraph's last citation are uncited and
are not checked here (they are mostly officer-facing notes; see EVALS for what this misses).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agrireach import citation_check, places

CITE_RE = citation_check.CITE_RE
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'(*\-\[A-Z0-9])")
AGREE_RE = re.compile(
    r"\bagree(?:s|d|ment)?\b|\bconsensus\b|\bconsistent(?:ly)?\b|\bin\s+line\s+with\s+each\s+other\b"
    r"|\b(?:both|all|two|several|multiple)\s+(?:of\s+the\s+|the\s+)?(?:sources|guides|passages|documents|references|"
    r"manuals|studies)\b"
    r"|\bboth\s+(?:recommend|say|state|suggest|advise|give|note|mention)\b", re.I)
# Officer-facing instructions and AgriReach policy lines ("The officer should not recommend a chemical...").
META_RE = re.compile(r"\b(?:officer|officers|agrireach|aea)\b", re.I)
# Uncited lines exempt from the lexical layer (still judged): notes and lines about the reply's language.
UNCITED_META_RE = re.compile(r"^\W*note\b|\b(?:twi|dagbani|wali|ewe|hausa|language|respond|reply)\b", re.I)
# Lines the judge is not asked about. Officer-addressed lines ARE judged in general ("the officer should tell the
# farmer it is safe to sell" is still advice); only the whole-sentence shapes below are exempt. Each shape must match
# the ENTIRE sentence (citations already removed; list markers, bold markers and a final full stop allowed), so a
# claim tacked on with "and", "so", "because", a comma, ";" or ":" makes the sentence longer than its shape and it is
# judged. Bare "disagree"/"disputed"/"differ" anywhere no longer exempts (review of ae53dc3, 25 Oct). The shapes come
# from live false rejects (docs/live-eval-2026-10-25-run2.md) and the existing tests; see tests/test_not_judged_anchored.py.
# One plain word that is not a joining word or a modal (so a word run can never carry a second clause or an order).
_W = (r"(?!(?:and|or|so|but|because|since|as|which|that|then|while|if|whether|though|although|unless|should|must"
      r"|need|needs|always|never)\b)[a-z][a-z'-]*")
_WORDS = lambda lo, hi: rf"{_W}(?:\s+{_W}){{{lo - 1},{hi - 1}}}"  # noqa: E731 - lo..hi plain words
_DET = r"(?:the|this|that|these|their|your|his|her|its|a|an)"
_OFFICER = r"(?:the\s+)?(?:extension\s+)?officer\s+(?:should|must|can|may)\s+(?:also\s+)?"
# Officer actions that give the farmer no advice: look at the crop, or send the case to a named person or office.
_THING = (r"(?:field|fields|farm|crop|crops|plants?|maize|soybeans?|cowpeas?|leaves|cobs|grain|store|storage|"
          r"sample|samples)")
_PERSON = (r"(?:(?:a|an|the|your|their)\s+)?(?:local\s+|nearest\s+|district\s+)?(?:aea|aeas|agricultural\s+extension"
           r"\s+(?:agent|officer)|extension\s+(?:agent|officer)|expert|specialist|plant\s+clinic|mofa\s+office"
           r"|district\s+agricultural\s+office|agricultural\s+office)")
# Fixed, advice-free tails (live run3 A1/A2 F6): what to look for, and "if unsure" on a referral.
_ACT = (rf"(?:inspect|visit|examine)\s+{_DET}\s+(?:affected\s+)?{_THING}"
        r"(?:\s+for\s+(?:signs|symptoms)\s+of\s+(?:infestation|damage|disease|pests?|attack))?"
        rf"|refer\s+(?:(?:the\s+farmer|them|the\s+case|this\s+case)\s+)?to\s+{_PERSON}"
        r"(?:\s+for\s+(?:a\s+)?(?:proper\s+|closer\s+|full\s+)?(?:diagnosis|inspection|advice))?"
        r"(?:\s+if\s+(?:unsure|in\s+doubt|needed|necessary))?"
        r"|confirm\s+(?:it|this|the\s+(?:window|option|choice))\s+with\s+the\s+farmer")
# A figure-free measurement phrase for "one source says X, another says Y": only measurement words, so advice
# ("to avoid loss of seed vigor") falls outside the shape. The figures themselves are checked by citation_check.
_MONTH = (r"(?:january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar"
          r"|apr|jun|jul|aug|sep|sept|oct|nov|dec)")
_MTOK = (rf"(?:\d+(?:[.,]\d+)?(?:-\d+(?:[.,]\d+)?)?|(?:early|mid|late|end|start)-{_MONTH}|{_MONTH}|cm|mm|m|kg|g|ha"
         r"|acre|acres|ppb|weeks?|days?|%|between|and|to|of|about|around|a|the|depth|deep|rows?|plants?|in|within"
         r"|spacing|row-to-row|plant-to-plant|not|deeper|more|than|exceeding|holes|making|planting|plant|apart|per"
         r"|hill|seeds?|stand|early|mid|late|end|start|from|until|after|before)")
_MEASURE = rf"{_MTOK}(?:(?:\s+|\s*,\s*(?=not\b)){_MTOK})*"
_SAYS = r"(?:says|said|suggests|recommends|advises|gives|states)"
_TOPIC = rf"(?:(?:for|on|regarding)\s+(?:the\s+)?{_WORDS(1, 3)}\s*,\s*)?"
_SHAPES = [
    # Restating the question: "The farmer asks when to plant soybeans in Tamale."
    rf"the\s+farmer\s+(?:asks|is\s+asking|wants\s+to\s+know)\s+{_WORDS(1, 12)}",
    # An officer action, or two joined by "and"/"or": "The officer should inspect the field or refer the farmer to
    # an expert." / imperative "Refer the farmer to your local AEA."
    rf"(?:{_OFFICER})?(?:{_ACT})(?:\s+(?:and|or)\s+(?:{_ACT}))?",
    # A pure choice instruction to the officer: "The officer should choose which limit to advise the farmer to follow."
    # / bare "Choose which planting window to follow." (live run3, core task 11)
    rf"(?:{_OFFICER})?(?:choose|decide|confirm)\s+which\s+(?:of\s+the\s+(?:two|cited)\s+)?"
    r"(?:(?:planting|plant|sowing|seeding|row)\s+)?(?:limit|spacing|window|option"
    r"|figure|depth|rate|source|guide|one)s?(?:\s+to\s+(?:recommend|use|follow|advise(?:\s+the\s+farmer\s+to\s+follow)?))?",
    # Choosing between the cited options: "Choose the appropriate window and confirm it with the farmer."
    rf"(?:{_OFFICER})?(?:choose|pick|select)\s+the\s+(?:appropriate|right|correct|suitable)\s+(?:window|option|limit"
    r"|figure)(?:\s+based\s+on\s+local\s+conditions)?(?:\s+and\s+confirm\s+(?:it|this)\s+with\s+the\s+farmer)?",
    # Saying what is not known: "We do not know the variety." / "We do not know if this method is effective."
    # The if/whether clause may end in one "X or Y" pair ("safe to sell or feed"); a second clause after "or" is longer.
    rf"(?:we|i|agrireach)\s+(?:do\s+not|don't|cannot|can't)\s+(?:know|say)\s+(?:(?:if|whether)\s+{_WORDS(1, 12)}"
    rf"(?:\s+or\s+{_W})?|{_WORDS(1, 5)})",
    # With no subject only "do not know if/whether ...": "Do not know if the maize is safe to sell or feed." (live
    # run3, A2 F7). A bare imperative like "Do not say..." or "Do not confirm..." is judged.
    rf"(?:do\s+not|don't)\s+know\s+(?:if|whether)\s+{_WORDS(1, 12)}(?:\s+or\s+{_W})?",
    # Describing the attached rainfall record, with no figures (live run3: EJB2-4, core task 11). Its figures are never
    # exempt: they go through the figure check and the judge like any other sentence.
    r"(?:a|the)\s+rainfall\s+record(?:\s+for\s+" + _WORDS(1, 3) + r")?\s+is\s+(?:attached|included|provided)"
    r"(?:\s+for\s+(?:your|the\s+officer['\u2019]s)\s+reference)?",
    r"(?:this|the\s+rainfall\s+record|the\s+record|this\s+data)\s+is\s+a\s+model\s+estimate",
    # "The curated sources do not cover this pest."
    rf"the\s+(?:curated\s+)?(?:passages|sources)\s+do\s+not\s+(?:mention|cover|say|address|describe)\s+{_WORDS(1, 5)}",
    # "The planting window varies by source." / "Plant spacing is disputed."
    rf"(?:the\s+)?{_WORDS(1, 3)}\s+(?:var(?:y|ies)|differs?)\s+(?:by|between|across)\s+(?:the\s+)?sources?",
    rf"(?:the\s+)?{_WORDS(1, 3)}\s+is\s+disputed",
    # "Sources disagree on the planting window." / "For plant spacing, sources disagree."
    rf"{_TOPIC}(?:the\s+)?sources\s+(?:also\s+)?(?:disagree|differ)(?:\s+(?:on|about)\s+(?:the\s+)?{_WORDS(1, 3)})?",
    # Two attributions and nothing else: "One source says 5 cm, another says 3 cm, not deeper than 5 cm."
    rf"{_TOPIC}one\s+source\s+{_SAYS}\s+(?:to\s+plant\s+)?{_MEASURE}\s*,\s*(?:while\s+|and\s+)?another\s+(?:source\s+)?"
    rf"(?:{_SAYS}\s+)?(?:to\s+plant\s+)?{_MEASURE}",
]
# A short topic heading in front of a shape: "- **Planting Window:** Sources disagree." (live run3, core task 12). Only
# topic nouns, 1-4 of them, then a colon, so a heading can't carry an order ("Plant early:", "Spray now:" are judged),
# and what follows must itself be a whole shape ("Planting window: plant in June." is judged).
_HEAD_WORD = (r"(?:planting|plant|sowing|seed|seeds|seeding|row|rows|window|windows|depth|spacing|rate|timing|date|dates"
              r"|season|fertili[sz]er|top|dressing|application|harvest|harvesting|storage|weather|rainfall|soil|moisture"
              r"|pest|pests|disease|control|variety|varieties|maize|soybeans?|cowpeas?|yield|note|summary|sources?"
              r"|conflict|options?|local|information|aflatoxin|limits?)")
_HEADING = rf"(?:\*\*|__)?\s*{_HEAD_WORD}(?:\s+{_HEAD_WORD}){{0,3}}\s*(?:\*\*|__)?\s*:\s*(?:\*\*|__)?\s+"
NOT_JUDGED_RE = re.compile(r"^[\s*#>\-•]*(?:\d+[.)]\s+)?(?:" + _HEADING + r")?(?:\*\*|__)?\s*(?:" + "|".join(_SHAPES)
                           + r")\s*(?:\*\*|__)?\s*[.!]?[\s*]*$", re.I)


def not_judged(bare: str) -> bool:
    """True only if the WHOLE sentence (citations removed) is one of the no-advice shapes in NOT_JUDGED_RE."""
    return bool(NOT_JUDGED_RE.fullmatch(re.sub(r"\s+", " ", bare).strip()))


# "It is still worth applying / not too late" answers a late-timing question. The judge accepted it live (F5) from
# passages that only give the ideal time, so code requires a cited passage that itself speaks about late timing.
# Only claims that a late ACTION is possible or worthwhile match: "can/could/may still <verb>", "is still worth /
# possible / fine", "still worth", "there is still time", "not too late". A present-tense state ("the worms are still a
# problem", "the larvae are still present") is not a timing claim (F1 live false reject, run3 on a5e9192).
LATE_CLAIM_RE = re.compile(r"\b(?:can|could|may|might)\s+still\b"
                           r"|\bstill\s+(?:worth|ok|okay|fine|possible|useful|in\s+time|time|help|apply|plant|sow"
                           r"|be\s+(?:applied|planted|sown|done|used))\b"
                           r"|\b(?:there\s+is|you\s+have)\s+still\s+time\b|\bnot\s+too\s+late\b", re.I)
# "can be planted up to end of July" speaks about late timing; "delay ... until some rains" (moisture) does not.
LATE_SUPPORT_RE = re.compile(r"\b(?:late|later|still|missed|up\s+to)\b", re.I)
NEGATED_AGREE = re.compile(r"\b(?:not|n't|never|dis)\s*agree|\bdo\s+not\s+agree|\bdiffer|\bdisagree", re.I)
# Words that carry no claim of their own: function words, advisory verbs and officer-facing meta talk.
STOP = set("""a an the is are was were be been being am of to in on at by for from with without as and or but nor so
if then than that this these those it its it's they them their there here he she you your yours we our us i me my
can could should would will shall may might must do does did done not no yes also too very about into over under
up down out off again further more most less least such only own same other another each any all both some many much
few one two which who whom whose what when where why how while because until before after above below between
during against per via etc also just still even ever however instead additionally therefore thus overall
officer officers farmer farmers agrireach source sources passage passages guide guides document documents
reference references cited cite according says say said state states stated suggest suggests suggested recommend
recommends recommended recommendation advise advises advised advice note notes ensure consider make sure
help helps important best good well better ideal appropriate proper properly
agree agrees agreed agreement consensus consistent consistently
choose chose pick decide follow option options""".split())
# An agreement claim with no figures must share at least this share of its content words with EACH cited source.
AGREE_MIN_OVERLAP = 0.6
_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ness", "ies", "ied", "ers", "er", "ed", "es", "ly",
             "s", "e")
# Spelling variants and close synonyms seen in drafts; both sides are mapped before comparing.
VARIANTS = {"fertiliser": "fertilizer", "fertilisers": "fertilizer", "sowing": "planting", "sow": "plant",
            "colour": "color", "mould": "mold", "mouldy": "mold", "moldy": "mold", "deep": "depth",
            "deeper": "depth", "apart": "spacing", "distance": "spacing", "dried": "dry", "drying": "dry",
            "soya": "soybean", "soyabean": "soybean", "soybeans": "soybean", "soyabeans": "soybean",
            "armyworm": "army worm", "armyworms": "army worm", "pesticides": "pesticide", "chemicals": "chemical"}


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def content_words(text: str) -> set[str]:
    text = CITE_RE.sub(" ", text.lower())
    words = []
    for w in re.findall(r"[a-z]+(?:-[a-z]+)?", text):
        w = VARIANTS.get(w, w)
        words += w.replace("-", " ").split()
    return {_stem(w) for w in words if w not in STOP and len(w) > 2}


@dataclass
class Sentence:
    text: str
    ids: list[str]
    inline: bool  # True if the citation is inside the sentence, False if borrowed from a later sentence


def sentences(draft: str) -> list[Sentence]:
    """Split into sentences per paragraph and attach citations (own brackets, else the next bracket)."""
    out: list[Sentence] = []
    for para in draft.split("\n"):
        parts = [s.strip() for s in SENT_SPLIT.split(para) if s.strip()]
        pending: list[str] = []
        for s in parts:
            ids = [i for m in CITE_RE.finditer(s) for i in citation_check._split_ids(m.group(1))]
            if not CITE_RE.sub("", s).strip(" .,;:*-"):
                # A bare citation on its own ("[A]."): it belongs to the sentence(s) before it.
                for prev in out[len(out) - len(pending):] if pending else out[-1:]:
                    prev.ids += ids
                pending = []
                continue
            if ids:
                for prev in out[len(out) - len(pending):] if pending else []:
                    prev.ids = list(ids)
                pending = []
            else:
                pending.append(s)
            out.append(Sentence(s, list(ids), bool(ids)))
    return out


@dataclass
class ClaimResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    checked: int = 0
    judge: dict | None = None  # {"model":..., "verdicts":[...]} or {"error":...} when the judge ran
    judge_failed: bool = False  # the judge was required but could not give a verdict (the check then fails)


RECORD_COMMON_WORDS = {"rainfall", "open"}


def source_aliases(passages: list[dict]) -> dict[str, set[str]]:
    """alias -> source ids. Aliases are the alphabetic parts of a source id ("APNI-SARI-2023" -> apni, sari)."""
    crops = {p.get("crop", "") for p in passages}
    out: dict[str, set[str]] = {}
    for p in passages:
        toks = re.findall(r"[A-Za-z]{3,}", p["source_id"])
        if p.get("kind") == "record":
            # A data record (RAINFALL-OPEN-METEO): "rainfall" and "open" are ordinary words, so only the provider
            # name counts as naming it. A "**Rainfall**:" heading over a guide sentence is not a citation claim.
            toks = [t for t in toks if t.lower() not in RECORD_COMMON_WORDS]
        for tok in toks:
            tok = tok.lower()
            if tok not in crops:
                out.setdefault(tok, set()).add(p["source_id"])
    return out


def _short(s: str, n: int = 90) -> str:
    s = CITE_RE.sub("", s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _backs(sentence: str, ps: list[dict]) -> bool:
    """Does this one source's passages back the (agreement) sentence on their own? Figures must all be in the
    source; without figures, at least AGREE_MIN_OVERLAP of the sentence's content words must be."""
    figs = citation_check.extract_figures(CITE_RE.sub(" ", sentence))
    pool = [f for p in ps for f in citation_check.extract_figures(p["text"])]
    if figs:
        return all(citation_check._matches(f, pool) for f in figs)
    words = content_words(sentence)
    if not words:
        return True
    return len(words & content_words(" ".join(p["text"] for p in ps))) / len(words) >= AGREE_MIN_OVERLAP


def _named_source_problems(s: Sentence, low: str, cited: list[dict], aliases: dict) -> list[str]:
    """Layer 1: a sentence that names a source (MoFA, IITA...) must cite a passage from that source."""
    return [f"'{_short(s.text)}' names {alias.upper()} but cites no {alias.upper()} passage"
            for alias, srcs in aliases.items()
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low) and not any(p["source_id"] in srcs for p in cited)]


def _check_uncited(s: Sentence, bare: str, all_cited: list[dict]) -> tuple[bool, str | None, bool]:
    """An uncited sentence (after a paragraph's last citation, or in a paragraph with none) can still add a claim.
    It is checked against everything the draft cites; headings ("...:") carry no claim.
    Returns (counted as checked, problem or None, send to the judge)."""
    words = content_words(bare)
    plain = re.sub(r"\*\*|__|`", "", bare).strip()
    if not all_cited or not words or plain.endswith(":") or not_judged(bare):
        return False, None, False
    if not META_RE.search(bare) and not UNCITED_META_RE.search(plain) and \
            not words & content_words(" ".join(p["text"] for p in all_cited)):
        return True, (f"'{_short(s.text)}' has no citation and is not supported by any cited passage "
                      "(no shared content words)"), False
    return True, None, True


def _agreement_problem(s: Sentence, bare: str, cited: list[dict], by_id: dict, conflict_groups: list) -> str | None:
    """Layer 2, for a sentence that says sources agree: it must cite each source, each must back it, and it must not
    describe a detected disagreement as agreement."""
    by_src: dict[str, list[dict]] = {}
    for p in cited:
        by_src.setdefault(p["source_id"], []).append(p)
    if len(by_src) < 2:
        return (f"'{_short(s.text)}' says sources agree but cites only {', '.join(by_src)}; cite each "
                "source that says it, or don't claim agreement")
    weak = [src for src, ps in by_src.items() if not _backs(bare, ps)]
    if weak:
        return f"'{_short(s.text)}' says sources agree, but {', '.join(weak)} does not say this"
    figs = citation_check.extract_figures(bare)
    ids = {p["id"] for p in cited}
    for key, group in conflict_groups:
        if len({by_id[i]["source_id"] for i in ids & group}) > 1 and not figs:
            return f"'{_short(s.text)}' describes the detected disagreement on {key.replace('_', ' ')} as agreement"
    return None


def _run_judge(to_judge: list[tuple[Sentence, list[dict]]], judge_call) -> tuple[dict, list[str]]:
    """Layer 4: the judge model reads each sentence against its passages. Fails closed: an error is a problem."""
    from agrireach import judge as judge_mod
    problems = []
    # Place names the cited passages don't contain are masked: whether a Northern Ghana guide applies to the
    # farmer's place is decided in code (caution note + urgent flag), and the judge kept rejecting
    # "For soybean planting in Kumasi, ..." on that ground alone (7 of its 8 replay false rejects).
    items = [(places.mask(s.text, keep=" ".join(p["text"] for p in cited)), cited) for s, cited in to_judge]
    judged = judge_mod.judge(items, call=judge_call)
    if judged.get("error"):
        err = judged["error"]
        problems.append("source check couldn't run: no judge model is configured (set LLM_BASE_URL and LLM_API_KEY)"
                        if "LLM_BASE_URL" in err else f"source check couldn't run: the judge model gave no verdict "
                                                        f"({err[:120]})")
    for v, (s, _c) in zip(judged.get("verdicts", []), to_judge):
        if v["sentence"] != s.text:
            v["sent_to_judge"], v["sentence"] = v["sentence"], s.text
    for v in judged.get("verdicts", []):
        if v["verdict"] == "not_supported":
            problems.append(f"'{_short(v['sentence'])}' is not supported by its citation according to the judge "
                            f"model: {v.get('why', '')}".rstrip(": "))
    return judged, problems


def _late_timing_problems(to_judge: list) -> tuple[list, list[str]]:
    """Split off sentences that say it is not too late when none of their passages mentions late timing."""
    keep, problems = [], []
    for s, ps in to_judge:
        bare = CITE_RE.sub(" ", s.text)
        if LATE_CLAIM_RE.search(bare) and not any(LATE_SUPPORT_RE.search(p["text"]) for p in ps):
            problems.append(f"'{_short(s.text)}' says it is not too late, but no cited passage speaks about late timing")
        else:
            keep.append((s, ps))
    return keep, problems


def check_claims(draft: str, passages: list[dict], conflicts: dict | None = None, judge: bool | None = None,
                 ignore_prefixes: tuple[str, ...] = (), judge_call=None) -> ClaimResult:
    """Sentence-level claim check, in layers: named sources, uncited sentences, agreement claims, lexical support,
    then the judge. judge: None = judge.enabled() (always on); False only for code-built verbatim drafts.
    judge_call replaces the judge's network call (tests)."""
    from agrireach import judge as judge_mod
    if ignore_prefixes:
        draft = "\n".join(l for l in draft.splitlines() if not l.strip().startswith(ignore_prefixes))
    by_id = {p["id"]: p for p in passages}
    aliases = source_aliases(passages)
    conflict_groups = [(k, {p["id"] for p in g}) for k, g in (conflicts or {}).items()]
    problems: list[str] = []
    checked = 0
    to_judge: list[tuple[Sentence, list[dict]]] = []
    ss = sentences(draft)
    all_cited = [by_id[i] for i in dict.fromkeys(i for s in ss for i in s.ids) if i in by_id]
    for s in ss:
        cited = [by_id[i] for i in dict.fromkeys(s.ids) if i in by_id]
        bare = CITE_RE.sub(" ", s.text)
        problems += _named_source_problems(s, bare.lower(), cited, aliases)
        if not cited:
            counted, problem, judge_it = _check_uncited(s, bare, all_cited)
            checked += counted
            problems += [problem] if problem else []
            if judge_it:
                to_judge.append((s, all_cited))
            continue
        checked += 1
        if AGREE_RE.search(bare) and not NEGATED_AGREE.search(bare):
            if problem := _agreement_problem(s, bare, cited, by_id, conflict_groups):
                problems.append(problem)
            continue
        # 3. Lexical support: at least one shared content word with the cited passages. Skipped when the sentence has
        # no content words of its own (e.g. "One source says 15 cm [A], another 10 cm [B]": the figure check covers
        # it), and for an officer-facing line that only borrows the next sentence's citation.
        words = content_words(bare)
        if words and not (not s.inline and META_RE.search(bare)) and \
                not words & content_words(" ".join(p["text"] for p in cited)):
            problems.append(f"'{_short(s.text)}' is not supported by its citation {[p['id'] for p in cited]} "
                            "(no shared content words)")
            continue
        # The judge is only asked about sentences with content words (not list markers like "1.").
        if words and not not_judged(bare):
            to_judge.append((s, cited))
    to_judge, late = _late_timing_problems(to_judge)
    problems += late
    judged = None
    if (judge if judge is not None else judge_mod.enabled()) and to_judge:
        judged, judge_problems = _run_judge(to_judge, judge_call)
        problems += judge_problems
    return ClaimResult(ok=not problems, problems=list(dict.fromkeys(problems)), checked=checked, judge=judged,
                       judge_failed=bool(judged and judged.get("error")))
