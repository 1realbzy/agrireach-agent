"""Speech-to-text on a few Ghanaian-accented English clips (not committed; downloaded at run time).

Source: "Ghana English ASR Dataset", ghanaopenai/ghana-english-speech-600hrs on Hugging Face (Mich-Seth Owusu,
Ghana NLP Community), CC BY-NC 4.0: non-commercial research and education use, with attribution. Broadcast news
segments, not farmers' voice notes; the reference transcripts themselves contain errors (e.g. "Kuhasi", "Ara").
The audio is cached under ~/.cache/agrireach/ghana-clips and never added to the repo.

  python scripts/stt_ghana_check.py            # the 10 clips used for the run in docs/eval-run-2026-10-25-voice.txt
  python scripts/stt_ghana_check.py --rows 5 77 # other rows
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agrireach import places  # noqa: E402
from agrireach.channels import location, stt  # noqa: E402

DATASET = "ghanaopenai/ghana-english-speech-600hrs"
API = "https://datasets-server.huggingface.co/rows?dataset={d}&config=default&split=train&offset={o}&length=1"
# Rows picked by searching six 100-row pages for farming words or Ghana place names in the reference text.
ROWS = [22, 50, 51, 200035, 300032, 390017, 390023, 390033, 390034, 390036]
CACHE = Path.home() / ".cache/agrireach/ghana-clips"


def _words(s: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", s.lower())


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = _words(ref), _words(hyp)
    d = list(range(len(h) + 1))
    for i, a in enumerate(r, 1):
        prev, d[0] = d[:], i
        for j, b in enumerate(h, 1):
            d[j] = min(prev[j] + 1, d[j - 1] + 1, prev[j - 1] + (a != b))
    return d[-1], len(r)


def fetch(row: int) -> tuple[Path, str]:
    CACHE.mkdir(parents=True, exist_ok=True)
    wav, ref = CACHE / f"{row}.wav", CACHE / f"{row}.txt"
    if not wav.exists():
        r = json.load(urllib.request.urlopen(API.format(d=DATASET, o=row), timeout=60))["rows"][0]["row"]
        urllib.request.urlretrieve(r["audio"][0]["src"], wav)
        ref.write_text(r["corrected_text"], encoding="utf-8")
    return wav, ref.read_text(encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, nargs="*", default=ROWS)
    ap.add_argument("--model", default="base")
    args = ap.parse_args(argv)
    w = stt.FasterWhisper(args.model)
    errs = words = flagged = 0
    for row in args.rows:
        wav, ref = fetch(row)
        t = w.transcribe(str(wav))
        e, n = wer(ref, t.text)
        errs, words, flagged = errs + e, words + n, flagged + bool(t.warnings)
        s = location.suggest(t.text)
        print(json.dumps({"row": row, "wer": round(e / n, 2), "language": t.language,
                          "p": round(t.language_probability, 2), "flagged_for_officer": bool(t.warnings),
                          "ref_places": [p["name"] for p in places.find(ref)],
                          "heard_places": [p["name"] for p in places.find(t.text)],
                          "location_question": s.question() if s else None, "ref": ref, "heard": t.text},
                         ensure_ascii=False))
    print(json.dumps({"clips": len(args.rows), "model": args.model, "wer": round(errs / words, 3),
                      "word_errors": errs, "ref_words": words, "flagged_for_officer": flagged}))


if __name__ == "__main__":
    main()
