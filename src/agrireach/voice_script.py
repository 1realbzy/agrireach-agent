"""Turn an officer-approved advisory into a short voice-message script (EVALS F14).

Follows Farmerline's published lessons for farmer voice messages (GSMA; research page S23): name the sender and
purpose first, and keep it to about 2-3 minutes. The approved sentences are kept word for word, so every figure
survives; only citation brackets and markdown are removed, because they can't be read aloud usefully.
A script over the length cap is returned with ok=False for the officer to shorten; it is never cut silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

WORDS_PER_MINUTE = 130   # a slow, clear speaking rate
MAX_SECONDS = 150         # 2.5 minutes, inside the 2-3 minute guidance


@dataclass
class VoiceScript:
    text: str
    words: int
    seconds: int
    ok: bool
    problems: list[str] = field(default_factory=list)


def speakable(text: str) -> str:
    t = re.sub(r"\s*\[[^\[\]]+\]", "", text)                 # citation brackets
    t = re.sub(r"\*\*|__|`|^#+\s*", "", t, flags=re.M)      # markdown emphasis and headings
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)           # bullets
    return re.sub(r"[ \t]+", " ", t).strip()


def build(approved_text: str, officer: str, topic: str = "") -> VoiceScript:
    if not officer or not officer.strip():
        raise ValueError("a named officer is required: only approved advice becomes a voice message")
    about = f" about {topic.strip()}" if topic and topic.strip() else ""
    opening = (f"Hello. This is AgriReach, with advice{about} approved by your extension officer, "
               f"{officer.strip()}.")
    closing = "If anything is unclear, please contact your extension officer. Thank you."
    text = "\n\n".join([opening, speakable(approved_text), closing])
    words = len(text.split())
    seconds = round(words / WORDS_PER_MINUTE * 60)
    problems = [] if seconds <= MAX_SECONDS else [
        f"about {seconds} s of speech, over the {MAX_SECONDS} s cap; officer should shorten the advice"]
    return VoiceScript(text, words, seconds, not problems, problems)
