"""Relevance of a registered chemical referral to the farmer's question.

Safety, evidence grounding, relevance and officer authorization are separate.
This check does not approve text, does not call a model, and does not score
keyword overlap between the question and the reply.

It applies only when every sentence is a registered chemical referral. The
question is classified with a closed set of operation and chemical intents:

* aligned: the question itself asks about a pest, weed, spray or chemical choice.
* unrelated: the question asks about harvest, planting or storage and does not
  ask about a pest, weed, spray or chemical. A pesticide referral is not an
  answer to that question.
* uncertain: the question fits neither group. Relevance is not claimed.
* not_applicable: the reply is not only a registered chemical referral, or no
  question was supplied. This does not confirm that the reply answers the
  question. A no-advice sentence such as "I am not sure." does not remove a
  registered referral from this check. Other checks still apply.

A local request counter elsewhere is not a provider bill, and a relevance
label is not officer approval.
"""
from __future__ import annotations

import re

_CHEMICAL_QUESTION = re.compile(
    r"\b(?:pesticides?|herbicides?|fungicides?|insecticides?|spray(?:ing|ed)?|weeds?|weeding|"
    r"armyworms?|fall army ?worms?|faw|worms?|insects?|pests?|caterpillars?|chemicals?)\b",
    re.I,
)
_OTHER_OPERATION = re.compile(
    r"\b(?:harvest(?:ing|ed|s)?|plant(?:ing|ed|s)?|sow(?:ing|n|ed)?|stor(?:e|ing|age|ed)|sacks?|bagging)\b",
    re.I,
)
_SUBJECTS = (
    ("faw_pesticide", ("fall army worm control pesticide", "which fall armyworm pesticide to use")),
    ("herbicide_application", ("before applying any herbicide",)),
    ("pesticide_choice", ("before choosing or applying a pesticide", "which pesticide to use")),
)


def _status(status: str, reason: str, subject: str | None = None) -> dict:
    result = {"status": status, "reason": reason}
    if subject:
        result["subject"] = subject
    return result


def _subject(normalized_sentences: list[str]) -> str:
    for sentence in normalized_sentences:
        for name, markers in _SUBJECTS:
            if any(marker in sentence for marker in markers):
                return name
    return "chemical_referral"


def classify(question: str, normalized_sentences: list[str], *, referral_norms: set[str],
             ignored_norms: set[str] | None = None) -> dict:
    """Classify a reply. `normalized_sentences` must already use the gate's comparison form.

    `ignored_norms` are closed no-advice sentences. They do not confirm relevance
    and they do not hide a registered referral in the same reply.
    `not_applicable` means this rule did not confirm relevance.
    """
    asked = (question or "").strip()
    if not asked or not normalized_sentences:
        return _status("not_applicable", "Relevance was not assessed because the question or the reply was empty.")
    considered = [sentence for sentence in normalized_sentences if sentence not in (ignored_norms or set())]
    if not considered:
        return _status(
            "not_applicable",
            "Relevance was not decided by the referral rule because the reply does not contain a registered chemical referral.",
        )
    if not referral_norms or any(sentence not in referral_norms for sentence in considered):
        return _status(
            "not_applicable",
            "Relevance was not decided by the referral rule because the reply is not only a registered chemical referral. "
            "not_applicable does not confirm that the reply answers the question.",
        )
    subject = _subject(considered)
    if _CHEMICAL_QUESTION.search(asked):
        return _status(
            "aligned",
            "The question asks about a pest, weed, spray or chemical choice, which is what this referral is for.",
            subject,
        )
    if _OTHER_OPERATION.search(asked):
        return _status(
            "unrelated",
            "This registered referral is about a pesticide, herbicide or fall armyworm product. "
            "The question asks about harvest, planting or storage and does not ask about that subject.",
            subject,
        )
    return _status(
        "uncertain",
        "The question does not identify a harvest, planting, storage, pest, weed or chemical choice. "
        "Relevance was not established.",
        subject,
    )
