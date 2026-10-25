"""Opt-out / retention purge after approval -> 'undeliverable' (terminal), never 'released'; and sends whose outcome
is unknown (timeout, lost reply) are marked so a retry is known to risk a duplicate. Offline; mocked HTTP."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from agrireach import api, db
from agrireach.channels import service, simulator, sms
from agrireach.channels.base import OutboundMessage
from tests.test_sms import CFG, FARMER, FakeAT

SENDER = "sim:farmer-u"
Q = "When should I harvest soybean in Tamale?"


def _case():
    return asyncio.run(simulator.ask(SENDER, text=Q))["case_id"]


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def test_opt_out_after_filing_makes_the_approved_case_undeliverable():
    cid = _case()
    asyncio.run(simulator.ask(SENDER, text="STOP"))
    h, c = _officer(), TestClient(api.app)
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "farmer_text": "Harvest at 9 of 10 brown pods.", "confirmed": True})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "undeliverable" and body["delivery"]["ok"] is False
    assert body["delivery_problem"] == "not sent: the farmer opted out (STOP)"
    # Not actionable: not in the pending queue; listed (and filterable) with the other cases.
    assert cid not in [x["id"] for x in c.get("/officer/queue", headers=h).json()]
    lst = c.get("/officer/cases", params={"status": "undeliverable"}, headers=h).json()
    assert [x["id"] for x in lst] == [cid] and lst[0]["delivery_problem"].endswith("opted out (STOP)")
    assert cid in [x["id"] for x in c.get("/officer/cases", headers=h).json()]
    assert c.get("/officer/cases", params={"status": "bogus"}, headers=h).status_code == 400
    assert c.get("/officer/cases").status_code == 401
    # Farmer view: no claim that an answer was sent, no answer text.
    fv = c.get(f"/farmer/cases/{cid}").json()
    assert fv["status"] == "undeliverable" and fv["answer"] is None and "Harvest" not in json.dumps(fv)
    # Terminal: no further decision, no release/retry, nothing sent.
    assert c.post(f"/officer/cases/{cid}/decision", headers=h,
                  json={"decision": "approve", "farmer_text": "x", "confirmed": True}).status_code == 409
    rel = c.post(f"/cases/{cid}/release", headers=h)
    assert rel.status_code == 409 and "undeliverable" in rel.json()["detail"]
    assert "no officer approval" not in rel.json()["detail"]
    logs = db.case_log(db.connect(), cid)
    assert any(l["tool"] == "mark_undeliverable" and "opted out" in l["result_summary"] for l in logs)


def test_retention_purge_after_filing_is_undeliverable_with_its_own_reason(monkeypatch):
    cid = _case()
    con = db.connect()
    later = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat(timespec="seconds")
    monkeypatch.setenv("AGRIREACH_RETENTION_DAYS", "30")
    db.purge_old(con, now_ts=later)
    out = simulator.officer_approve(cid, officer="Ama Mensah", farmer_text="Harvest.")
    assert out["ok"] is False
    assert db.get_case(con, cid)["status"] == "undeliverable"
    assert db.delivery_problem(con, cid) == "not sent: the number was removed by the retention purge"


def test_opted_out_marker_survives_a_later_purge(monkeypatch):
    cid = _case()
    asyncio.run(simulator.ask(SENDER, text="STOP"))
    con = db.connect()
    later = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat(timespec="seconds")
    monkeypatch.setenv("AGRIREACH_RETENTION_DAYS", "30")
    db.purge_old(con, now_ts=later)
    assert db.get_contact(con, cid)["sender_id"] == db.OPTED_OUT


def test_released_means_sent_for_channel_cases():
    cid = _case()
    out = simulator.officer_approve(cid, officer="Ama Mensah", farmer_text="Harvest.")
    assert out["ok"] is True and db.get_case(db.connect(), cid)["status"] == "released"


# --- outcome unknown ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError, httpx.ReadError])
def test_timeout_after_the_request_went_out_is_outcome_unknown(exc):
    def lost(req):
        raise exc("lost")
    r = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(lost))).send(FARMER, OutboundMessage(text="hi"))
    assert not r.ok and r.detail.startswith("outcome unknown: ")
    assert "may have been sent" in r.detail and "retry may send it twice" in r.detail


@pytest.mark.parametrize("exc", [httpx.ConnectError, httpx.ConnectTimeout])
def test_request_never_sent_is_a_plain_network_error(exc):
    def down(req):
        raise exc("down")
    r = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(down))).send(FARMER, OutboundMessage(text="hi"))
    assert not r.ok and r.detail.startswith("network error") and "outcome unknown" not in r.detail


def test_unreadable_success_response_is_outcome_unknown():
    r = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(FakeAT(body="<html>")))).send(
        FARMER, OutboundMessage(text="hi"))
    assert not r.ok and r.detail.startswith("outcome unknown: unreadable response")
