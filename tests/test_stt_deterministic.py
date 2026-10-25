"""The speech-to-text step must give the same transcript for the same audio: it decides the farmer's district.
faster-whisper's default temperature list falls back to random sampling, which made test_stt_real flip between runs."""
import types

from agrireach.channels import stt


def test_transcribe_uses_temperature_zero_only(monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, path, **kw):
            seen.update(kw)
            info = types.SimpleNamespace(language="en", language_probability=0.99, duration=3.0)
            return [types.SimpleNamespace(text=" When should I plant soybean in Tamale?", avg_logprob=-0.2,
                                          no_speech_prob=0.01)], info

    monkeypatch.setattr(stt, "_load", lambda *a: FakeModel())
    stt.FasterWhisper("base", "/tmp").transcribe("x.wav")
    assert seen["temperature"] == 0.0
