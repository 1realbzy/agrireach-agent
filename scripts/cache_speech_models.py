"""Download pinned public CPU speech models for optional CI; no credentials required."""
import os
from pathlib import Path
import shutil

from huggingface_hub import hf_hub_download, snapshot_download

WHISPER_REVISION = "ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66"
PIPER_REVISION = "5041a7a49ae5b3a0f30e6837769eb03fdbb231bd"


def main():
    snapshot_download("Systran/faster-whisper-base", revision=WHISPER_REVISION,
        cache_dir=os.environ["AGRIREACH_STT_DIR"],
        allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*"])
    target = Path(os.environ["AGRIREACH_TTS_DIR"])
    target.mkdir(parents=True, exist_ok=True)
    for suffix in ("onnx", "onnx.json"):
        name = f"en_US-lessac-medium.{suffix}"
        source = hf_hub_download("rhasspy/piper-voices", revision=PIPER_REVISION,
                                filename=f"en/en_US/lessac/medium/{name}")
        shutil.copyfile(source, target / name)


if __name__ == "__main__":
    main()
