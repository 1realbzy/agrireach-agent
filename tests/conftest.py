import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("AGRIREACH_SOURCE_CHECK", "0")  # no network in unit tests
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "AGRIREACH_JUDGE_MODEL"):
        monkeypatch.delenv(k, raising=False)  # tests run in labelled offline stub mode
    monkeypatch.setenv("AGRIREACH_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("AGRIREACH_OUTBOX", str(tmp_path / "outbox"))
    monkeypatch.setenv("AGRIREACH_STT", "none")  # tests pass a fake transcriber; test_stt_real.py opts in
    for k in ("WHATSAPP_ENABLED", "AGRIREACH_TTS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1] / "src"))
    yield
