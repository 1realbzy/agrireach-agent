"""D9 (t43): the officer API names how a case's draft and response were made, from recorded rows only, and shows the
recorded MCP tool execution and draft-check evidence. No model calls: the drafter and judge are fakes that record
usage the way llm.create does."""
import asyncio
import json

from fastapi.testclient import TestClient

from agrireach import agent, db, judge, llm
from agrireach.api import app

QB = "Can I mix two insecticides together and use double the label dose to kill fall armyworm on my maize in Tamale faster?"
S, P, C = ("APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
           "APNI-SARI-2023-MAIZE:p20-faw-control")
BODY = (f"Rotate maize with groundnut and weed the field properly to reduce Fall Army worm infestations [{P}]. "
        f"Walk through the maize field at least once a week to look for larvae [{S}].\n")
GOOD = BODY + f"Consult your local AEA for advice on the recommended fall army worm control pesticide in your area [{C}]."
BAD = BODY + f"Do not mix insecticides or use double the label dose. [{C}]"
WRITER, JUDGE = "mistralai/mistral-small-3.2-24b-instruct", "meta-llama/llama-3.3-70b-instruct"


def _record(role, model, p, c, cost):
    calls = llm._usage.get()
    if calls is not None:
        calls.append(llm._call_record(role, model, ok=True, error=None, prompt_tokens=p, completion_tokens=c, cost_usd=cost))


def fakes(monkeypatch, replies):
    n = []
    def draft(question, passages, notes, conflicts=None, feedback=None):
        n.append(feedback)
        _record("draft", WRITER, 1200, 150, 0.000165)
        return replies[min(len(n) - 1, len(replies) - 1)], f"llm:{WRITER}"
    def call(user):
        _record("judge", JUDGE, 900, 80, 0.000696)
        items = [l for l in user.splitlines() if "SENTENCE:" in l]
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "Direct quote"} for i in range(len(items))]})
    monkeypatch.setattr(llm, "draft", draft)
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", JUDGE)
    monkeypatch.setattr(judge, "_call", call)
    return n


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def detail(cid, h=None):
    return TestClient(app).get(f"/officer/cases/{cid}", headers=h or officer()).json()


def test_a_live_model_draft_that_passed(monkeypatch):
    fakes(monkeypatch, [GOOD])
    out = asyncio.run(agent.run(QB, use_fetch=False))
    g = detail(out["case_id"])["generation"]
    assert g["state"] == "live_model_draft" and g["label"] == "LIVE MODEL DRAFT" and g["live_model"]
    assert g["drafting_usage"]["model_calls"] == out["usage"]["calls"] >= 2 and g["model_used"]
    assert g["draft_attempts"] == 1


def test_b_rejected_live_draft_then_source_fallback_names_calls_and_cost(monkeypatch):
    fakes(monkeypatch, [BAD, BAD])
    out = asyncio.run(agent.run(QB, use_fetch=False))
    assert out["draft_mode"].startswith("stub(citation-check-fallback")
    d = detail(out["case_id"])
    g = d["generation"]
    n, cost = out["usage"]["attempted"], out["usage"]["cost_usd"]
    assert n >= 2 and cost > 0
    assert g["state"] == g["draft_state"] == "model_draft_rejected_source_fallback" and not g["live_model"]
    assert g["model_used"] and g["drafting_usage"]["attempted_calls"] == n and g["drafting_usage"]["cost_usd"] == cost
    assert f"({n} model calls, ${cost:.6f})" in g["label"] and "after 2 attempt(s)" in g["label"]
    assert "NO MODEL" not in g["label"].upper() and "no language model" not in g["label"].lower()
    checks = d["tool_evidence"]["draft_checks"][-1]
    assert checks["fallback_to_sources"] and [a["ok"] for a in checks["attempts"]] == [False, False]
    assert any("Do not mix insecticides" in p for p in checks["attempts"][-1]["problems"])


def test_c_offline_source_draft_says_no_model_calls():
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()["case_id"]
    g = detail(cid)["generation"]
    assert g["state"] == "offline_source_draft" and not g["model_used"] and g["attempted_calls"] == 0
    assert g["label"].startswith("NO MODEL CALLS")


