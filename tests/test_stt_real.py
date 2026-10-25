"""Real speech-to-text (faster-whisper "base", CPU) on the synthetic English fixture clips.

Skipped unless faster-whisper is installed (requirements-voice.txt) and the model is already in the local cache, so
the normal test run stays offline. These clips are clean synthetic US-English speech (Piper TTS); passing here says
nothing about Ghanaian-accented English, Twi, Dagbani or Wali.
"""
import asyncio
import json
import re
import os
from pathlib import Path

import pytest

from agrireach import db
from agrireach.channels import simulator, stt

AUDIO = Path(__file__).parent / "fixtures/audio"
CACHE = Path(os.getenv("AGRIREACH_STT_DIR", str(Path.home() / ".cache/agrireach/whisper")))

pytest.importorskip("faster_whisper")
if not list(CACHE.glob("models--Systran--faster-whisper-base/snapshots/*/model.bin")):
    pytest.skip("faster-whisper 'base' model not cached locally", allow_module_level=True)


@pytest.fixture
def whisper():
    return stt.FasterWhisper("base", str(CACHE))


def test_transcribes_the_harvest_question_with_place_name(whisper):
    t = whisper.transcribe(str(AUDIO / "en_harvest_tamale_piper.wav"))
    text = t.text.lower()
    assert t.language == "en" and t.language_probability > 0.9
    assert "harvest" in text and "soybean" in text and "tamale" in text
    assert t.warnings == []


def test_ogg_opus_voice_note_decodes(whisper):
    """WhatsApp voice notes arrive as OGG/Opus; this is the same clip re-encoded to that format (PyAV, libopus)."""
    t = whisper.transcribe(str(AUDIO / "en_harvest_tamale_piper.ogg"))
    assert t.language == "en" and "harvest" in t.text.lower() and "tamale" in t.text.lower()


def test_known_failure_wa_is_heard_as_another_word(whisper):
    """Recorded limitation: the town name "Wa" is not recognised even with the vocabulary hint."""
    t = whisper.transcribe(str(AUDIO / "en_plant_wa_piper.wav"))
    words = t.text.lower().replace("?", " ").replace(".", " ").split()
    assert "plant" in words and "soybean" in words
    assert "wa" not in words  # if this starts passing, update docs/voice-channel.md


def test_voice_note_end_to_end_through_the_simulator_with_real_stt(whisper):
    out = asyncio.run(simulator.ask("sim:farmer-1", audio=str(AUDIO / "en_harvest_tamale_piper.wav"),
                                    transcriber=whisper))
    assert "harvest" in out["transcript"].lower()
    assert out["status"] == "pending_review"  # waits for the officer; nothing but the acknowledgement went out
    msgs = simulator.SimulatorChannel().messages("sim:farmer-1")
    assert len(msgs) == 1 and "officer" in msgs[0]["text"].lower()

    con = db.connect()
    proposed = json.loads(db.get_case(con, out["case_id"])["farmer_draft"])["text"]
    delivered = simulator.officer_approve(out["case_id"], officer="Test Officer", farmer_text=proposed)
    assert delivered["ok"]
    msgs = simulator.SimulatorChannel().messages("sim:farmer-1")
    assert msgs[-1]["text"] == proposed == db.get_case(con, out["case_id"])["farmer_text"]


PIPER = Path(os.getenv("AGRIREACH_TTS_DIR", str(Path.home() / ".cache/agrireach/piper")))


@pytest.mark.skipif(not (PIPER / "en_US-lessac-medium.onnx").exists(), reason="Piper voice not cached locally")
def test_round_trip_piper_answer_is_understood_by_whisper(whisper, tmp_path, monkeypatch):
    """The released answer is spoken by Piper and, as a sanity check, transcribed back by Whisper."""
    pytest.importorskip("piper")
    from agrireach.channels import tts
    from agrireach import voice_script

    s = voice_script.build("Harvest when most pods have turned brown [APNI-SARI-2023:p16-harvest].",
                           "Test Officer", "soybean")
    assert s.ok
    wav = tts.synthesize(s.text, str(tmp_path / "answer.wav"))
    back = whisper.transcribe(wav).text.lower()
    assert "agrireach" in back.replace(" ", "") or "agri" in back
    assert "pods" in back and "brown" in back


def test_misheard_wa_is_confirmed_back_not_guessed(whisper):
    """The real Whisper 'base' model hears the synthetic 'at Wa' clip as 'war': the farmer is asked, then it's used."""
    out = asyncio.run(simulator.ask("sim:farmer-2", audio=str(AUDIO / "en_plant_wa_piper.wav"), transcriber=whisper))
    if out["status"] != "awaiting_location":
        pytest.skip(f"this Whisper build transcribed the clip as {out.get('transcript')!r}")
    assert "Wa (Upper West Region)" in out["message"]
    done = asyncio.run(simulator.ask("sim:farmer-2", text="yes"))
    assert re.search(r"\bWa\b", done["question"]) and "war" not in done["question"].lower()
    assert db.get_case(db.connect(), done["case_id"])["region"].lower() == "wa"
