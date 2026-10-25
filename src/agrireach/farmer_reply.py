"""Farmer-facing version of an answer: what is actually sent to the farmer (WhatsApp text, voice note, /farmer view).

The officer draft is written FOR the officer ("the officer should advise...", citation brackets, notes). The farmer
version is plain text addressed to the farmer, without citations, short enough for one WhatsApp message or a short
voice note. AgriReach proposes it; the officer sees it, can edit it, and approves that exact text (db.officer_decide
farmer_text). Nothing else is delivered.

Proposal: the drafting model rewrites the officer draft when one is configured, else a deterministic rewrite. Either
way the result is checked in code (check()): no citation brackets, no officer-facing wording, no figure that is not in
the officer text, at most MAX_CHARS. A model rewrite that fails the check is replaced by the deterministic one.
Only English is supported. For a Twi (or other unsupported language) question no proposal is made: the officer
writes the farmer text in the farmer's language.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from agrireach import citation_check, llm

MAX_CHARS = 600   # about 100 words: one WhatsApp screen, under a minute spoken
CITE_RE = citation_check.CITE_RE
OFFICER_RE = re.compile(r"\b(?:the\s+)?(?:extension\s+)?(?:officer|officers|aea)\b(?!\s*(?:\.|,|$))", re.I)
ALLOWED_OFFICER = re.compile(r"\b(?:your|an|a|local)\s+(?:local\s+)?(?:agricultural\s+)?extension\s+(?:officer|agent)"
                             r"(?:\s*\(AEA\))?", re.I)
SUPPORTED_LANGUAGES = {"en"}
PROMPT = (
    "Rewrite this advice for the farmer who asked the question. It was written for an extension officer. "
    "Write directly to the farmer ('you'), in simple English, at most 80 words, no citations or brackets, no "
    "markdown, no lists. Keep every instruction and every number and date exactly as written; add nothing new and do "
    "not add reassurance. Leave out notes meant only for the officer. Only if the user message says SOURCES DIFFER: "
    "yes, give each option and end with 'Your extension officer will confirm which to follow.'; otherwise never "
    "write that sentence. Reply with the message only."
)


# A quoted planting-window table row: "Major season | Transition | Mid-March-end of April" [MOFA-MAIZE:p11-...]
ROW_RE = re.compile(r'^"?(Major|Minor)(?:\s+cropping)?\s+season\s*\|\s*([^|]+?)\s*\|\s*([^|"]+?)"?\s*'
                    r'\[([A-Z0-9][A-Z0-9-]*):[^\]]*\]', re.I)
SOURCE_NAMES = {"MOFA": "MoFA", "IITA": "IITA", "APNI": "APNI"}
CONFIRM = "Your extension officer will confirm which to follow."


def _zone_words(cell: str) -> str:
    c = re.sub(r"\bcostal\b", "coastal", cell.strip(), flags=re.I)  # IITA's table spells it "Costal"
    if "/" in c:  # "Guinea/Sudan savannah"
        a, b = c.split("/", 1)
        return f"the {a.strip()} and {b.strip()} zones"
    low = c.lower()
    return f"the {c if low.startswith(('guinea', 'sudan')) else low} zone"


def _lower1(s: str) -> str:
    return s[:1].lower() + s[1:]


def row_sentence(line: str) -> str | None:
    """Plain sentence for a quoted planting-window row, naming its source; None if the line is not one.
    The period's own words are kept (only the first letter lowered); the officer view keeps the verbatim row."""
    m = ROW_RE.match(line.strip())
    if not m:
        return None
    season, zone, period, sid = m.groups()
    parts = period.split(" - ", 1) if " - " in period else \
        re.split(r"-(?=(?:end|early|mid)\b)", period, maxsplit=1, flags=re.I)
    when = f"from {_lower1(parts[0].strip())} to {_lower1(parts[1].strip())}" if len(parts) == 2 else \
        f"in {_lower1(period.strip())}"
    crop = "maize" if "MAIZE" in sid else "the crop"
    src = SOURCE_NAMES.get(sid.split("-")[0], sid)
    return f"In {_zone_words(zone)}, plant {season.lower()}-season {crop} {when} ({src})."


@dataclass
class FarmerDraft:
    text: str
    mode: str                       # llm:<model> | rule | none
    problems: list[str] = field(default_factory=list)  # shown to the officer next to the proposal
    needs_officer_text: bool = False
    language: str = "en"
    zone_caveat: dict | None = None  # set when the guidance is for another zone; see zone_caveat()


