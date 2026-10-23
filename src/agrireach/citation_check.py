"""Citation check: every date and number in a draft must appear in the passage(s) it cites.

Runs in code (no model) before a draft reaches the officer. A draft fails when:
  - a figure (number, number+unit, or date) is not found in any passage cited for it;
  - a figure appears with no citation at all;
  - a citation names a passage id that was not retrieved;
  - a figure is stated with a different limit than in its passage: "not deeper than 3 cm" when the
    passage says "recommended depth = 3 cm; not deeper than 5 cm" (a flipped bound), or a plain
    "5 cm" when the passage gives 5 cm only as a maximum;
  - code detected a conflict between sources, but the draft does not attribute each source's
    figure to that source alone (i.e. it merged or hid the disagreement).

Limits are detected from a small fixed list of bound words next to the number (see BOUND WORDS
below). Anything else about meaning (a sentence with no figure, or a figure whose surrounding words
change what it means in other ways) is NOT checked; that stays the officer's job.

How figures are attached to citations: the text between one citation bracket and the next is
the "segment" for the later bracket, so "... 9 out of 10 pods ... [A]." checks 9 and 10 against
passage A. Brackets separated only by spaces/punctuation ("[A] [B]" or "[A, B]") are one
combined citation. Figures after the last bracket must appear in some passage cited in the draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]
_MON = {m: m for m in MONTHS} | {m[:3]: m for m in MONTHS} | {"sept": "september"}
QUALIFIERS = {"early": "early", "mid": "mid", "middle": "mid", "late": "late", "end": "late", "beginning": "early",
              "start": "early"}
UNITS = {"cm": "cm", "centimetre": "cm", "centimetres": "cm", "centimeter": "cm", "centimeters": "cm",
         "mm": "mm", "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
         "kg": "kg", "kgs": "kg", "kilogram": "kg", "kilograms": "kg", "g": "g", "grams": "g",
         "ha": "ha", "hectare": "ha", "hectares": "ha", "acre": "acre", "acres": "acre",
         "week": "week", "weeks": "week", "day": "day", "days": "day", "month": "month", "months": "month",
         "%": "%", "percent": "%", "per cent": "%", "l": "l", "litre": "l", "litres": "l", "liter": "l", "liters": "l"}
WORD_NUMS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
             "fifty": 50, "sixty": 60, "hundred": 100}
# Number words that count sources/passages are meta-talk, not advice figures ("one source says").
META_NOUNS = r"(?:sources?|passages?|guides?|documents?|references?|studies|study|options?|ways?|of\s+(?:them|the|these))"
CITE_RE = re.compile(r"\[([^\[\]]+)\]")

_unit_alt = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
_month_alt = "|".join(sorted(_MON, key=len, reverse=True))
_qual_alt = "|".join(QUALIFIERS)
NUM = r"\d+(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?"
DATE_RE = re.compile(
    rf"(?:(?P<q1>{_qual_alt})(?:[\s-]+of)?[\s-]+(?P<m1>{_month_alt})\b)"            # mid-June, end of July
    rf"|(?:(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:\s+of)?\s+(?P<m2>{_month_alt})\b)"      # 15 March, 15th of March
    rf"|(?:\b(?P<m3>{_month_alt})\.?\s+(?P<d3>\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*(?:{_unit_alt})\b))"  # March 15
    rf"|(?:\b(?P<m4>{_month_alt})\b)", re.I)
NUMBER_RE = re.compile(rf"(?<![\w.])(?P<n>{NUM})\s*(?P<u>(?:{_unit_alt})(?![a-z]))?", re.I)
WORDNUM_RE = re.compile(rf"\b(?P<w>{'|'.join(WORD_NUMS)})\b(?!\s+{META_NOUNS}\b)\s*(?P<u>(?:{_unit_alt})(?![a-z]))?", re.I)
RANGE_GLUE = re.compile(r"^\s*(?:to|-|–|—|and|or)\s*$", re.I)

# --- BOUND WORDS -------------------------------------------------------------------------------------------
# A number can be stated as a plain value ("3 cm"), an upper limit ("up to 5 cm", "not deeper than 5 cm") or
# a lower limit ("at least 50 kg", "no less than 50 kg"). The limit is part of the figure's identity, so a draft
# that turns a maximum into a recommendation or swaps two bounds fails like a wrong number would.
MAX, MIN = "max", "min"
_GREATER = r"more|deeper|higher|greater|longer|later|larger|wider|heavier|bigger"
_LESS = r"less|fewer|shallower|lower|shorter|earlier|smaller|narrower|lighter"
_FIXED_BOUND = [
    (re.compile(r"\b(?:up\s+to|at\s+(?:the\s+)?most|(?:a\s+)?maximum(?:\s+of)?|max\.?)\s*$", re.I), MAX),
    (re.compile(r"\b(?:at\s+(?:the\s+)?least|(?:a\s+)?minimum(?:\s+of)?|min\.?)\s*$", re.I), MIN),
]
_COMPARATIVE = re.compile(rf"\b(?:(?P<g>(?:{_GREATER})\s+than|over|above|exceeding)"
                          rf"|(?P<l>(?:{_LESS})\s+than|under|below))\s*$", re.I)
# A negation up to two words before the comparative flips it: "not deeper than", "do not plant deeper than".
_NEGATION = re.compile(r"\b(?:not|no|never|avoid|avoiding|don't|without)(?:\s+\w+){0,2}\s*$", re.I)
_SUFFIX_BOUND = [
    (re.compile(rf"^\s*(?:or|and)\s+(?:{_GREATER}|over|above)\b", re.I), MIN),   # "50 kg or more"
    (re.compile(rf"^\s*(?:or|and)\s+(?:{_LESS}|under|below)\b", re.I), MAX),     # "3 weeks or less"
]
_BOUND_WINDOW = 40   # chars before a number searched for bound words; enough for "do not plant deeper than"
_CLAUSE_BREAK = re.compile(r"[;:()\[\]]|\.(?!\d)")
_BOUND_TEXT = {MAX: "an upper limit", MIN: "a lower limit", "": "a plain value"}


def _bound(t: str, start: int, end: int, prev_end: int) -> str:
    """'max', 'min' or '' for the number at t[start:end]. Looks only within the same clause and after the previous
    number, so in "3 cm; not deeper than 5 cm" the bound attaches to 5, not 3."""
    before = _CLAUSE_BREAK.split(t[max(prev_end, start - _BOUND_WINDOW):start])[-1]
    for pat, kind in _FIXED_BOUND:
        if pat.search(before):
            return kind
    m = _COMPARATIVE.search(before)
    if m:
        kind = MIN if m.group("g") else MAX
        if _NEGATION.search(before[:m.start()]):
            kind = MAX if kind == MIN else MIN
        return kind
    for pat, kind in _SUFFIX_BOUND:
        if pat.search(t[end:end + _BOUND_WINDOW]):
            return kind
    return ""


@dataclass(frozen=True)
class Figure:
    kind: str          # "number" or "date"
    value: str         # normalised: "1000", "2.5", "mid july", "15 march", "july"
    unit: str = ""     # normalised unit for numbers, "" if none
    raw: str = ""
    bound: str = ""    # numbers only: MAX ("up to 5 cm"), MIN ("at least 50 kg") or "" for a plain value

    def label(self) -> str:
        return self.raw or (f"{self.value} {self.unit}".strip())


@dataclass
class CheckResult:
    ok: bool
    problems: list[str] = field(default_factory=list)
    checked: int = 0

    def summary(self) -> str:
        return "passed" if self.ok else "; ".join(self.problems)


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def extract_figures(text: str) -> list[Figure]:
    """All numbers (with units) and dates in text. Dates consume their day number."""
    t = text.replace("\u2013", "-").replace("\u2014", "-")
    figs: list[tuple[int, Figure]] = []
    taken: list[tuple[int, int]] = []
    for m in DATE_RE.finditer(t):
        g = m.groupdict()
        if g["m1"]:
            month, val = _MON[g["m1"].lower()], f"{QUALIFIERS[g['q1'].lower()]} {_MON[g['m1'].lower()]}"
        elif g["m2"]:
            month, val = _MON[g["m2"].lower()], f"{int(g['d2'])} {_MON[g['m2'].lower()]}"
        elif g["m3"]:
            month, val = _MON[g["m3"].lower()], f"{int(g['d3'])} {_MON[g['m3'].lower()]}"
        else:
            word = g["m4"]
            month = _MON[word.lower()]
            # "may" is usually the verb; "mar"/"jun" etc. abbreviations alone are too noisy.
            if word.lower() == "may" and not word[0].isupper():
                continue
            if word.lower() == "may" and m.start() > 0 and not re.search(r"(?:in|from|by|until|before|after|of|to|and|-)\s*$", t[:m.start()], re.I):
                continue
            if len(word) < 4 and word.lower() not in MONTHS:
                continue
            val = month
        figs.append((m.start(), Figure("date", val, raw=m.group(0).strip())))
        taken.append(m.span())
    inside = lambda pos: any(a <= pos < b for a, b in taken)
    nums: list[tuple[int, int, Figure]] = []
    for m in NUMBER_RE.finditer(t):
        if inside(m.start()):
            continue
        unit = UNITS.get((m.group("u") or "").lower().strip(), "")
        nums.append((m.start(), m.end(), Figure("number", _norm_num(m.group("n")), unit, m.group(0).strip())))
    for m in WORDNUM_RE.finditer(t):
        if inside(m.start()):
            continue
        unit = UNITS.get((m.group("u") or "").lower().strip(), "")
        nums.append((m.start(), m.end(), Figure("number", str(WORD_NUMS[m.group("w").lower()]), unit, m.group(0).strip())))
    nums.sort(key=lambda x: x[0])
    # Ranges: "50 to 60 kg", "40 - 45 kg", "2 to 3 weeks" -> the first number inherits the unit.
    for i in range(len(nums) - 2, -1, -1):
        s, e, f = nums[i]
        ns, _, nf = nums[i + 1]
        if not f.unit and nf.unit and RANGE_GLUE.match(t[e:ns]):
            nums[i] = (s, e, Figure(f.kind, f.value, nf.unit, f.raw))
    prev_end = 0
    for i, (s, e, f) in enumerate(nums):
        nums[i] = (s, e, Figure(f.kind, f.value, f.unit, f.raw, _bound(t, s, e, prev_end)))
        prev_end = e
    figs += [(s, f) for s, _, f in nums]
    figs.sort(key=lambda x: x[0])
    return [f for _, f in figs]


def _same_number(f: Figure, p: Figure) -> bool:
    return p.value == f.value and (not f.unit or not p.unit or f.unit == p.unit)


def _matches(f: Figure, pool: list[Figure]) -> bool:
    for p in pool:
        if p.kind != f.kind:
            continue
        if f.kind == "number" and _same_number(f, p) and p.bound == f.bound:
            return True
        if f.kind == "date":
            if p.value == f.value:
                return True
            if " " not in f.value and p.value.split()[-1] == f.value:  # bare "July" vs "late July"
                return True
    return False


def _mismatch(f: Figure, pool: list[Figure], where: str) -> str:
    """Problem text for a figure that did not match; names a wrong limit separately so the regeneration
    feedback tells the model exactly what to fix."""
    limits = sorted({p.bound for p in pool if p.kind == "number" and f.kind == "number" and _same_number(f, p)})
    if limits:
        given = " or ".join(_BOUND_TEXT[b] for b in limits)
        return (f"'{f.label()}' states {f.value} {f.unit}".rstrip() + f" as {_BOUND_TEXT[f.bound]}, but {where} "
                f"give(s) it as {given}")
    return f"'{f.label()}' is not in {where}"


def _split_ids(inner: str) -> list[str]:
    return [x.strip() for x in re.split(r"[,;]|\s+and\s+", inner) if x.strip()]


def segments(draft: str) -> tuple[list[tuple[str, list[str]]], str]:
    """Return ([(segment_text, cited_ids)], trailing_text). Adjacent brackets merge into one citation."""
    out: list[tuple[str, list[str]]] = []
    pos, pending_text, pending_ids = 0, None, []
    for m in CITE_RE.finditer(draft):
        between = draft[pos:m.start()]
        ids = _split_ids(m.group(1))
        if pending_text is not None and re.fullmatch(r"[\s,;.]*", between):
            pending_ids += ids
        else:
            if pending_text is not None:
                out.append((pending_text, pending_ids))
            pending_text, pending_ids = between, ids
        pos = m.end()
    if pending_text is not None:
        out.append((pending_text, pending_ids))
    return out, draft[pos:]


def check_draft(draft: str, passages: list[dict], conflicts: dict[str, list[dict]] | None = None,
                ignore_prefixes: tuple[str, ...] = ()) -> CheckResult:
    """Check `draft` against the retrieved `passages` (dicts with 'id' and 'text').

    conflicts: claim_key -> passages from different sources that disagree; each source's figure must be
    attributed to that source alone somewhere in the draft.
    ignore_prefixes: lines starting with these (e.g. system notes) are not advice and are skipped.
    """
    if ignore_prefixes:
        draft = "\n".join(l for l in draft.splitlines() if not l.strip().startswith(ignore_prefixes))
    by_id = {p["id"]: p for p in passages}
    figs_of = {pid: extract_figures(p["text"]) for pid, p in by_id.items()}
    problems: list[str] = []
    checked = 0
    segs, trailing = segments(draft)
    cited_all: set[str] = set()
    for text, ids in segs:
        unknown = [i for i in ids if i not in by_id]
        problems += [f"cites unknown passage [{i}]" for i in unknown]
        known = [i for i in ids if i in by_id]
        cited_all.update(known)
        pool = [f for i in known for f in figs_of[i]]
        for f in extract_figures(text):
            checked += 1
            if not _matches(f, pool):
                problems.append(_mismatch(f, pool, f"the cited passage(s) {known or ids}"))
    trailing_figs = extract_figures(trailing)
    if trailing_figs:
        pool = [f for i in cited_all for f in figs_of[i]]
        for f in trailing_figs:
            checked += 1
            if not segs:
                problems.append(f"'{f.label()}' has no citation")
            elif not _matches(f, pool):
                problems.append(_mismatch(f, pool, "any cited passage") + " (uncited, after the last citation)")
    for key, group in (conflicts or {}).items():
        sources = {p["source_id"] for p in group}
        for p in group:
            others = {q["id"] for q in group if q["source_id"] != p["source_id"]}
            own = figs_of.get(p["id"]) or extract_figures(p["text"])
            ok = False
            for text, ids in segs:
                if p["id"] in ids and not (set(ids) & others):
                    seg_figs = extract_figures(text)
                    if not own or any(_matches(f, own) for f in seg_figs):
                        ok = True
                        break
            if not ok:
                problems.append(f"conflict on {key.replace('_', ' ')} ({', '.join(sorted(sources))}) is not shown: "
                                f"[{p['id']}]'s own figure is not stated with its own citation")
    return CheckResult(ok=not problems, problems=list(dict.fromkeys(problems)), checked=checked)
