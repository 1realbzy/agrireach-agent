"""Run 6 (docs/live-eval-2026-10-25-run6-approval.md, cost): model_usage rows were written only when the agent created
a case, so the re-propose (/farmer-draft: farmer-text rewrite and SMS source check) and the approval-time source check
(judge) were missing from the app's cost log ($0.001262 gap). They now go through the same usage recording."""
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agrireach import db, farmer_reply as fr, judge, llm
from agrireach.api import app

Q = "Fall armyworm is eating my maize in Kintampo. What pesticide should I use?"


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def resp(cost):
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, cost=cost))


def fake_models(monkeypatch):
    def judge_call(user):
        llm.record_usage("judge", "fake-judge", resp(0.0002))
        n = len([l for l in user.splitlines() if ". SENTENCE: " in l])
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(n)]})

    def rewrite(officer_text, question, conflicts=False):
        llm.record_usage("farmer_text", "fake-model", resp(0.0001))
        return "Check your maize field at least once a week for damage.", "llm:fake"
    monkeypatch.setattr(judge, "_call", judge_call)
    monkeypatch.setattr(fr, "_llm_rewrite", rewrite)


def usage_rows(cid):
    return [r for r in db.case_log(db.connect(), cid) if r["tool"] == "model_usage"]


def test_farmer_draft_and_approval_model_calls_are_in_the_cost_log(monkeypatch):
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": Q}).json()["case_id"]  # offline: no model calls, so no usage row yet
    before = usage_rows(cid)
    fake_models(monkeypatch)
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    draft = "\n".join(l for l in c.get(f"/officer/cases/{cid}", headers=h).json()["draft"].splitlines()
                      if not l.startswith(llm.STUB_LABEL))
    fd = c.post(f"/officer/cases/{cid}/farmer-draft", headers=h, json={"officer_text": draft}).json()
    rows = usage_rows(cid)[len(before):]
    assert len(rows) == 1, rows
    args = json.loads(rows[0]["args"])
    assert rows[0]["actor"].startswith("officer:") and args["path"] == "farmer_draft"
    assert args["by_role"]["farmer_text"]["calls"] == 1 and args["by_role"]["judge"]["calls"] >= 1, args
    assert args["cost_usd"] is not None and "model calls succeeded" in rows[0]["result_summary"]

    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json=({"decision": "approve", "farmer_text": fd["text"], "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    assert r.status_code == 200, r.text
    rows = usage_rows(cid)[len(before) + 1:]
    assert len(rows) == 1, rows
    args = json.loads(rows[0]["args"])
    assert args["path"] == "approval_check" and args["by_role"]["judge"]["calls"] >= 1, args
    assert set(args["by_role"]) == {"judge"}


def test_a_failed_model_call_is_logged_too(monkeypatch):
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": Q}).json()["case_id"]
    before = usage_rows(cid)
    prop = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]

    class Boom:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    raise TimeoutError("judge timed out")

    monkeypatch.setattr(judge, "_call", lambda user: llm.create("judge", "fake-judge", Boom).choices[0])
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json=({"decision": "approve", "farmer_text": prop + " Check your maize field carefully for damage.", "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    assert r.status_code == 503, r.text
    rows = usage_rows(cid)[len(before):]
    assert len(rows) == 1 and not rows[0]["ok"], rows
    args = json.loads(rows[0]["args"])
    assert args["failed"] == 1 and args["errors"] == ["TimeoutError"] and args["path"] == "approval_check"
