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
import sys
from dataclasses import dataclass, field

from agrireach import citation_check, llm

MAX_CHARS = 600   # about 100 words: one WhatsApp screen, under a minute spoken
CITE_RE = citation_check.CITE_RE
OFFICER_RE = re.compile(r"\b(?:the\s+)?(?:extension\s+)?(?:officer|officers|aea)\b(?!\s*(?:\.|,|$))", re.I)
# "Agriculture Extension Agent (AEA)" is the same referral as "Agricultural ..." (F1 live, run3: the rule rewrite dropped
# the pesticide safety line because the leftover "(AEA)" read as an officer instruction).
ALLOWED_OFFICER = re.compile(r"\b(?:your|an|a|local)\s+(?:local\s+)?(?:agricultur(?:al|e)\s+)?extension\s+(?:officer|agent)"
                             r"(?:\s*\(AEA\))?|\b(?:your\s+local|your|local)\s+AEA\b", re.I)
# A pesticide or spraying line in the officer text is a safety line: the farmer text must keep one (F1 dropped it).
SAFETY_RE = re.compile(r"\b(?:pesticides?|insecticides?|herbicides?|fungicides?|spray(?:s|ing)?)\b", re.I)
SUPPORTED_LANGUAGES = {"en"}
PROMPT = (
    "Rewrite this advice for the farmer who asked the question. It was written for an extension officer. "
    "Write directly to the farmer ('you'), in simple English, at most 80 words, no citations or brackets, no "
    "markdown, no lists. Keep every instruction and every number and date exactly as written; add nothing new and do "
    "not add reassurance. Always keep any line about pesticides or spraying. Leave out notes meant only for the officer. Only if the user message says SOURCES DIFFER: "
    "yes, give each option and end with 'Your extension officer will confirm which to follow.'; otherwise never "
    "write that sentence. Reply with the message only."
)


# A quoted planting-window table row: "Major season | Transition | Mid-March-end of April" [MOFA-MAIZE:p11-...]
ROW_RE = re.compile(r'^"?(Major|Minor)(?:\s+cropping)?\s+season\s*\|\s*([^|]+?)\s*\|\s*([^|"]+?)"?\s*'
                    r'\[([A-Z0-9][A-Z0-9-]*):[^\]]*\]', re.I)
SOURCE_NAMES = {"MOFA": "MoFA", "IITA": "IITA", "APNI": "APNI"}
CONFIRM = "Your extension officer will confirm which to follow."
# Regulatory limits (aflatoxin in ppb) are for the officer: a farmer can't measure them, and a quoted limit reads as
# "safe below this". They stay in the officer draft and never go into the farmer text.
LIMIT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:ppb|ppm|µg\s*/\s*kg|ug\s*/\s*kg|mg\s*/\s*kg)\b|\bparts\s+per\s+(?:billion|million)\b",
                      re.I)


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
    # How the proposal was made, for the audit log (tool_log 'farmer_text_proposal', see audit_entry()): path
    # model | rule | officer, model SMS rejection reasons or error, sentences dropped to fit, safety line source.
    audit: dict = field(default_factory=dict)


def sms_length_problem(text: str) -> str | None:
    """The SMS limit the approval endpoint enforces (sms.length_prompt: SMS_MAX_SEGMENTS parts, by default 612 GSM-7
    characters, or 268 if any character needs Unicode), measured on the text as proposed (plain punctuation). Using
    the same function means a proposed text can't be refused with a 400 at approval for length."""
    from agrireach.channels import sms
    return sms.length_prompt(plain_punctuation(text))


def check(text: str, officer_text: str) -> list[str]:
    """Problems with a farmer-facing text; empty if it can be proposed as is."""
    out = []
    if CITE_RE.search(text) or "[" in text:
        out.append("contains citation brackets")
    if "|" in text:
        out.append("contains a raw table row ('|'): write it as a sentence")
    if OFFICER_RE.search(ALLOWED_OFFICER.sub("", text)):
        out.append("still addresses the officer")
    if LIMIT_RE.search(text):
        out.append("quotes a regulatory limit (ppb) a farmer can't measure: keep it in the officer notes")
    if not SAFETY_RE.search(text) and any(SAFETY_RE.search(l) for l in officer_text.splitlines()
                                          if not l.strip().startswith(("Note:", "Caution:"))):
        out.append("drops the pesticide safety line: keep the officer text's line on pesticides or spraying")
    if len(text) > MAX_CHARS:
        out.append(f"{len(text)} characters, over {MAX_CHARS}")
    if p := sms_length_problem(text):
        out.append(p)
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


# A full stop after one of these, or one followed by "(Source)", does not end a sentence: "early Sept. (MoFA)."
_ABBREV = r"(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec|approx|e\.g|i\.e|No|St|Dr)\."


def _sentences(text: str) -> list[str]:
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out: list[str] = []
    for s in parts:
        if out and (s.startswith("(") or (re.search(rf"\b{_ABBREV}$", out[-1]) and not s[:1].isupper())):
            out[-1] += " " + s
        else:
            out.append(s)
    return out


