"""Check that every passage (or, for a table row, every cell) in data/knowledge.json appears verbatim in its source document.

Usage: python scripts/verify_corpus.py   (needs network + pdftotext from poppler-utils)
A source is read from `verify_url` if set, else `url`. `verify_format` is "pdf" (default) or "xml"
(e.g. the Europe PMC full-text XML of an open-access article).
"""
import html, json, re, subprocess, sys, tempfile, urllib.request
from pathlib import Path

d = json.loads((Path(__file__).parent.parent / "data/knowledge.json").read_text())
# pdftotext renders the ff/ffi ligature in the APNI maize guide as U+0093 ("di\x93icult" = "difficult").
LIGATURES = {"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\u0093": "ff"}


def norm(s: str) -> str:
    for a, b in LIGATURES.items():
        s = s.replace(a, b)
    return re.sub(r"[\s\u25aa\u2022]+", " ", s).replace("- ", "-")


def source_text(src: dict) -> str:
    req = urllib.request.Request(src.get("verify_url") or src["url"], headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=60).read()
    if src.get("verify_format") == "xml":
        return norm(html.unescape(re.sub(r"<[^>]+>", " ", raw.decode("utf-8", "replace"))))
    with tempfile.TemporaryDirectory() as td:
        pdf = Path(td) / "s.pdf"
        pdf.write_bytes(raw)
        # Layout mode keeps table rows together; raw mode keeps multi-line table cells together. Check both.
        return " \n ".join(norm(subprocess.run(["pdftotext", *mode, str(pdf), "-"], capture_output=True, text=True).stdout)
                            for mode in (["-layout"], []))


fail = 0
for sid, src in d["sources"].items():
    text = source_text(src)
    for p in [p for p in d["passages"] if p["source_id"] == sid]:
        if p.get("form") == "table_row":  # every cell (or each PDF line of a split cell) must be verbatim
            split = p.get("pdf_lines", {})
            parts = [line for c in p["cells"] for line in split.get(c, [c])]
            ok = all(norm(c) in text for c in parts) and " | ".join(p["cells"]) == p["text"]
        else:
            ok = norm(p["text"]) in text
        fail += not ok
        print("OK  " if ok else "MISS", p["id"])
sys.exit(1 if fail else 0)
