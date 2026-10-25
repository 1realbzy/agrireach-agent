"""Untracked harness: runs scripts/run_evals.py (unchanged) or N Ejura runs, and records per agent run the farmer
SMS, its length/encoding/parts, model SMS rewrites and every judge verdict (draft vs SMS phase) to a side JSONL.
Usage: wrap.py SIDE.jsonl field | wrap.py SIDE.jsonl ejura N"""
import asyncio, json, os, runpy, sys, tempfile, time
side_path, mode = sys.argv[1], sys.argv[2]
os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.mkdtemp(prefix='evallive-')}/evals.db"
sys.path.insert(0, "src")
from agrireach import agent, judge, farmer_reply
from agrireach.channels import sms
side = open(side_path, "a")
CAP, PHASE = {}, {"p": "draft"}
_j = judge.judge
def j(items, call=None):
    r = _j(items, call=call)
    CAP.setdefault("judge_calls", []).append({"phase": PHASE["p"], "error": r.get("error"),
        "verdicts": [{k: v[k] for k in ("sentence", "cited", "verdict", "why")} for v in r.get("verdicts", [])]})
    return r
judge.judge = j
_sc, _rw = farmer_reply.sms_claims, farmer_reply._llm_rewrite
def sc(*a, **k):
    PHASE["p"] = "sms"
    try:
        p = _sc(*a, **k)
    finally:
        PHASE["p"] = "draft"
    CAP.setdefault("sms_checks", []).append({"text": a[0], "problems": p}); return p
def rw(*a, **k):
    t, m = _rw(*a, **k); CAP.setdefault("model_sms", []).append(t); return t, m
farmer_reply.sms_claims, farmer_reply._llm_rewrite = sc, rw
_run = agent.run
async def run(q, *a, **k):
    CAP.clear(); t0 = time.time()
    o = await _run(q, *a, **k)
    fd = o.get("farmer_draft") or {}
    fd = json.loads(fd) if isinstance(fd, str) else fd
    txt = fd.get("text") or ""
    m = sms.measure(txt)
    side.write(json.dumps({"q": q, "secs": round(time.time() - t0, 1), "status": o.get("status"),
        "draft_mode": o.get("draft_mode"), "draft": o.get("draft"), "citation_check": o.get("citation_check"),
        "usage": o.get("usage"), "sms": txt, "sms_mode": fd.get("mode"), "sms_notes": fd.get("problems") or fd.get("notes"),
        "sms_fd_keys": sorted(fd.keys()), "sms_chars": len(txt), "sms_encoding": m.encoding, "sms_units": m.units,
        "sms_parts": m.segments, **CAP}, ensure_ascii=False) + "\n"); side.flush()
    u = o.get("usage") or {}
    if u.get("failed"):  # stop at the first failed model call (e.g. 402) instead of burning more calls
        print(json.dumps({"ABORT": f"{u['failed']} model call(s) failed: {u.get('errors')}", "q": q}), flush=True)
        os._exit(3)
    return o
agent.run = run
if mode in ("field", "core"):
    sys.argv = ["scripts/run_evals.py", mode]
    runpy.run_path("scripts/run_evals.py", run_name="__main__")
else:
    n = int(sys.argv[3])
    for i in range(n):
        o = asyncio.run(agent.run("When should I plant maize in Ejura?"))
        u = o.get("usage") or {}
        print(json.dumps({"ejura_run": i + 1, "draft_mode": o["draft_mode"], "usage": u}), flush=True)
        if u.get("failed"):
            sys.exit(f"STOP: {u['failed']} model call(s) failed: {u.get('errors')}")
