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

POLICY_VERSION = "chemical-2"
SOURCE_FINGERPRINTS = {'APNI-SARI-2023:weeds-herbicide': '7c089f0dc5fbace588368f1dbef72fea4c00445a0e6c6c4d58d37c68360da91c', 'APNI-SARI-2023-MAIZE:p20-faw-control': 'a54a9501e8bd86701d3823aaea38dd9fbbae8e6eff66985fdcee94ff8077415e', 'APNI-SARI-2023-MAIZE:p22-sacks': '5d7dd431a6b34d46b89760c8ae3709db7b1afdc2937ee845308a5361dd094594'}
CHEMICAL = re.compile(r"\b(?:pesticides?|insecticides?|herbicides?|fungicides?|chemicals?|spray\w*|glyphosate|paraquat)\b", re.I)
ACTION = re.compile(r"\b(?:apply|use|mix|spray|treat|ignore|consult|ask|wear)\b", re.I)
CONTEXT_ACTION = re.compile(r"\b(?:apply|use|mix|spray|treat)\s+(?:it|them|this|that|these|those|the product)\b", re.I)
UNKNOWN_BRAND_ACTION = re.compile(r"\b(?:Apply|Use|Mix|Treat|apply|use|mix|treat)\s+[A-Z][A-Za-z]*[A-Z][A-Za-z]*\b")
# Unsupported material instructions are uncertain even when the material has an
# unfamiliar lowercase name. Source sentences are exempted before this check.
MATERIAL_INSTRUCTION = re.compile(
    r"\b(?:use|apply|mix|spray|treat|drench|dust|dose|administer)\b", re.I)
MATERIAL_OBJECT = re.compile(
    r"\b(?:with|using)\s+\w+|\b(?:use|apply|mix|dose|administer)\s+\w+"
    r"|\b(?:it|them|this product|that product)\b|\b\d+\s*(?:ml|litres?|grams?|kg|days?)\b", re.I)
PERSON = r"(?:AEA|agricultural extension officer|agricultural extension agent|extension officer|extension agent)"
REFERRALS = {
    f"{verb} your local {person} {tail}."
    for verb in ("Consult", "Ask")
    for person in ("AEA", "agricultural extension officer", "agricultural extension agent")
    for tail in ("before choosing or applying a pesticide", "before applying any herbicide",
                 "for advice on the recommended fall army worm control pesticide in your area")
}
PROTECTIVE = {"Do not use unapproved pesticides.", "Do not spray without gloves."}
NO_ADVICE = {"I do not know.", "I am not sure.", "Your extension officer will confirm which to follow."}


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
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class Finding:
    rule_id: str
    sentence: str
    reason: str
    evidence: tuple[str, ...] = ()
    recovery: tuple[str, ...] = ("revise", "reject", "request_info")

    def to_dict(self) -> dict:
        """Serialize rule evidence consistently for authenticated clients and storage."""
        return asdict(self)


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
    safe_templates = {normalized(s) for s in REFERRALS | PROTECTIVE | NO_ADVICE}
    chemical_passages = [p for p in passages if p.get("risk") == "chemical" or CHEMICAL.search(p.get("text", ""))]
    ss = sentences(text)
    # All baseline chemical requirements permit local consultation. Additional
    # precautions in later corpus versions cannot inherit this exemption.
    registry_ids = {"APNI-SARI-2023:weeds-herbicide", "APNI-SARI-2023-MAIZE:p20-faw-control",
                    "APNI-SARI-2023-MAIZE:p22-sacks"}
    referral_sentences = [normalized(s) for s in ss if normalized(s) in {normalized(x) for x in REFERRALS}]
    preuse_referral = any("before choosing or applying a pesticide" in s for s in referral_sentences)
    for p in chemical_passages:
        consultation = [s for s in sentences(p["text"]) if re.search(PERSON, s, re.I)]
        kept = any(normalized(s) == normalized(c) for s in ss for c in consultation)
        if p["id"] not in registry_ids or fingerprint(p["text"]) != SOURCE_FINGERPRINTS.get(p["id"]):
            add("S1", "", "Chemical source requires a registered safeguard", [p["id"], p["text"]], uncertain=True)
        elif not (kept or preuse_referral or
                  (p["id"] == "APNI-SARI-2023:weeds-herbicide" and any("before applying any herbicide" in s for s in referral_sentences)) or
                  (p["id"] == "APNI-SARI-2023-MAIZE:p20-faw-control" and any("fall army worm" in s for s in referral_sentences))):
            add("S1", "", "Required chemical consultation guidance is missing", [p["id"], *consultation])
    for s in ss:
        norm = normalized(s)
        if norm in safe_templates:
            continue
        reversal = re.search(
            rf"\b(?:do not|don't|never|no need to)\s+(?:consult|ask)\s+(?:your\s+)?(?:local\s+)?{PERSON}\b"
            r"|\b(?:do not|don't|never|no need to)\s+follow\s+(?:the\s+)?(?:pesticide\s+)?label\b"
            r"|\b(?:do not|don't|never|no need to)\s+wear\s+(?:protective\s+)?gloves\b"
            r"|\bignore\b.*\blabel\b|^spray\b.*\bwithout gloves\b"
            r"|^(?:apply|use|spray|treat)\b.*\bwithout (?:advice|consultation)\b", norm, re.I)
        if reversal and (chemical_passages or CHEMICAL.search(s)):
            add("S2", s, "Instruction reverses consultation, label or protection requirements")
            continue
        if norm in source_sentences:
            continue
        # Chemical case context does not make every agricultural verb a pesticide
        # instruction. Only bounded pronoun continuations and product shapes use
        # that context; unknown indirect wording remains a documented limitation.
        product_instruction = MATERIAL_INSTRUCTION.search(s) and MATERIAL_OBJECT.search(s)
        if CHEMICAL.search(s) or product_instruction or (chemical_passages and CONTEXT_ACTION.search(s)):
            established = re.search(r"\b(?:every week|every day|twice a day|any pesticide|without gloves)\b", norm)
            add("S3", s, "Chemical instruction is not an accepted source sentence or template",
                [p["id"] for p in chemical_passages], uncertain=not bool(established))
        else:
            result.judge_status = "required"
    return result
