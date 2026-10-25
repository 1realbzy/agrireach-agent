"""Run the EVALS.md task set against the real agent + MCP servers and print results.
Uses whatever draft mode is configured (offline stub unless LLM_BASE_URL/LLM_MODEL are set).

  python scripts/run_evals.py            # core tasks 1-12 and the field-evidence set F1-F14
  python scripts/run_evals.py core       # core tasks only
  python scripts/run_evals.py field      # field-evidence set only (evals/field_evidence.json)
"""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/evals.db")
from agrireach import agent, db, llm, knowledge, evalset

TASKS = [
    ("1 routine, region given", "When should I harvest my soybean? I farm near Tamale."),
    ("2 missing region", "When should I plant soybean?"),
    ("3 no matching reference", "What price will soybean sell for in Tamale market next month?"),
    ("4 conflicting sources", "What spacing between soybean plants in Tamale?"),
    ("5 chemical + disease", "My soybean leaves have yellow spots, what chemical should I spray in Tamale and what dose?"),
    ("10 region outside corpus", "When should I plant soybean in Kumasi?"),
    ("11 Wa (Upper West) town name", "When should I plant soybean at Wa?"),
    ("12 Twi-language question", "Bere ben na menndua soya wo Tamale?"),
]


def _record(o: dict) -> dict:
    return {"status": o["status"], "priority": o["priority"], "clarification": o["clarification"],
            "urgent_reasons": o["urgent_reasons"], "sources": o["sources"],
            "source_checks": [(c["source_id"], c["reachable"]) for c in o["source_checks"] or []],
            "errors": o["errors"], "draft_mode": o["draft_mode"], "language": o["language"],
            "citation_check": o["citation_check"], "draft": o["draft"]}


async def field():
    """Field-evidence evals: automatic routing checks; advice quality is graded by hand in EVALS.md."""
    passed = failed = 0
    for e in evalset.load():
        if e.get("skip"):
            print(json.dumps({"task": e["id"], "skipped": e["skip"]}, ensure_ascii=False))
            continue
        if e.get("kind") == "voice_script":
            problems = evalset.grade_voice_script(e)
            passed, failed = passed + (not problems), failed + bool(problems)
            print(json.dumps({"task": e["id"], "auto": "pass" if not problems else "FAIL", "auto_problems": problems,
                              "kind": "voice_script (code, no model)"}))
            continue
        o = await agent.run(e["question"])
        problems = evalset.grade(e, o)
        passed, failed = passed + (not problems), failed + bool(problems)
        print(json.dumps({"task": e["id"], "q": e["question"], "auto": "pass" if not problems else "FAIL",
                          "auto_problems": problems} | _record(o), ensure_ascii=False))
    print(json.dumps({"field_summary": {"auto_pass": passed, "auto_fail": failed}}))


async def main():
    print("draft mode:", llm.mode())
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "core"):
        await core()
    if which in ("all", "field"):
        await field()


async def core():
    for name, q in TASKS:
        o = await agent.run(q)
        print(json.dumps({"task": name, "q": q, "status": o["status"], "priority": o["priority"],
                          "clarification": o["clarification"], "urgent_reasons": o["urgent_reasons"],
                          "sources": o["sources"], "source_checks": [(c["source_id"], c["reachable"]) for c in o["source_checks"] or []],
                          "errors": o["errors"], "draft_mode": o["draft_mode"], "language": o["language"],
                          "citation_check": o["citation_check"], "draft": o["draft"]}, ensure_ascii=False))
    # 7: tool failure
    os.environ["AGRIREACH_KNOWLEDGE"] = "/nonexistent.json"
    o = await agent.run("When should I harvest soybean in Tamale?", use_fetch=False)
    print(json.dumps({"task": "7 tool failure", "priority": o["priority"], "errors": o["errors"], "sources": o["sources"]}))
    del os.environ["AGRIREACH_KNOWLEDGE"]
    # 6 + 8: gate and officer edit
    con = db.connect()
    cid = (await agent.run("When should I harvest soybean in Tamale?", use_fetch=False))["case_id"]
    try:
        db.release_to_farmer(con, cid); r6 = "RELEASED (FAIL)"
    except db.GateError as e:
        r6 = f"blocked: {e}"
    print(json.dumps({"task": "6 release without approval", "result": r6,
                      "log": [l["result_summary"] for l in db.case_log(con, cid) if not l["ok"]]}))
    row = db.officer_decide(con, cid, officer="Ama Mensah", decision="edit_approve", edited_text="Officer-edited text")
    row = db.release_to_farmer(con, cid)
    print(json.dumps({"task": "8 officer edit then approve", "status": row["status"], "officer": row["officer"],
                      "decided_at": row["decided_at"], "draft_kept": row["draft"][:40], "final": row["final_text"]}))

asyncio.run(main())
