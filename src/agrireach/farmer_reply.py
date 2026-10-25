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


@dataclass
class FarmerDraft:
    text: str
    mode: str                       # llm:<model> | rule | none
    problems: list[str] = field(default_factory=list)  # shown to the officer next to the proposal
    needs_officer_text: bool = False
    language: str = "en"


def check(text: str, officer_text: str) -> list[str]:
    """Problems with a farmer-facing text; empty if it can be proposed as is."""
    out = []
    if CITE_RE.search(text) or "[" in text:
        out.append("contains citation brackets")
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


def rule_rewrite(officer_text: str) -> str:
    """Deterministic plain version: drop notes and officer-only lines, strip citations, address the farmer."""
    keep = []
    for line in officer_text.splitlines():
        l = line.strip()
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
    for s in keep:
        if len(out) + len(s) + 1 > MAX_CHARS:
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


def propose(officer_text: str, question: str = "", language: str = "en", conflicts: bool = False) -> FarmerDraft:
    if language not in SUPPORTED_LANGUAGES:
        return FarmerDraft("", "none", [f"the farmer wrote in {language}; AgriReach can't write farmer text in that "
                                        "language, so the officer must write it"], needs_officer_text=True,
                           language=language)
    if not officer_text.strip():
        return FarmerDraft("", "none", ["no officer text yet"], needs_officer_text=True)
    notes = ["sources differ: edit to keep only the option you choose"] if conflicts else []
    if llm.mode() == "llm" and not officer_text.startswith(llm.STUB_LABEL):
        try:
            text, mode = _llm_rewrite(officer_text, question, conflicts)
            problems = check(text, officer_text)
            if not problems:
                return FarmerDraft(text, mode, notes)
            notes.append(f"model rewrite rejected ({'; '.join(problems)}); rule-based version shown")
        except Exception as e:
            notes.append(f"model rewrite failed ({type(e).__name__}); rule-based version shown")
    text = rule_rewrite(officer_text)
    problems = check(text, officer_text)
    if not text:
        return FarmerDraft("", "rule", notes + ["nothing farmer-facing left after removing officer notes; "
                                                "the officer must write it"], needs_officer_text=True)
    return FarmerDraft(text, "rule", notes + problems)
