"""Deterministic safety gate for the exact farmer text, run before any approval.

Lines copied from a cited source pass on provenance. Other lines go through the
three hard stops in instruction_policy plus the chemical-safeguard check (S1);
whatever survives goes to the judge and the officer. A favourable judge verdict never
overrides a hard stop, and the original payload is never normalized for storage or delivery.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

POLICY_VERSION = "chemical-4"
SOURCE_FINGERPRINTS = {'APNI-SARI-2023:weeds-herbicide': '7c089f0dc5fbace588368f1dbef72fea4c00445a0e6c6c4d58d37c68360da91c', 'APNI-SARI-2023-MAIZE:p20-faw-control': 'a54a9501e8bd86701d3823aaea38dd9fbbae8e6eff66985fdcee94ff8077415e', 'APNI-SARI-2023-MAIZE:p22-sacks': '5d7dd431a6b34d46b89760c8ae3709db7b1afdc2937ee845308a5361dd094594'}
CHEMICAL = re.compile(r"\b(?:pesticides?|insecticides?|herbicides?|fungicides?|chemicals?|spray\w*|glyphosate|paraquat)\b", re.I)
PROTECTIVE_RULE = re.compile(r"^(?:wear (?:protective )?gloves\b|(?:never|do not|don't) (?:use|buy) (?:any )?"
                             r"(?:(?:unapproved|unlabelled) (?:pesticides?|chemicals?)|(?:pesticides?|chemicals?) "
                             r"without (?:a |the )?labels?)\b)", re.I)
PERSON = r"(?:AEA|agricultural extension officer|agricultural extension agent|extension officer|extension agent)"
# Fixed lines that always pass: referrals, protective rules and "I don't know".
REFERRALS = {f"{verb} your local {person} {tail}." for verb in ("Consult", "Ask")
             for person in ("AEA", "agricultural extension officer", "agricultural extension agent")
             for tail in ("before choosing or applying a pesticide", "before applying any herbicide",
                          "for advice on the recommended fall army worm control pesticide in your area")}
REFERRALS |= {f"{start} your local {person} {end}." for person in ("AEA", "extension agent", "agricultural extension officer")
              for start, end in (("Talk to", "about which pesticide to use"), ("Ask", "which fall armyworm pesticide to use"))}
PROTECTIVE = {"Do not use unapproved pesticides.", "Do not spray without gloves."}
NO_ADVICE = {"I do not know.", "I am not sure.", "Your extension officer will confirm which to follow.",
             "I do not know which pesticide to recommend."}


def registered_template(text: str) -> bool:
    """Recognize complete verified templates, including permitted attribution."""
    return normalized(text) in {normalized(s) for s in REFERRALS | PROTECTIVE | NO_ADVICE}


TOPICS = {"storage": r"\b(?:stor\w*|sacks?|bags?|grain|bagging|tablets?|postharvest)\b|\bkeep\b.*\bcobs?\b",
          "faw": r"\b(?:faw|army\s?worms?|worms?|holes|infestation)\b", "weeds": r"\b(?:weeds?|weeding|herbicides?)\b"}
SAFEGUARD = {"APNI-SARI-2023:weeds-herbicide": "before applying any herbicide",  # source-specific referral lines
             "APNI-SARI-2023-MAIZE:p20-faw-control": "fall army ?worm"}
SOURCE_TOPICS = {"APNI-SARI-2023:weeds-herbicide": "weeds", "APNI-SARI-2023-MAIZE:p20-faw-control": "faw",
                 "APNI-SARI-2023-MAIZE:p22-sacks": "storage"}


def applicable(passage: dict, question: str, text: str) -> bool:
    """False only for a registered, unchanged source off the question's topic; anything unknown keeps S1 on."""
    topic = SOURCE_TOPICS.get(passage.get("id"))
    if not topic or fingerprint(passage.get("text", "")) != SOURCE_FINGERPRINTS.get(passage.get("id")):
        return True
    context_topics = {k for k, pattern in TOPICS.items() if re.search(pattern, question, re.I)}
    reply_topics = {k for k, pattern in TOPICS.items() if re.search(pattern, text, re.I)}
    return not context_topics or topic in context_topics | reply_topics


def sentences(text: str) -> list[str]:
    """Keep clauses together so appended instructions cannot match a safe template."""
    from agrireach.farmer_reply import _sentences
    return _sentences(text)


