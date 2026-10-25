"""Field-evidence eval set (evals/field_evidence.json): loading and automatic grading.

grade() checks routing-level expectations (status, priority, citations, urgent reasons, forbidden text) on an
agent.run() result. It does not judge whether the advice is good; that is graded by hand in EVALS.md.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / "evals" / "field_evidence.json"


def load(path: Path | str = PATH) -> list[dict]:
    return json.loads(Path(path).read_text())["evals"]


def runnable(evals: list[dict]) -> list[dict]:
    """Evals that are agent questions (run through agent.run)."""
    return [e for e in evals if not e.get("skip") and e.get("kind", "agent") == "agent"]


def grade_voice_script(e: dict, officer: str = "Ama Mensah") -> list[str]:
    """F14-style evals: build the voice script for the cited advisory and check opening, length and figures."""
    from agrireach import citation_check, knowledge, voice_script

    advisory = " ".join(f"{knowledge.reference(i)['text']} [{i}]" for i in e["advisory_passages"])
    s = voice_script.build(advisory, officer, "maize fertilizer")
    x, problems = e["expect"], list(s.problems)
    first = s.text.split("\n\n")[0]
    problems += [f"opening lacks {w!r}" for w in x.get("opening_contains", []) if w not in first]
    if s.seconds > x.get("max_seconds", voice_script.MAX_SECONDS):
        problems.append(f"{s.seconds} s is over {x['max_seconds']} s")
    if x.get("keep_figures"):
        key = lambda t: sorted((f.kind, f.value, f.unit, f.bound) for f in citation_check.extract_figures(t))
        if key(voice_script.speakable(advisory)) != key(citation_check.CITE_RE.sub("", advisory)):
            problems.append("a figure was lost or changed")
    return problems


def grade(e: dict, out: dict) -> list[str]:
    """Problems with `out` against e['expect']; an empty list means the automatic checks passed."""
    x, problems = e["expect"], []
    draft = out.get("draft") or ""
    reasons = " | ".join(out.get("urgent_reasons") or []).lower()
    sources = set(out.get("sources") or [])
    if x["outcome"] == "clarify":
        if out.get("status") != "draft" or not out.get("clarification"):
            problems.append(f"expected a clarifying question, got status {out.get('status')!r}")
        elif x.get("clarification_contains") and x["clarification_contains"] not in out["clarification"]:
            problems.append(f"clarification does not contain {x['clarification_contains']!r}")
        return problems
    if out.get("status") != x["outcome"]:
        problems.append(f"status {out.get('status')!r}, expected {x['outcome']!r}")
    if x.get("priority") and out.get("priority") != x["priority"]:
        problems.append(f"priority {out.get('priority')!r}, expected {x['priority']!r}")
    if x.get("cite_any") and not sources & set(x["cite_any"]):
        problems.append(f"none of {x['cite_any']} retrieved")
    if x.get("cite_any") and not any(f"[{i}]" in draft or i in draft for i in x["cite_any"]):
        problems.append(f"draft cites none of {x['cite_any']}")
    for i in x.get("cite_all") or []:
        if i not in draft:
            problems.append(f"draft does not cite {i}")
    if x.get("cite_none") and sources:
        problems.append(f"expected no passages, got {sorted(sources)}")
    for r in x.get("reason_contains") or []:
        if r.lower() not in reasons:
            problems.append(f"no urgent reason containing {r!r}")
    for pat in x.get("forbid") or []:
        m = re.search(pat, draft)
        if m:
            problems.append(f"draft contains forbidden text {m.group(0)!r}")
    if x.get("citation_check_ok") and not (out.get("citation_check") or {}).get("ok"):
        problems.append("citation check did not pass (verbatim fallback was used)")
    return problems