# Saying the system doesn't know is not a claim that needs a source.
NO_CLAIM_RE = re.compile(r"^(?:i\s+(?:do\s+not|don't|don\u2019t)\s+know|i\s+am\s+not\s+sure|i'm\s+not\s+sure)\s*[.!]?$", re.I)


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
            if LIMIT_RE.search(s) or s[:1].islower():
                continue  # a regulatory limit, or a verbatim mid-sentence excerpt: not something to text a farmer
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
    # Safety lines (pesticides, spraying) go right after the planting rows so the length limit never cuts them.
    keep = [s for s in keep if SAFETY_RE.search(s)] + [s for s in keep if not SAFETY_RE.search(s)]
    out = ""
    for s in rows + keep:
        if len(out) + len(s) + 1 > max_chars:
            break
        out = f"{out} {s}".strip()
    return out


def ensure_safety_line(text: str, passages: list[dict] | None, caveat: dict | None = None,
                       fit: bool = False, audit: dict | None = None) -> tuple[str, list[str]]:
    """The pesticide safety guarantee, applied when the farmer text is proposed (never at approval or send: the
    officer approves, and may edit, the exact text that is sent).

    Why it exists: F1 lost the safety line from the farmer SMS three different ways in live runs, each a different
    wording, so patching wordings did not hold. a5e9192 run 2: the late-timing check flagged "worms are still a
    problem" and the rule fallback dropped "Agriculture Extension Agent (AEA)". cc7cf4c B1: the faithful model SMS was
    723 characters (over the limit) and the rule fallback dropped "the officer should consult the local AEA ...
    pesticide" as an officer instruction (docs/live-eval-2026-10-25-run4.md).

    When a case passage carries a pesticide safety sentence (SAFETY_RE; a referral to the AEA is preferred), that
    sentence goes word for word, with its source named like the planting rows ("(APNI)"), right after the zone caveat
    and before the advice. It is never reworded or shortened.
    fit=False (model text): nothing is dropped; dropping trailing model sentences can leave half a piece of advice, so
    a model text that no longer fits is rejected by check() and the rule path is used.
    fit=True (rule text, which is built sentence by sentence): advice sentences are dropped whole from the end until
    the text fits MAX_CHARS and the approval endpoint's SMS limit (sms_length_problem); the caveat, the safety line
    and the sources-differ sentence are never dropped, and every dropped sentence is named in the officer note. If it
    still can't fit, the text is "" with a note: no SMS is proposed and the officer writes it.
    The rainfall record is never a source. Returns (text, notes for the officer); `audit`, if given, gets the
    dropped sentences and the safety line's source."""
    line = src = None
    for p in passages or []:
        pid = str(p.get("id", "")) if p else ""
        if not p or pid.startswith("RAINFALL-"):
            continue
        cands = [s for s in _sentences(p.get("text") or "") if SAFETY_RE.search(s) and not LIMIT_RE.search(s)
                 and not OFFICER_RE.search(ALLOWED_OFFICER.sub("", s))]
        cands.sort(key=lambda s: not ALLOWED_OFFICER.search(s))  # "consult your local AEA" is the safety advice
        if cands:
            src = SOURCE_NAMES.get(pid.split("-")[0], pid.split(":")[0])
            line = f"{re.sub(r'[.!?]+$', '', cands[0])} ({src})."
            break
    if audit is not None:
        audit.update(dropped=[], safety_line=src)
    if not text or (not line and not fit):
        return text, []  # no proposal (the officer writes the text), or nothing to guarantee or fit
    head = [caveat["sentence"]] if caveat and text.startswith(caveat["sentence"]) else []

    def key(s: str) -> str:  # the same sentence with or without its "(Source)" name
        return re.sub(r"\W+", " ", re.sub(r"\s*\([^)]*\)\s*[.!?]*$", "", s)).strip().lower()
    body = [s for s in _sentences(text[len(head[0]) if head else 0:].strip()) if not line or key(s) != key(line)]
    tail = [s for s in body if s == CONFIRM]
    body = [s for s in body if s != CONFIRM]
    join = lambda b: " ".join([*head, *([line] if line else []), *b, *tail])  # noqa: E731
    fits = lambda t: len(t) <= MAX_CHARS and not sms_length_problem(t)  # noqa: E731
    dropped: list[str] = []
    while fit and body and not fits(join(body)):
        dropped.insert(0, body.pop())
    out, notes = join(body), []
    if audit is not None:
        audit["dropped"] = list(dropped)
    if fit and (not fits(out) or not (body or line)):  # caveat + safety line alone is still worth proposing
        why = (f"the cited source's pesticide sentence ({src}) does not fit" if line else "no advice sentence fits")
        return "", [f"{why} within the length limit ({MAX_CHARS} characters, and the approval part limit) with the caveat; "
                    "it is never shortened, so no SMS is proposed: the officer must write the farmer text"]
    if line and out != text:
        notes.append(f"the cited source's pesticide sentence ({src}) was put first after any caveat, word for word")
    if dropped:
        notes.append(f"{len(dropped)} advice sentence(s) dropped to fit the length limit; check the reply still makes "
                     "sense: " + "; ".join(f"'{d}'" for d in dropped))
    return out, notes


