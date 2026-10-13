"""Check that every passage in data/knowledge.json appears verbatim in its source PDF.

Usage: python scripts/verify_corpus.py   (needs network + pdftotext from poppler-utils)
"""
import json, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path

d = json.loads((Path(__file__).parent.parent / "data/knowledge.json").read_text())
norm = lambda s: re.sub(r"[\s\u25aa\u2022]+", " ", s).replace("\ufb00", "ff").replace("- ", "-")
fail = 0
for sid, src in d["sources"].items():
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "s.pdf"
        req = urllib.request.Request(src["url"], headers={"User-Agent": "Mozilla/5.0"})
        pdf.write_bytes(urllib.request.urlopen(req, timeout=60).read())
        text = norm(subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True).stdout)
    for p in [p for p in d["passages"] if p["source_id"] == sid]:
        ok = norm(p["text"]) in text
        fail += not ok
        print("OK  " if ok else "MISS", p["id"])
sys.exit(1 if fail else 0)
