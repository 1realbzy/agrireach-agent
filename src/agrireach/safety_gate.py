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
    r"\b(?:with|using|in|into|onto)\s+\w+|\b(?:use|apply|mix|dose|administer)\s+\w+"
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
NO_ADVICE.add("I do not know which pesticide to recommend.")
for person in ("AEA", "extension agent", "agricultural extension officer"):
    REFERRALS.update({f"Talk to your local {person} about which pesticide to use.",
                      f"Ask your local {person} which fall armyworm pesticide to use."})


def registered_template(text: str) -> bool:
    """Recognize complete verified templates, including permitted attribution."""
    return normalized(text) in {normalized(s) for s in REFERRALS | PROTECTIVE | NO_ADVICE}


TOPICS = {
    "storage": r"\b(?:stor\w*|sacks?|grain|bagging|postharvest)\b",
    "faw": r"\b(?:faw|army\s?worms?|worms?|holes|infestation)\b",
    "weeds": r"\b(?:weeds?|weeding|herbicides?)\b",
}
SOURCE_TOPICS = {"APNI-SARI-2023:weeds-herbicide": "weeds",
                 "APNI-SARI-2023-MAIZE:p20-faw-control": "faw",
                 "APNI-SARI-2023-MAIZE:p22-sacks": "storage"}


def applicable(passage: dict, question: str, text: str) -> bool:
    """Exclude only classified incidental sources; ambiguity keeps S1 enabled.

    The immutable question participates so omitting reply keywords cannot remove
    its safeguards. Unknown IDs/topics and changed registered content fail closed.
    """
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


def assess(text: str, passages: list[dict], *, language: str = "en", question: str = "") -> Assessment:
    """Assess deterministic rules; return evidence without I/O or content rewriting.

    Args: exact farmer text, resolved source passages and stored proposal language.
    Returns: pass, safety_blocked or review_required plus rule evidence.
    Safety assumption: supplied passages are the immutable case snapshot. Unknown
    languages and uncertain chemical clauses require revision, not acknowledgement.
    """
    from agrireach.language import TWI_MARKERS

    result = Assessment()
    def add(rule, sentence, reason, evidence=(), *, uncertain=False):
        result.findings.append(Finding(rule, sentence, reason, tuple(evidence)))
        if not uncertain or result.outcome != "safety_blocked":
            result.outcome = "review_required" if uncertain else "safety_blocked"

    if not text or not text.strip():
        add("TEXT", text or "", "Explicit farmer text is required")
        return result
    words = re.findall(r"[^\W\d_]+", text.casefold())
    twi_hits = sum(w in TWI_MARKERS for w in words)
    english_hits = sum(w in {"the", "your", "when", "before", "do", "not", "consult", "use", "harvest", "maize", "pesticide", "to", "is", "at"} for w in words)
    foreign_script = bool(re.search(r"[\u0370-\u052f\u0600-\u06ff\u0900-\u0dff\u3040-\u9fff]", text))
    if twi_hits >= 2 or foreign_script or (language != "en" and english_hits < 2):
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
        if not applicable(p, question, text):
            continue
        consultation = [s for s in sentences(p["text"]) if re.search(PERSON, s, re.I)]
        kept = any(normalized(s) == normalized(c) for s in ss for c in consultation)
        if p["id"] not in registry_ids or fingerprint(p["text"]) != SOURCE_FINGERPRINTS.get(p["id"]):
            add("S1", "", "Chemical source requires a registered safeguard", [p["id"], p["text"]], uncertain=True)
        elif not (kept or preuse_referral or
                  (p["id"] == "APNI-SARI-2023:weeds-herbicide" and any("before applying any herbicide" in s for s in referral_sentences)) or
                  (p["id"] == "APNI-SARI-2023-MAIZE:p20-faw-control" and any("fall army worm" in s or "fall armyworm" in s for s in referral_sentences))):
            required = consultation or ["Consult your local AEA before choosing or applying a pesticide."]
            add("S1", "", "Required safeguard: " + " / ".join(required), [p["id"], *required])
    for s in ss:
        norm = normalized(s)
        if norm in safe_templates:
            continue
        reversal = re.search(
            rf"\b(?:do not|don't|never|no need to|do not need to|don't need to)\s+(?:consult|ask)\s+(?:your\s+)?(?:local\s+)?{PERSON}\b"
            rf"|(?<!not )(?<!never )(?<!don't )\bskip\s+(?:the\s+|your\s+)?(?:local\s+)?{PERSON}\b"
            r"|\b(?:do not|don't|never|no need to)\s+follow\s+(?:the\s+)?(?:pesticide\s+)?label\b"
            r"|\b(?:do not|don't|never|no need to)\s+wear\s+(?:protective\s+)?gloves\b"
            r"|\bignore\b.*\blabel\b|^spray\b.*\bwithout gloves\b"
            r"|^(?:apply|use|spray|treat)\b.*\bwithout (?:advice|consultation)\b", norm, re.I)
        if reversal:
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
