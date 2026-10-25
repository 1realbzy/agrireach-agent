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
sentence is supported. Off unless AGRIREACH_JUDGE_MODEL is set. Officer-facing lines, restatements of the question,
"the sources differ / one source says X, another Y" lines (conflicts are detected and their figures checked in code)
and sentences with no content words (list markers like "1.") are not sent to it. See judge.py.

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
# Lines the judge is not asked about: officer-facing instructions, restating the question, and saying the sources
# differ (conflicts are detected by code and their figures are checked by citation_check).
# Uncited lines exempt from the lexical layer (still judged): notes and lines about the reply's language.
UNCITED_META_RE = re.compile(r"^\W*note\b|\b(?:twi|dagbani|wali|ewe|hausa|language|respond|reply)\b", re.I)
# Officer-addressed lines ARE judged: "the officer should tell the farmer it is safe to sell" is still advice.
NOT_JUDGED_RE = re.compile(r"\bfarmer\s+(?:asks|is\s+asking|wants\s+to\s+know)\b"
                           r"|\bsources?\b[^.]*\b(?:disagree|differ)|\bdisagree|\bdisput|\bone\s+source\b[^.]*\banother\b",
                           re.I)
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


def source_aliases(passages: list[dict]) -> dict[str, set[str]]:
    """alias -> source ids. Aliases are the alphabetic parts of a source id ("APNI-SARI-2023" -> apni, sari)."""
    crops = {p.get("crop", "") for p in passages}
    out: dict[str, set[str]] = {}
    for p in passages:
        for tok in re.findall(r"[A-Za-z]{3,}", p["source_id"]):
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


def check_claims(draft: str, passages: list[dict], conflicts: dict | None = None, judge: bool | None = None,
                 ignore_prefixes: tuple[str, ...] = (), judge_call=None) -> ClaimResult:
    """judge: None = judge.enabled() (always on); False only for code-built verbatim drafts. judge_call replaces the
    judge's network call (tests). Uncited sentences are checked against every passage the draft cites."""
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
        low = bare.lower()
        # 1. Named sources.
        for alias, srcs in aliases.items():
            if re.search(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", low) and not any(p["source_id"] in srcs for p in cited):
                problems.append(f"'{_short(s.text)}' names {alias.upper()} but cites no {alias.upper()} passage")
        if not cited:
            # An uncited sentence (after a paragraph's last citation, or in a paragraph with none) can still add a
            # claim. Check it against everything the draft cites; headings ("...:") carry no claim.
            words = content_words(bare)
            plain = re.sub(r"\*\*|__|`", "", bare).strip()
            if not all_cited or not words or plain.endswith(":") or NOT_JUDGED_RE.search(bare):
                continue
            checked += 1
            if not META_RE.search(bare) and not UNCITED_META_RE.search(plain) and not words & content_words(" ".join(p["text"] for p in all_cited)):
                problems.append(f"'{_short(s.text)}' has no citation and is not supported by any cited passage "
                                "(no shared content words)")
                continue
            to_judge.append((s, all_cited))
            continue
        checked += 1
        by_src: dict[str, list[dict]] = {}
        for p in cited:
            by_src.setdefault(p["source_id"], []).append(p)
        # 2. Agreement claims.
        if AGREE_RE.search(bare) and not NEGATED_AGREE.search(bare):
            if len(by_src) < 2:
                problems.append(f"'{_short(s.text)}' says sources agree but cites only {', '.join(by_src)}; cite each "
                                "source that says it, or don't claim agreement")
                continue
            weak = [src for src, ps in by_src.items() if not _backs(bare, ps)]
            if weak:
                problems.append(f"'{_short(s.text)}' says sources agree, but {', '.join(weak)} does not say this")
                continue
            figs = citation_check.extract_figures(bare)
            ids = {p["id"] for p in cited}
            for key, group in conflict_groups:
                if len({by_id[i]["source_id"] for i in ids & group}) > 1 and not figs:
                    problems.append(f"'{_short(s.text)}' describes the detected disagreement on {key.replace('_', ' ')} "
                                    "as agreement")
                    break
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
        if words and not NOT_JUDGED_RE.search(bare):
            to_judge.append((s, cited))
    judged = None
    from agrireach import judge as judge_mod
    if (judge if judge is not None else judge_mod.enabled()) and to_judge:
        # Place names the cited passages don't contain are masked: whether a Northern Ghana guide applies to the
        # farmer's place is decided in code (caution note + urgent flag), and the judge kept rejecting
        # "For soybean planting in Kumasi, ..." on that ground alone (7 of its 8 replay false rejects).
        items = [(places.mask(s.text, keep=" ".join(p["text"] for p in cited)), cited) for s, cited in to_judge]
        judged = judge_mod.judge(items, call=judge_call)
        if judged.get("error"):
            problems.append(f"source check couldn't run: the judge model gave no verdict ({judged['error'][:120]})")
        for v, (s, _c) in zip(judged.get("verdicts", []), to_judge):
            if v["sentence"] != s.text:
                v["sent_to_judge"], v["sentence"] = v["sentence"], s.text
        for v in judged.get("verdicts", []):
            if v["verdict"] == "not_supported":
                problems.append(f"'{_short(v['sentence'])}' is not supported by its citation according to the judge "
                                f"model: {v.get('why', '')}".rstrip(": "))
    return ClaimResult(ok=not problems, problems=list(dict.fromkeys(problems)), checked=checked, judge=judged,
                       judge_failed=bool(judged and judged.get("error")))
