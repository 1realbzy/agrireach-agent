"""Optional text-to-speech for the officer-approved answer, run locally with Piper.

Off unless AGRIREACH_TTS=piper. AGRIREACH_TTS_VOICE (default en_US-lessac-medium) and AGRIREACH_TTS_DIR
(default ~/.cache/agrireach/piper) select the voice; download it once with
  python -m piper.download_voices en_US-lessac-medium --data-dir ~/.cache/agrireach/piper
The voice is US English. There is no Ghanaian English, Twi or Dagbani voice here.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def enabled() -> bool:
    return os.getenv("AGRIREACH_TTS", "") == "piper"


def synthesize(text: str, out_path: str) -> str:
    voice = os.getenv("AGRIREACH_TTS_VOICE", "en_US-lessac-medium")
    data_dir = os.getenv("AGRIREACH_TTS_DIR", str(Path.home() / ".cache/agrireach/piper"))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "piper", "-m", voice, "--data-dir", data_dir, "-f", out_path],
                   input=text, text=True, check=True, capture_output=True, timeout=120)
    return out_path
