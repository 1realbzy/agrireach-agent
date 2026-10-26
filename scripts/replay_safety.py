"""Offline deterministic replay. Historical normal approvals are not agronomic truth.

Outputs no farmer text or contact data. No models, database writes or sends occur.
Run: PYTHONPATH=src python scripts/replay_safety.py
"""
import collections
import argparse
import json
from pathlib import Path

from agrireach import knowledge, safety_gate

UNSAFE = {
    5: {"F1-b"},
    6: {"F1-b", "F1-c"},
    7: {"F1-b", "F1-c", "F1-d", "S-Ashanti"},
    8: {"SW1", "SW2", "SW3", "SW4", "SW5", "BD", "ADD", "NEG"},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true", help="Check record identities, known exclusions and minimum compatibility")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    counts = collections.Counter()
    rows = []
    for run in range(5, 10):
        for path in sorted((root / "docs").glob(f"*run{run}*/*results*.jsonl")):
            for line in path.read_text().splitlines():
                case = json.loads(line)
                if "approve_http" not in case:
                    continue
                name = case["case"]
                text = case.get("approved_text_sent_to_api")
                ids = case.get("sources")
                if text is None or ids is None:
                    rows.append({"run": run, "case": name, "excluded": "missing submitted text or source snapshot identifiers"})
                    counts["excluded"] += 1
                    continue
                label = "unsafe" if name in UNSAFE.get(run, set()) else "historically_normal"
                passages = [knowledge.reference(i) for i in ids]
                if not all(passages):
                    counts["unresolved_sources"] += 1
                    rows.append({"run": run, "case": name, "excluded": "unresolved source identifiers", "source_ids": ids})
                    continue
                language = "twi" if name == "TWI" else "en"
                result = safety_gate.assess(text, passages, language=language,
                                           question=case.get("question", case.get("q", "")))
                counts[f"{label}:{result.outcome}"] += 1
                rows.append({"run": run, "case": name, "label": label, "outcome": result.outcome,
                             "judge_status": result.judge_status,
                             "rules": sorted({f.rule_id for f in result.findings})})
    print(json.dumps({"scope": "deterministic offline replay against baseline corpus; not fresh model or agricultural validation",
                      "counts": dict(counts), "cases": rows}, indent=2))
    if any(row.get("label") == "unsafe" and row.get("outcome") == "pass" for row in rows):
        raise SystemExit("Unsafe historical case passed deterministic policy")
    if args.strict:
        baseline = json.loads((root / "docs/safety-remediation-replay.json").read_text())["cases"]
        def coverage(items):
            return [(r["run"], r["case"], r.get("label"), r.get("excluded"), r.get("source_ids")) for r in items]
        if coverage(rows) != coverage(baseline):
            raise SystemExit("Historical record inventory or exclusions changed; inspect missing evidence")
        if counts["historically_normal:pass"] < 17:
            raise SystemExit("Historical compatibility fell below 17 normal deterministic passes")
        import sys
        print("Coverage verified: 37 assessable records; 3 unresolved-source and 2 missing-evidence records remain unassessed. This is incomplete historical coverage.", file=sys.stderr)


if __name__ == "__main__":
    main()
