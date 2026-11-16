"""Conservative, explainable officer queue triage.

The priority is a *routing hint*, never a diagnosis or authorization to release
agricultural advice. The existing approval gate is unchanged. Institutions must
validate these provisional rules with qualified agricultural staff before use.
"""
from __future__ import annotations

import re


POLICY_VERSION = "triage-demo-v1"
RANK = {"critical": 0, "high": 1, "medium": 2, "routine": 3}

_SAFETY_EMERGENCY = re.compile(
    r"\b(?:pesticide poisoning|chemical poisoning|swallowed pesticide|"
    r"ingested pesticide|chemical exposure|pesticide in (?:my|the) eyes|"
    r"difficulty breathing after spraying)\b", re.IGNORECASE,
)
_RESTRICTED_TREATMENT = re.compile(
    r"\b(?:pesticides?|insecticides?|herbicides?|fungicides?|"
    r"agrochemicals?|chemical spray|mix(?:ing)? (?:two|both) chemicals|"
    r"mix(?:ing)? (?:two|both) pesticides)\b", re.IGNORECASE,
)
_SPREAD = re.compile(r"\b(?:outbreak|spreading to (?:other|nearby) farms|"
                     r"several (?:nearby )?farms (?:are )?affected)\b", re.IGNORECASE)


def assess(case: dict) -> dict:
    """Return a deterministic queue priority without modifying the case."""
    question = str(case.get("question") or "")
    urgent_reasons = case.get("urgent_reasons") or []
    if not isinstance(urgent_reasons, list):
        urgent_reasons = []
    existing_urgent = case.get("priority") == "urgent"

    if _SAFETY_EMERGENCY.search(question):
        level, reasons = "critical", ["Possible immediate human safety concern reported by farmer"]
    elif _RESTRICTED_TREATMENT.search(question):
        level, reasons = "high", ["Question mentions potentially restricted chemical treatment"]
    elif _SPREAD.search(question):
        level, reasons = "high", ["Farmer reports a possible spreading agricultural problem"]
    elif existing_urgent or urgent_reasons:
        level, reasons = "medium", ["Existing intake requires additional officer attention"]
    else:
        level, reasons = "routine", ["No priority escalation signal found in the available case text"]

    return {
        "level": level,
        "rank": RANK[level],
        "reasons": reasons,
        "policy_version": POLICY_VERSION,
        "provisional": True,
        "autonomous_release_permitted": False,
    }
