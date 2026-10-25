"""Replay every recorded real-model draft (docs/eval-run-*.txt) through the citation and claim checks.

Usage: python scripts/replay_drafts.py [--judge] [--json]
  --judge  also call the optional model judge (needs AGRIREACH_JUDGE_MODEL and LLM credentials)
Used to measure false rejects: each flagged draft is then labelled by hand (tests/fixtures/recorded_drafts.json).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from agrireach import citation_check, claim_check, knowledge  # noqa: E402

FILES = ["eval-run-2026-10-23.txt", "eval-run-2026-10-23-review.txt", "eval-run-2026-10-25-field.txt"]
CAUTION = re.compile(r"^Caution: the curated sources cover Northern Ghana only\..*?\n\n", re.S)


def recorded() -> list[dict]:
    """Model drafts from the recorded runs: the final model draft, or the rejected one if the run fell back."""
    out = []
    for f in FILES:
        run = "?"
        for line in (ROOT / "docs" / f).read_text().splitlines():
            m = re.match(r"#\s*[Rr]un (\S+) started", line)
            if m:
                run = m.group(1)
            if not line.startswith("{"):
                continue
            d = json.loads(line)
            cc = d.get("citation_check") or {}
            if cc.get("rejected_draft"):
                text = cc["rejected_draft"]
            elif str(d.get("draft_mode", "")).startswith("llm"):
                text = CAUTION.sub("", d["draft"])
            else:
                continue
            out.append({"file": f, "run": run, "task": d["task"], "q": d.get("q", ""), "sources": d["sources"],
                        "draft": text})
    return out


def passages_and_conflicts(ids: list[str]) -> tuple[list[dict], dict]:
    ps = [knowledge.reference(i) for i in ids]
    by_key: dict = {}
    for p in ps:
        for k in knowledge.claim_keys(p):
            by_key.setdefault(k, []).append(p)
    return ps, {k: g for k, g in by_key.items() if len({p["source_id"] for p in g}) > 1}


def main():
    use_judge = "--judge" in sys.argv
    rows = []
    for r in recorded():
        ps, conflicts = passages_and_conflicts(r["sources"])
        fig = citation_check.check_draft(r["draft"], ps, conflicts)
        claims = claim_check.check_claims(r["draft"], ps, conflicts, judge=use_judge)
        rows.append(r | {"figure_ok": fig.ok, "claim_ok": claims.ok, "claim_problems": claims.problems,
                         "judge": claims.judge})
    if "--json" in sys.argv:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
        return
    for r in rows:
        flag = "ok  " if r["claim_ok"] else "FLAG"
        print(f"{flag} run {r['run']:>3} task {r['task'][:28]:<28} figures {'ok' if r['figure_ok'] else 'FAIL'}")
        for p in r["claim_problems"]:
            print("      -", p)
    n, flagged = len(rows), sum(not r["claim_ok"] for r in rows)
    print(f"\n{n} recorded model drafts, {flagged} flagged by the claim check")


if __name__ == "__main__":
    main()