def _llm_rewrite(officer_text: str, question: str, conflicts: bool = False) -> tuple[str, str]:
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    r = llm.create(
        "farmer_text", os.environ["LLM_MODEL"], client, temperature=0,
        extra_body=llm.extra_body(os.environ["LLM_BASE_URL"]),
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
    sents = [s for s in _sentences(text) if s not in fixed and re.search(r"[A-Za-z]{3}", s) and not NO_CLAIM_RE.match(s)]
    if not sents:
        return []
    # The rainfall record is officer-only (a model estimate, not a gauge reading): never a source for farmer text.
    passages = [p for p in passages if p and p.get("text") and not str(p.get("id", "")).startswith("RAINFALL-")]
    if not passages:
        return [f"'{s[:80]}' has no source behind it: the case cites no passage" for s in sents]
    ids = ", ".join(p["id"] for p in passages)
    draft = "\n".join(re.sub(r"([.!?]*)$", lambda m: f" [{ids}]{m.group(1) or '.'}", s, count=1) for s in sents)
    out = list(citation_check.check_draft(draft, passages).problems)
    out += claim_check.check_claims(draft, passages, judge=True, judge_call=judge_call).problems
    return list(dict.fromkeys(out))


# Typographic punctuation outside the GSM-7 SMS alphabet: one curly apostrophe switches the whole SMS to Unicode
# (67 characters a part instead of 153). Proposed text uses the plain equivalents; officer edits are left alone.
_PLAIN = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201c": '"', "\u201d": '"', "\u201e": '"',
                        "\u2013": "-", "\u2014": "-", "\u2026": "...", "\u00a0": " "})


def plain_punctuation(text: str) -> str:
    return text.translate(_PLAIN)


def propose(officer_text: str, question: str = "", language: str = "en", conflicts: bool = False,
            zone_caveat: dict | None = None, passages: list[dict] | None = None) -> FarmerDraft:
    """passages: the case's sources. When given, a model-written SMS must pass sms_claims or it is replaced by the
    rule-based version (fail closed)."""
    audit: dict = {"model_rejected": [], "model_error": None, "dropped": [], "safety_line": None}
    fd = _propose(officer_text, question, language, conflicts, zone_caveat, passages, audit)
    fd.zone_caveat = zone_caveat
    fd.text = plain_punctuation(fd.text)
    fd.audit = audit | {"mode": fd.mode, "path": "officer" if not fd.text else
                        "model" if fd.mode.startswith("llm") else "rule", "chars": len(fd.text)}
    return fd


def audit_entry(fd: FarmerDraft) -> tuple[dict, str]:
    """(args, summary) for the tool_log 'farmer_text_proposal' entry: why the farmer text is what it is (run 5: an
    auditor reading only the log couldn't see why a model SMS was replaced by the rule text)."""
    a = fd.audit
    why = []
    if a.get("model_rejected"):
        why.append("model SMS rejected: " + "; ".join(a["model_rejected"]))
    if a.get("model_error"):
        why.append(f"model SMS failed: {a['model_error']}")
    if a.get("dropped"):
        why.append(f"{len(a['dropped'])} sentence(s) dropped to fit: " + "; ".join(f"'{d}'" for d in a["dropped"]))
    head = {"model": "model SMS proposed", "rule": "rule-based text proposed",
            "officer": "no text proposed: the officer must write it"}[a.get("path", "officer")]
    return a, ". ".join([head] + why)


def _propose(officer_text: str, question: str, language: str, conflicts: bool, caveat: dict | None,
             passages: list[dict] | None, audit: dict) -> FarmerDraft:
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
            # Before the checks: a model SMS is never trimmed, so if it no longer fits with the line, check() rejects
            # it and the rule path is used.
            text, safety = ensure_safety_line(text, passages, caveat, audit=audit)
            problems = check(text, officer_text) if text else safety
            if not problems and passages is not None:
                problems = sms_claims(text, passages, caveat=caveat)
            if not problems:
                return FarmerDraft(text, mode, notes + safety)
            audit["model_rejected"] = list(problems)
            notes.append(f"model rewrite rejected ({'; '.join(problems)}); rule-based version shown")
        except Exception as e:
            audit["model_error"] = f"{type(e).__name__}: {e}"[:300]
            notes.append(f"model rewrite failed ({type(e).__name__}); rule-based version shown")
    # No length cut here: ensure_safety_line(fit=True) drops whole sentences to fit and names them for the officer.
    text = rule_rewrite(officer_text, sys.maxsize)
    if conflicts and text and CONFIRM not in text:
        # The options are listed with their sources; never present them as if they agree.
        text = f"{text} {CONFIRM}"
    text = lead + text if text else text
    text, safety = ensure_safety_line(text, passages, caveat, fit=True, audit=audit)
    if not text:
        return FarmerDraft("", "rule", notes + (safety or ["nothing farmer-facing left after removing officer notes; "
                                                           "the officer must write it"]), needs_officer_text=True)
    return FarmerDraft(text, "rule", notes + safety + check(text, officer_text))