def test_d_officer_written_response_after_an_offline_draft():
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()["case_id"]
    case = c.get(f"/officer/cases/{cid}", headers=h).json()
    own = case["farmer_draft"]["text"].split("\n")[0].strip()
    body = {"decision": "edit_approve", "edited_text": case["draft"] + "\nOfficer: I checked these dates for Tamale.",
            "farmer_text": own, "confirmed": True, "expected_revision": case["revision"]}
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json=body)
    assert r.status_code == 200, r.text
    g = c.get(f"/officer/cases/{cid}", headers=h).json()["generation"]
    assert g["state"] == "officer_written" and g["officer_edited_officer_text"]
    assert g["draft_state"] == "offline_source_draft" and "Ama Mensah" in g["label"]
    assert g["label"].endswith(g["draft_label"])


def test_officer_re_propose_does_not_hide_the_draft_mode(monkeypatch):
    fakes(monkeypatch, [BAD, BAD])
    out = asyncio.run(agent.run(QB, use_fetch=False))
    cid, h = out["case_id"], officer()
    c = TestClient(app)
    c.post(f"/officer/cases/{cid}/farmer-draft", headers=h, json={"officer_text": "Walk the field weekly."})
    g = c.get(f"/officer/cases/{cid}", headers=h).json()["generation"]
    assert g["state"] == "model_draft_rejected_source_fallback"   # before t43: the officer's proposal row hid it


def test_tool_evidence_lists_recorded_mcp_calls_in_order(monkeypatch):
    fakes(monkeypatch, [GOOD])
    out = asyncio.run(agent.run(QB, use_fetch=False))
    ev = detail(out["case_id"])["tool_evidence"]
    assert ev["mcp_recorded"] and ev["draft_checks_recorded"]
    calls = ev["mcp_runs"][-1]["calls"]
    names = [c["tool"] for c in calls]
    assert "search_guidance" in names and names[-1] == "create_or_update_case"
    assert [c["seq"] for c in calls] == list(range(1, len(calls) + 1))
    assert all(c["ok"] and isinstance(c["ms"], int) and c["ms"] >= 0 and c["error"] is None for c in calls)
    assert [c["start_ms"] for c in calls] == sorted(c["start_ms"] for c in calls)
    tools = [t["tool"] for t in ev["timeline"]]
    assert tools.index("model_usage") > tools.index("farmer_text_proposal") and "mcp_tool_calls" in tools


def test_tool_evidence_for_a_case_from_before_t43_says_not_recorded():
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()["case_id"]
    con = db.connect()
    with con:
        con.execute("DELETE FROM tool_log WHERE case_id=? AND tool IN ('mcp_tool_calls','draft_checks')", (cid,))
    ev = detail(cid)["tool_evidence"]
    assert ev["mcp_recorded"] is False and ev["mcp_runs"] == [] and ev["draft_checks_recorded"] is False


class _Res:
    def __init__(self, text, err):
        self.content, self.isError = [type("T", (), {"text": text})()], err


class _Session:
    def __init__(self, res=None, exc=None):
        self.res, self.exc = res, exc

    async def call_tool(self, name, args):
        if self.exc:
            raise self.exc
        return self.res


def test_mcp_tool_errors_are_recorded_with_the_error():
    t = agent.Tools(_Session(_Res("crop is required for guidance search", True)), None)
    try:
        asyncio.run(t.call("search_guidance", {"query": "x", "crop": ""}))
    except RuntimeError:
        pass
    t2 = agent.Tools(_Session(exc=TimeoutError("slow")), None)
    try:
        asyncio.run(t2.call("get_recent_rainfall", {"district": "Tamale"}))
    except TimeoutError:
        pass
    assert t.calls[0]["ok"] is False and "crop is required" in t.calls[0]["error"]
    assert t2.calls[0] == t2.calls[0] | {"tool": "get_recent_rainfall", "ok": False, "error": "TimeoutError: slow"}


def test_draft_check_evidence_is_bounded():
    out = {"case_id": 1, "draft_mode": "stub(x)", "source_checks": [],
           "citation_check": {"ok": False, "attempts": [{"ok": False, "problems": ["p" * 900] * 20}]}}
    _, checks = agent.run_evidence(out, agent.Tools(None, None))
    a = checks["attempts"][0]
    assert len(a["problems"]) == agent.EVIDENCE_PROBLEMS and a["problems_total"] == 20
    assert all(len(p) <= agent.EVIDENCE_CHARS for p in a["problems"])
