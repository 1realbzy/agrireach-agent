"""A released answer that the channel failed to send must not look delivered (QA, 25 Oct 2026). Offline; mocked HTTP.

State model: approved -> released -> (send fails) -> not_delivered -> either a fresh confirmed approval
(-> approved -> released) or a retry of the same approved text (-> released). A send that succeeds leaves the case
'released', and released cases keep the single-decision / 409 protections."""
import asyncio
import json
from urllib.parse import parse_qs, urlencode

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agrireach import api, db
from agrireach.channels import service, simulator, sms
from tests.test_sms import CFG, FARMER, FakeAT, callback


class SwitchableAT(FakeAT):
    """Mock Africa's Talking: answers with an error until .ok is set."""

    def __init__(self):
        super().__init__()
        self.ok = False

    def __call__(self, req):
        self.status = 200 if self.ok else 500
        return super().__call__(req)


def _setup(monkeypatch):
    at = SwitchableAT()
    at.ok = True  # the acknowledgement goes out
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    monkeypatch.setattr(service, "configured_channels", lambda: {"sms": ch, "simulator": simulator.SimulatorChannel()})
    item = sms.parse(urlencode(callback("When should I harvest soybean in Tamale?")).encode())
    cid = asyncio.run(sms.process(CFG, [item], channel=ch))[0]["case_id"]
    tok = db.add_officer(db.connect(), "Ama Mensah")
    return at, cid, {"Authorization": f"Bearer {tok}"}, TestClient(api.app)


def _approve(c, h, cid, text):
    return c.post(f"/officer/cases/{cid}/decision", headers=h,
                  json={"decision": "approve", "farmer_text": text, "confirmed": True})


def test_failed_send_after_release_is_not_delivered_and_reappears_in_the_queue(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    at.ok = False
    r = _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "not_delivered" and body["delivery"]["ok"] is False
    assert body["delivery_problem"].startswith("HTTP 500")
    q = c.get("/officer/queue", headers=h).json()
    item = next(x for x in q if x["id"] == cid)
    assert item["status"] == "not_delivered" and item["delivery_problem"].startswith("HTTP 500")
    fv = c.get(f"/farmer/cases/{cid}").json()
    assert fv["status"] == "not_delivered" and fv["answer"] is None and "not been sent" in fv["message"]
    assert "Harvest" not in json.dumps(fv)
    logs = json.dumps(db.case_log(db.connect(), cid))
    assert "not_delivered" in logs and FARMER not in logs


def test_officer_can_edit_and_re_approve_then_one_successful_release(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    at.ok = False
    _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    at.ok = True
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "farmer_text": "Harvest when 9 of 10 pods are brown.", "confirmed": True})
    assert r.status_code == 200 and r.json()["status"] == "released" and r.json()["delivery"]["ok"] is True
    sent = [parse_qs(x.content.decode())["message"][0] for x in at.requests]
    assert sent.count("Harvest when 9 of 10 pods are brown.") == 1 and "Harvest at 9 of 10 pods." not in sent[-1:]
    fv = c.get(f"/farmer/cases/{cid}").json()
    assert fv["status"] == "released" and fv["answer"] == "Harvest when 9 of 10 pods are brown."
    assert cid not in [x["id"] for x in c.get("/officer/queue", headers=h).json()]
    # Delivered: a further decision or release is refused as before (409), and nothing more is sent.
    n = len(at.requests)
    assert _approve(c, h, cid, "again").status_code == 409
    rel = c.post(f"/cases/{cid}/release", headers=h)
    assert rel.status_code == 409 and "already released" in rel.json()["detail"]
    assert len(at.requests) == n
    log = db.case_log(db.connect(), cid)
    re_appr = [l for l in log if l["tool"] == "officer_decision" and "after a failed delivery" in (l["args"] or "")]
    assert len(re_appr) == 1 and re_appr[0]["actor"] == "officer:Ama Mensah"
    assert sum(1 for l in log if l["tool"] == "release_to_farmer" and l["ok"]) == 2


def test_officer_can_retry_the_same_text(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    at.ok = False
    _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    r = c.post(f"/cases/{cid}/release", headers=h)          # still failing: stays not delivered, honest message
    assert r.status_code == 200 and r.json()["status"] == "not_delivered"
    assert "no officer approval" not in json.dumps(r.json())
    at.ok = True
    r = c.post(f"/cases/{cid}/release", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "released" and r.json()["delivery"]["ok"] is True
    assert parse_qs(at.requests[-1].content.decode())["message"] == ["Harvest at 9 of 10 pods."]
    assert c.post(f"/cases/{cid}/release", headers=h).status_code == 409


def test_length_backstop_and_unconfigured_channel_also_count_as_not_delivered(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    con = db.connect()
    db.officer_decide(con, cid, officer="Ama Mensah", decision="approve", farmer_text="Wear gloves. " * 60)
    db.release_to_farmer(con, cid)
    out = service.deliver(con, cid, {"sms": sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))})
    assert out["ok"] is False and db.get_case(con, cid)["status"] == "not_delivered"
    assert "too long for SMS" in api._case(db.get_case(con, cid))["delivery_problem"]
    # A simulator case whose channel is missing from the configured set.
    o = asyncio.run(service.handle_inbound(service.InboundMessage("simulator", "sim:farmer-2", text="When should I harvest soybean in Tamale?")))
    db.officer_decide(con, o["case_id"], officer="Ama Mensah", decision="approve", farmer_text="Harvest.")
    db.release_to_farmer(con, o["case_id"])
    assert service.deliver(con, o["case_id"], {})["ok"] is False
    assert db.get_case(con, o["case_id"])["status"] == "not_delivered"


def test_not_delivered_case_only_takes_an_approval_and_only_one_wins(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    at.ok = False
    _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json={"decision": "reject"})
    assert r.status_code == 409 and "not delivered" in r.json()["detail"]
    # Two re-approvals of the same not-delivered case: the second is refused (the first moved it on).
    con = db.connect()
    db.officer_decide(con, cid, officer="Ama Mensah", decision="approve", farmer_text="A")
    with pytest.raises(db.GateError):
        db.officer_decide(con, cid, officer="Kofi Boateng", decision="approve", farmer_text="B")


def test_web_only_cases_are_unchanged():
    con = db.connect()
    cid = TestClient(api.app).post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()["case_id"]
    db.officer_decide(con, cid, officer="Ama Mensah", decision="approve", farmer_text="Harvest.")
    db.release_to_farmer(con, cid)
    assert service.deliver(con, cid, {}) is None and db.get_case(con, cid)["status"] == "released"


def test_send_log_has_a_space_after_sent(monkeypatch):
    at, cid, h, c = _setup(monkeypatch)
    _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    s = [l["result_summary"] for l in db.case_log(db.connect(), cid) if l["tool"] == "send_answer"]
    assert s == ["sent: accepted by Africa's Talking (status 101 Sent; 1 segment, GSM-7)"]


def test_non_numeric_content_length_is_400_not_500():
    app = FastAPI()
    app.include_router(sms.router(CFG))
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post(f"/channels/sms/inbound/{CFG.webhook_token}", content=b"from=x&text=y",
               headers={"Content-Type": "application/x-www-form-urlencoded", "Content-Length": "abc"})
    assert r.status_code == 400
