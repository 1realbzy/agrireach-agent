"""Speech-to-text for voice notes, run locally with faster-whisper (no audio leaves the machine).

Config:
  AGRIREACH_STT          faster-whisper (default) or none
  AGRIREACH_STT_MODEL    Whisper model size, default "base" (~145 MB, CPU int8; a few seconds per short note)
  AGRIREACH_STT_DIR      model cache, default ~/.cache/agrireach/whisper (downloaded from Hugging Face on first use)

Tested only on synthetic English speech (Piper TTS). NOT tested on Ghanaian-accented English, and Whisper does not
support Twi, Dagbani or Wali; such notes are detected as another language and the case is flagged for the officer.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# A short vocabulary hint. Without it, the base model wrote "Tamale" as "Tamali" in our tests.
PROMPT = ("A Ghanaian farmer's question. Places: Tamale, Wa, Bolgatanga, Yendi, Damongo, Nyankpala, Walewale, Kumasi, "
          "Adaklu. Crops: soybean, maize, cowpea, groundnut, cocoa.")
MIN_LANG_PROB = 0.6


@dataclass
class Transcript:
    text: str
    language: str
    language_probability: float
    duration_s: float
    engine: str
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"language": self.language, "language_probability": round(self.language_probability, 3),
                "duration_s": round(self.duration_s, 2), "engine": self.engine, "warnings": self.warnings}


class Transcriber:
    def transcribe(self, audio_path: str) -> Transcript:  # pragma: no cover - interface
        raise NotImplementedError


@lru_cache(maxsize=2)
def _load(model: str, cache_dir: str):
    from faster_whisper import WhisperModel  # optional dependency: requirements-voice.txt

    return WhisperModel(model, device="cpu", compute_type="int8", download_root=cache_dir)


class FasterWhisper(Transcriber):
    def __init__(self, model: str | None = None, cache_dir: str | None = None):
        self.model_name = model or os.getenv("AGRIREACH_STT_MODEL", "base")
        self.cache_dir = cache_dir or os.getenv("AGRIREACH_STT_DIR", str(Path.home() / ".cache/agrireach/whisper"))

    def transcribe(self, audio_path: str) -> Transcript:
        segments, info = _load(self.model_name, self.cache_dir).transcribe(audio_path, beam_size=5, initial_prompt=PROMPT)
        text = " ".join(s.text.strip() for s in segments).strip()
        return check(Transcript(text, info.language, float(info.language_probability), float(info.duration),
                                f"faster-whisper:{self.model_name}"))


def check(t: Transcript) -> Transcript:
    """Add warnings that make the case urgent: no speech, not English, or low language confidence."""
    if not t.text:
        t.warnings.append("voice note: no speech recognised; officer must listen to the audio")
    if t.language != "en":
        t.warnings.append(f"voice note: speech detected as '{t.language}' (p={t.language_probability:.2f}), not "
                          "English; AgriReach can't transcribe it reliably; officer must listen to the audio")
    elif t.language_probability < MIN_LANG_PROB:
        t.warnings.append(f"voice note: low confidence that this is English (p={t.language_probability:.2f}); "
                          "officer should check the transcript against the audio")
    return t


def default() -> Transcriber | None:
    if os.getenv("AGRIREACH_STT", "faster-whisper") == "none":
        return None
    return FasterWhisper()
