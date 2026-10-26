"""Bounded English chemical advisory policy, separate from storage and model calls.

Complete sentence matching establishes provenance, not agronomic truth. Unknown
chemical wording is held for review; a positive model verdict cannot override it.
The original payload is never normalized for storage or delivery.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

POLICY_VERSION = "chemical-1"
SOURCE_FINGERPRINTS = {'APNI-SARI-2023:weeds-herbicide': '7c089f0dc5fbace588368f1dbef72fea4c00445a0e6c6c4d58d37c68360da91c', 'APNI-SARI-2023-MAIZE:p20-faw-control': 'a54a9501e8bd86701d3823aaea38dd9fbbae8e6eff66985fdcee94ff8077415e', 'APNI-SARI-2023-MAIZE:p22-sacks': '5d7dd431a6b34d46b89760c8ae3709db7b1afdc2937ee845308a5361dd094594'}
CHEMICAL = re.compile(r"\b(?:pesticides?|insecticides?|herbicides?|fungicides?|chemicals?|spray\w*|glyphosate|paraquat)\b", re.I)
ACTION = re.compile(r"\b(?:apply|use|mix|spray|treat|ignore|consult|ask|wear)\b", re.I)
PERSON = r"(?:AEA|agricultural extension officer|agricultural extension agent|extension officer|extension agent)"
REFERRALS = {
    f"{verb} your local {person} {tail}."
    for verb in ("Consult", "Ask")
    for person in ("AEA", "agricultural extension officer", "agricultural extension agent")
    for tail in ("before choosing or applying a pesticide", "before applying any herbicide",
                 "for advice on the recommended fall army worm control pesticide in your area")
}
PROTECTIVE = {"Do not use unapproved pesticides.", "Do not spray without gloves."}


def sentences(text: str) -> list[str]:
    """Keep clauses together so appended instructions cannot match a safe template."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]


def normalized(text: str) -> str:
    """Comparison only: discard a source attribution, never a safety qualifier."""
    text = re.sub(r"\s*\((?:APNI|MoFA|IITA|FAO|WHO)\)\s*[.!]?$", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip().rstrip(".!").casefold()


def fingerprint(value) -> str:
    """Stable SHA256 of canonical UTF8 JSON, including exact text inside strings."""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Finding:
    rule_id: str
    sentence: str
    reason: str
    evidence: tuple[str, ...] = ()
    recovery: tuple[str, ...] = ("revise", "reject", "request_info")


@dataclass
class Assessment:
    outcome: str = "pass"
    findings: list[Finding] = field(default_factory=list)
    judge_status: str = "not_required"

    def to_dict(self) -> dict:
        return asdict(self)


def assess(text: str, passages: list[dict], *, language: str = "en") -> Assessment:
    """Assess deterministic rules; return evidence without I/O or content rewriting.

    Args: exact farmer text, resolved source passages and stored proposal language.
    Returns: pass, safety_blocked or review_required plus rule evidence.
    Safety assumption: supplied passages are the immutable case snapshot. Unknown
    languages and uncertain chemical clauses require revision, not acknowledgement.
    """
    from agrireach.language import is_twi

    result = Assessment()
    def add(rule, sentence, reason, evidence=(), *, uncertain=False):
        result.findings.append(Finding(rule, sentence, reason, tuple(evidence)))
        if not uncertain or result.outcome != "safety_blocked":
            result.outcome = "review_required" if uncertain else "safety_blocked"

    if not text or not text.strip():
        add("TEXT", text or "", "Explicit farmer text is required")
        return result
    if language != "en" or is_twi(text) or re.search(r"[^\x00-\x7f]", text.replace("’", "'").replace("–", "-").replace("é", "e")):
        add("LANGUAGE", "", "Language assessment is outside the English policy", uncertain=True)
    source_sentences = {normalized(s) for p in passages for s in sentences(p.get("text", ""))}
    safe_templates = {normalized(s) for s in REFERRALS | PROTECTIVE}
    chemical_passages = [p for p in passages if p.get("risk") == "chemical" or CHEMICAL.search(p.get("text", ""))]
    ss = sentences(text)
    # All baseline chemical requirements permit local consultation. Additional
    # precautions in later corpus versions cannot inherit this exemption.
    registry_ids = {"APNI-SARI-2023:weeds-herbicide", "APNI-SARI-2023-MAIZE:p20-faw-control",
                    "APNI-SARI-2023-MAIZE:p22-sacks"}
    referral = any(normalized(s) in {normalized(x) for x in REFERRALS} for s in ss)
    for p in chemical_passages:
        consultation = [s for s in sentences(p["text"]) if re.search(PERSON, s, re.I)]
        kept = any(normalized(s) == normalized(c) for s in ss for c in consultation)
        if p["id"] not in registry_ids or fingerprint(p["text"]) != SOURCE_FINGERPRINTS.get(p["id"]):
            add("S1", "", "Chemical source requires a registered safeguard", [p["id"], p["text"]], uncertain=True)
        elif not (referral or kept):
            add("S1", "", "Required chemical consultation guidance is missing", [p["id"], *consultation])
    for s in ss:
        norm = normalized(s)
        if norm in safe_templates:
            continue
        reversal = re.search(r"\b(?:do not|don't|never|no need to)\s+(?:consult|ask|follow|wear)\b|\bignore\b.*\blabel\b|^spray\b.*\bwithout gloves\b", norm)
        if reversal and (chemical_passages or CHEMICAL.search(s)):
            add("S2", s, "Instruction reverses consultation, label or protection requirements")
            continue
        if norm in source_sentences:
            continue
        if CHEMICAL.search(s) or (chemical_passages and ACTION.search(s)):
            established = re.search(r"\b(?:every week|every day|twice a day|any pesticide|without gloves)\b", norm)
            add("S3", s, "Chemical instruction is not an accepted source sentence or template",
                [p["id"] for p in chemical_passages], uncertain=not bool(established))
        else:
            result.judge_status = "required"
    return result
