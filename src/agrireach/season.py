"""The question's received date next to the planting windows the draft cites: a plain fact for the officer.

It says whether the date falls inside any cited window and nothing more: no next window, no advice to plant.
"""
import calendar
import re
from datetime import date

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m} | {"sept": 9}
_POINT = re.compile(r"\b(?:(early|mid|end|late)\s+(?:of\s+)?)?(" + "|".join(sorted(_MONTHS, key=len, reverse=True))
                    + r")\b\.?(?:\s+(\d{1,2})(?:st|nd|rd|th)?\b)?", re.I)
_BETWEEN = re.compile(r"\bbetween\s+[^.]*?(?=\s+(?:based|with|depending)\b|[.;]|$)", re.I)
_SOURCE = {"MOFA": "MoFA", "IITA": "IITA", "APNI-SARI": "CSIR-SARI/APNI"}


def is_window(p: dict) -> bool:
    return "planting_window" in (p.get("claim_key") or "")


def _phrase(p: dict) -> str:
    if p.get("form") == "table_row" and p.get("cells"):
        return p["cells"][-1]
    m = _BETWEEN.search(p.get("text") or "")
    return m.group(0) if m else ""


def window(p: dict) -> tuple[tuple[int, int], tuple[int, int]] | None:
    """((month, day), (month, day)) of the window a passage gives, or None if its dates can't be read."""
    pts = list(_POINT.finditer(re.sub(r"(?i)\bmid-", "mid ", _phrase(p))))
    if len(pts) < 2:
        return None
    (q1, m1, d1), (q2, m2, d2) = (pts[0].groups(), pts[-1].groups())
    m1, m2 = _MONTHS[m1.lower()], _MONTHS[m2.lower()]
    start = int(d1) if d1 else {"early": 1, "mid": 11, "end": 21, "late": 21}.get((q1 or "").lower(), 1)
    last = calendar.monthrange(2001, m2)[1]
    end = int(d2) if d2 else {"early": 10, "mid": 20, "end": last, "late": last}.get((q2 or "").lower(), last)
    return (m1, start), (m2, end)


def _label(p: dict) -> str:
    src = next((v for k, v in _SOURCE.items() if p["source_id"].startswith(k)), p["source_id"])
    if p.get("form") == "table_row" and p.get("cells"):
        where = p["cells"][1].lower()
        return f"{src} {p['season']} season, {where}" if p.get("season") else f"{src}, {where}"
    return f"{src}, {p.get('region', '')} region".rstrip(", ")


def _rows(passages: list[dict]) -> list[tuple[str, str, tuple | None]]:
    rows, seen = [], set()
    for p in passages:
        if is_window(p) and p["id"] not in seen:
            seen.add(p["id"])
            rows.append((_label(p), _phrase(p), window(p)))
    return rows


def _inside(received: date, rows) -> bool:
    md = (received.month, received.day)
    return any(w and w[0] <= md <= w[1] for _, _, w in rows)


def outside(received: date, passages: list[dict]) -> bool:
    """True only when windows are cited, every one could be read, and none contains the received date."""
    rows = _rows(passages)
    return bool(rows) and all(w for _, _, w in rows) and not _inside(received, rows)


def prompt(received: date) -> str:
    """Approval prompt for the officer when outside() is True. A fact and a request to check; no advice."""
    return (f"season check: the question was received on {received.day} {received:%b %Y}, which is outside every "
            "planting window cited in the draft; check the timing before approving")


def fact(received: date, passages: list[dict]) -> str:
    """'Question received 25 Oct 2026. Windows cited: ...' plus a flag when the date is outside all of them.
    Empty when no cited passage gives a planting window."""
    rows = _rows(passages)
    if not rows:
        return ""
    cited = "; ".join(f"{label}: {phrase}" for label, phrase, _ in rows)
    out = f"Question received {received.day} {received:%b %Y}. Windows cited: {cited}"
    out += "" if out.endswith(".") else "."
    unread = [label for label, _, w in rows if not w]
    if unread:
        out += f" AgriReach could not read the dates of: {', '.join(unread)}."
    elif not _inside(received, rows):
        out += " The date is outside the cited windows."
    return out