def check(text: str, officer_text: str) -> list[str]:
    """Problems with a farmer-facing text; empty if it can be proposed as is."""
    out = []
    if CITE_RE.search(text) or "[" in text:
        out.append("contains citation brackets")
    if "|" in text:
        out.append("contains a raw table row ('|'): write it as a sentence")
    if OFFICER_RE.search(ALLOWED_OFFICER.sub("", text)):
        out.append("still addresses the officer")
    if len(text) > MAX_CHARS:
        out.append(f"{len(text)} characters, over {MAX_CHARS}")
    pool = citation_check.extract_figures(CITE_RE.sub(" ", officer_text))
    for f in citation_check.extract_figures(text):
        if not citation_check._matches(f, pool):
            out.append(f"'{f.raw}' is not in the officer text")
    return out


_OPENERS = [
    (r"^(?:The\s+)?(?:extension\s+)?officer\s+(?:should|can|could|may|must)\s+(?:also\s+)?(?:advise|tell|recommend|"
     r"suggest|remind|encourage|ask|inform)\s+(?:the\s+farmer|them|him|her)\s+(?:to\s+|that\s+)?", ""),
    (r"^(?:The\s+)?(?:extension\s+)?officer\s+(?:should|can|could|may)\s+(?:also\s+)?(?:recommend|suggest)\s+", "Try "),
    (r"^Advise\s+the\s+farmer\s+(?:to\s+|that\s+)?", ""),
    (r"^(?:The\s+)?farmer\s+should\s+", "You should "),
]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def rule_rewrite(officer_text: str, max_chars: int = MAX_CHARS) -> str:
    """Deterministic plain version: drop notes and officer-only lines, strip citations, address the farmer.
    Planting-window table rows become plain sentences naming their source, and come first."""
    rows, keep = [], []
    for line in officer_text.splitlines():
        l = line.strip()
        if "[RAINFALL-" in l:
            continue  # the rainfall record is an input for the officer, not advice for the farmer
        sent = row_sentence(re.sub(r"^[-*•]\s+", "", l))
        if sent:
            if sent not in rows:
                rows.append(sent)
            continue
        if not l or l.startswith(("Note:", "Caution:", llm.STUB_LABEL, "What the curated sources say")) or \
                l.endswith(":") or l.startswith("**Advice for"):
            continue
        l = re.sub(r"^[-*•]\s+|^\d+\.\s+", "", l)
        l = CITE_RE.sub("", re.sub(r"\*\*|__|`", "", l)).strip().strip('"')
        for s in _sentences(l):
            if s.startswith(("Note:", "Caution:")):
                continue  # caveats for the officer; the officer decides whether the farmer needs them
            for pat, rep in _OPENERS:
                # The officer instruction may follow a lead-in clause ("To decide when to harvest, the officer
                # should advise the farmer to ..."): keep only what the farmer is told to do.
                m = re.search(pat.lstrip("^"), s, flags=re.I)
                if m:
                    s2 = rep + s[m.end():]
                    s = s2[:1].upper() + s2[1:]
                    break
            s = re.sub(r"\bthe farmer's\b", "your", s, flags=re.I)
            s = re.sub(r"\bthe farmer\b", "you", s, flags=re.I)
            s = re.sub(r"\s+([.,;:])", r"\1", s)
            if OFFICER_RE.search(ALLOWED_OFFICER.sub("", s)) or re.search(r"\bchoose\b", s, re.I):
                continue  # an instruction to the officer, not advice for the farmer
            if s not in keep:
                keep.append(s)
    out = ""
    for s in rows + keep:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = f"{out} {s}".strip()
    return out


def _llm_rewrite(officer_text: str, question: str, conflicts: bool = False) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    r = client.chat.completions.create(
        model=os.environ["LLM_MODEL"], temperature=0,
        messages=[{"role": "system", "content": PROMPT},
                  {"role": "user", "content": f"Farmer's question: {question}\nSOURCES DIFFER: {'yes' if conflicts else 'no'}\n\n"
                                                    f"Advice for the officer:\n{officer_text}"}])
    return (r.choices[0].message.content or "").strip(), f"llm:{os.environ['LLM_MODEL']}"


def zone_caveat(region: str, where: str = "") -> dict:
    """The farmer-facing caveat for guidance from another agroecological zone. `where` is the zone the passages are
    for ("" means the Northern Ghana guides). Plain words, no figures, and it doesn't address the officer."""
    src = f"the {where} zone" if where else "Northern Ghana"
    return {"region": region.title(), "sources_for": src,
            "sentence": f"This advice comes from guides for {src} and may not suit {region.title()}, so check the "
                        "timing with your local extension agent."}