def normalized(text: str) -> str:
    """Comparison only: discard a source attribution, never a safety qualifier."""
    text = re.sub(r"\s*\((?:APNI|MoFA|IITA|FAO|WHO)\)\s*[.!]?$", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip().rstrip(".!").casefold()


def fingerprint(value) -> str:
    """Stable SHA256 of canonical UTF8 JSON, including exact text inside strings."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Finding:
    rule_id: str
    sentence: str
    reason: str
    evidence: tuple[str, ...] = ()
    recovery: tuple[str, ...] = ("revise", "reject", "request_info")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Assessment:
    outcome: str = "pass"
    findings: list[Finding] = field(default_factory=list)
    judge_status: str = "not_required"

    def to_dict(self) -> dict:
        return asdict(self)


def assess(text: str, passages: list[dict], *, language: str = "en", question: str = "") -> Assessment:
    """Return pass, review_required or safety_blocked (neither held outcome can be acknowledged)."""
    from agrireach.language import TWI_MARKERS
    from agrireach import instruction_policy

    result = Assessment()
    def add(rule, sentence, reason, evidence=(), *, uncertain=False):
        result.findings.append(Finding(rule, sentence, reason, tuple(evidence)))
        if not uncertain or result.outcome != "safety_blocked":
            result.outcome = "review_required" if uncertain else "safety_blocked"

    if not text or not text.strip():
        add("TEXT", text or "", "Explicit farmer text is required")
        return result
    words = re.findall(r"[^\W\d_]+", text.casefold())
    english_hits = sum(w in {"the", "your", "when", "before", "do", "not", "consult", "use", "harvest", "maize", "pesticide", "to", "is", "at"} for w in words)
    foreign_script = bool(re.search(r"[\u0370-\u052f\u0600-\u06ff\u0900-\u0dff\u3040-\u9fff]", text))
    english = not (sum(w in TWI_MARKERS for w in words) >= 2 or foreign_script or (language != "en" and english_hits < 2))
    if not english:  # held for a reviewer who reads the language; the English rules below cannot read it
        add("LANGUAGE", "", "Language assessment is outside the English policy", uncertain=True)
    source_sentences = {normalized(s) for p in passages for s in sentences(p.get("text", ""))}
    chemical_passages = [p for p in passages if p.get("risk") == "chemical" or CHEMICAL.search(p.get("text", ""))]
    ss = sentences(text)
    referral_sentences = [normalized(s) for s in ss if normalized(s) in {normalized(x) for x in REFERRALS}]
    for p in chemical_passages:
        if not applicable(p, question, text):
            continue
        consultation = [s for s in sentences(p["text"]) if re.search(PERSON, s, re.I)]
        kept = any(normalized(s) == normalized(c) for s in ss for c in consultation)
        if fingerprint(p["text"]) != SOURCE_FINGERPRINTS.get(p["id"]):  # unknown or changed chemical source
            add("S1", "", "Chemical source requires a registered safeguard", [p["id"], p["text"]], uncertain=True)
        elif not (kept or any(re.search(r"before choosing or applying a pesticide|" + SAFEGUARD.get(p["id"], "^$"), s)
                              for s in referral_sentences)):
            required = consultation or ["Consult your local AEA before choosing or applying a pesticide."]
            add("S1", "", "Required safeguard: " + " / ".join(required), [p["id"], *required])
    for s in ss:
        norm = normalized(s)
        if registered_template(s) or norm in source_sentences:
            continue
        reversal = re.search(
            r"\b(?:do not|don't|never|no need to)\s+follow\s+(?:the\s+)?(?:pesticide\s+)?label\b"
            r"|\b(?:do not|don't|never|no need to)\s+wear\s+(?:protective\s+)?gloves\b"
            r"|\bignore\b.*\blabel\b|^spray\b.*\bwithout gloves\b"
            r"|^(?:apply|use|spray|treat)\b.*\bwithout (?:advice|consultation)\b", norm, re.I)
        if reversal or (english and instruction_policy.skips_officer(s)):
            add("S2", s, "Only a plain referral may mention the AEA or extension officer, and label and "
                         "protection advice cannot be reversed. Use the fixed referral line instead.")
            continue
        if instruction_policy.burns_land(s) and not any(instruction_policy.BURN.search(p.get("text", "")) for p in passages):
            add("S4", s, "Burning is not advised without a cited source. Revise or remove this line.", uncertain=True)
            continue
        # S3: unsourced products, doses, repeats, materials and spraying; protective rules may name chemicals.
        harmless = PROTECTIVE_RULE.match(s) or re.search(
            r"\b(?:without|no|not|never|before you)\s+(?:any\s+)?spray\w*|\bspray\w*\s+(?:clean\s+)?water\b|"
            r"\bwhen spraying\b|\badvice on (?:the )?recommended\b", s, re.I)
        repeat = instruction_policy.REPEAT.search(s)
        problem = instruction_policy.unsourced_input(s) or ("repeats an application" if repeat else
            None if harmless or not CHEMICAL.search(s) else "mentions a pesticide or spraying")
        if problem and harmless and not re.search(r"\d|\bit\b|\bthem\b", s):
            problem = None
        if problem:
            add("S3", s, f"This line {problem} and is not in the cited source. Use the source wording, "
                         "name an ordinary material, or remove it.", [p["id"] for p in passages],
                uncertain=not CHEMICAL.search(s))  # unsourced spraying/pesticide advice is blocked outright
        else:
            result.judge_status = "required"
    return result
