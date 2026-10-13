"""Run the EVALS.md task set against the real agent + MCP servers and print results.
Uses whatever draft mode is configured (offline stub unless LLM_BASE_URL/LLM_MODEL are set)."""
import asyncio, json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/evals.db")
from agrireach import agent, db, llm, knowledge

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


async def main():
    print("draft mode:", llm.mode())
    for name, q in TASKS:
        o = await agent.run(q)
        print(json.dumps({"task": name, "q": q, "status": o["status"], "priority": o["priority"],
                          "clarification": o["clarification"], "urgent_reasons": o["urgent_reasons"],
                          "sources": o["sources"], "source_checks": [(c["source_id"], c["reachable"]) for c in o["source_checks"] or []],
                          "errors": o["errors"], "draft_mode": o["draft_mode"], "draft": o["draft"]}, ensure_ascii=False))
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