def caveat_kept(text: str, caveat: dict | None) -> bool:
    """Whether an (officer-edited) farmer text still tells the farmer the guidance may not suit their place."""
    if not caveat:
        return True
    t = text.lower()
    return caveat["sentence"].lower() in t or caveat["region"].lower() in t


def sms_claims(text: str, passages: list[dict], judge_call=None, caveat: dict | None = None) -> list[str]:
    """Problems with the farmer text measured against the case's own passages: every sentence (except the code-built
    caveat and sources-differ sentences) is checked like a cited officer sentence (figures, lexical support, judge)
    against all of them. Fails closed: no passages, or a judge that can't run, is a problem."""
    from agrireach import claim_check

    fixed = {CONFIRM} | ({caveat["sentence"]} if caveat else set())
    sents = [s for s in _sentences(text) if s not in fixed and re.search(r"[A-Za-z]{3}", s)]
    if not sents:
        return []
    passages = [p for p in passages if p and p.get("text")]
    if not passages:
        return [f"'{s[:80]}' has no source behind it: the case cites no passage" for s in sents]
    ids = ", ".join(p["id"] for p in passages)
    draft = "\n".join(re.sub(r"([.!?]*)$", lambda m: f" [{ids}]{m.group(1) or '.'}", s, count=1) for s in sents)
    out = list(citation_check.check_draft(draft, passages).problems)
    out += claim_check.check_claims(draft, passages, judge=True, judge_call=judge_call).problems
    return list(dict.fromkeys(out))


def propose(officer_text: str, question: str = "", language: str = "en", conflicts: bool = False,
            zone_caveat: dict | None = None, passages: list[dict] | None = None) -> FarmerDraft:
    """passages: the case's sources. When given, a model-written SMS must pass sms_claims or it is replaced by the
    rule-based version (fail closed)."""
    fd = _propose(officer_text, question, language, conflicts, zone_caveat, passages)
    fd.zone_caveat = zone_caveat
    return fd


def _propose(officer_text: str, question: str, language: str, conflicts: bool, caveat: dict | None,
             passages: list[dict] | None = None) -> FarmerDraft:
    if language not in SUPPORTED_LANGUAGES:
        return FarmerDraft("", "none", [f"the farmer wrote in {language}; AgriReach can't write farmer text in that "
                                        "language, so the officer must write it"], needs_officer_text=True,
                           language=language)
    if not officer_text.strip():
        return FarmerDraft("", "none", ["no officer text yet"], needs_officer_text=True)
    notes = ["sources differ: edit to keep only the option you choose"] if conflicts else []
    lead = f"{caveat['sentence']} " if caveat else ""
    if caveat:
        notes.append(f"the guidance is from sources for {caveat['sources_for']} and the farmer is in "
                     f"{caveat['region']}: a caveat sentence opens the farmer text; keep it, or adjust the advice, "
                     "before approving")
    elif "cover Northern Ghana only" in officer_text:
        notes.append("the guidance is from Northern Ghana sources and the farmer is elsewhere: say so in the farmer "
                     "text, or adjust it, before approving")
    elif "Caution: some of the guidance below is from sources for the" in officer_text:
        notes.append("some guidance is for another agroecological zone than the farmer's: say so in the farmer text, "
                     "or adjust it, before approving")
    if llm.mode() == "llm" and not officer_text.startswith(llm.STUB_LABEL):
        try:
            text, mode = _llm_rewrite(officer_text, question, conflicts)
            text = lead + text if text and caveat and not caveat_kept(text, caveat) else text
            if conflicts and text and CONFIRM not in text:
                text = f"{text} {CONFIRM}"  # same as the rule-based path: never present the options as agreeing
            problems = check(text, officer_text)
            if not problems and passages is not None:
                problems = sms_claims(text, passages, caveat=caveat)
            if not problems:
                return FarmerDraft(text, mode, notes)
            notes.append(f"model rewrite rejected ({'; '.join(problems)}); rule-based version shown")
        except Exception as e:
            notes.append(f"model rewrite failed ({type(e).__name__}); rule-based version shown")
    text = rule_rewrite(officer_text, MAX_CHARS - len(lead) - (len(CONFIRM) + 1 if conflicts else 0))
    if conflicts and text and CONFIRM not in text:
        # The options are listed with their sources; never present them as if they agree.
        text = f"{text} {CONFIRM}"
    text = lead + text if text else text
    problems = check(text, officer_text)
    if not text:
        return FarmerDraft("", "rule", notes + ["nothing farmer-facing left after removing officer notes; "
                                                "the officer must write it"], needs_officer_text=True)
    return FarmerDraft(text, "rule", notes + problems)
