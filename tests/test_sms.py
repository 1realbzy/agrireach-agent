"""SMS adapter (Africa's Talking), offline only: encoding and segment counts, config, the inbound callback route and
outbound sends via a mocked HTTP transport. No account exists; numbers are fictional and unallocated (+233 00 000 00xx)."""
import asyncio
import json
from urllib.parse import parse_qs, urlencode

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agrireach import api, db
from agrireach.channels import service, sms
from agrireach.channels.base import OutboundMessage, mask_sender

CFG = sms.Config(username="sandbox", api_key="at-key-abc", webhook_token="tok-0123456789abcdef0123",
                 sender_id=None, sandbox=True, max_segments=4)
FARMER = "+233000000017"


# --- length and encoding ----------------------------------------------------------------------------------------

def test_plain_english_is_gsm7_single_and_multipart():
    assert sms.measure("a" * 160) == sms.Length("GSM-7", 160, 1, ())
    assert sms.measure("a" * 161).segments == 2              # multipart: 153 per part
    assert sms.measure("a" * 306).segments == 2
    assert sms.measure("a" * 307).segments == 3
    assert sms.measure("").segments == 0


def test_gsm7_extension_characters_count_double():
    m = sms.measure("[" * 80)  # '[' is in the GSM-7 extension table: escape + char
    assert m.encoding == "GSM-7" and m.units == 160 and m.segments == 1
    assert sms.measure("[" * 81).segments == 2


def test_twi_and_dagbani_letters_force_ucs2():
    m = sms.measure("Wo bɛtumi adua aburo.")
    assert m.encoding == "UCS-2" and "ɛ" in m.non_gsm
    assert sms.measure("ɔ" * 70).segments == 1
    assert sms.measure("ɔ" * 71).segments == 2               # multipart UCS-2: 67 per part
    assert sms.measure("ɔ" * 134).segments == 2
    assert sms.measure("ɔ" * 135).segments == 3
    assert sms.measure("ŋ").encoding == "UCS-2" and sms.measure("ʒ").encoding == "UCS-2"
    assert sms.measure("😀").units == 2                      # outside the BMP: two UTF-16 units


def test_over_max_segments_is_refused_not_truncated():
    pesticide = "Wear gloves and a mask when you spray, and keep children away for 24 hours."
    text = ("Plant soybean when the rains are steady. " * 16) + pesticide
    seen = []
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r) or httpx.Response(500))))
    r = ch.send(FARMER, OutboundMessage(text=text))
    assert not r.ok and "segments" in r.detail and "max 4" in r.detail and "shorten" in r.detail
    assert seen == []                                         # nothing sent, nothing cut


def test_ucs2_refusal_names_the_characters_that_forced_it():
    text = "Wo bɛtumi " + "a" * 300
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    r = ch.send(FARMER, OutboundMessage(text=text))
    assert not r.ok and "UCS-2" in r.detail and "ɛ" in r.detail


# --- config -----------------------------------------------------------------------------------------------------

def test_off_by_default_and_misconfiguration_fails_clearly(monkeypatch):
    assert not sms.enabled()
    assert not any("/channels/sms" in getattr(r, "path", "") for r in api.app.routes)
    assert "sms" not in service.configured_channels()
    monkeypatch.setenv("SMS_ENABLED", "1")
    with pytest.raises(RuntimeError, match="missing AT_USERNAME, AT_API_KEY, SMS_WEBHOOK_TOKEN"):
        sms.Config.from_env()
    monkeypatch.setenv("AT_USERNAME", "myapp")
    monkeypatch.setenv("AT_API_KEY", "k")
    monkeypatch.setenv("SMS_WEBHOOK_TOKEN", "short")
    with pytest.raises(RuntimeError, match="sandbox"):          # AT_SANDBOX defaults to 1; sandbox username is 'sandbox'
        sms.Config.from_env()
    monkeypatch.setenv("AT_SANDBOX", "0")
    with pytest.raises(RuntimeError, match="at least 20"):
        sms.Config.from_env()
    monkeypatch.setenv("SMS_WEBHOOK_TOKEN", "x" * 24)
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "0")
    with pytest.raises(RuntimeError, match="SMS_MAX_SEGMENTS"):
        sms.Config.from_env()
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "3")
    cfg = sms.Config.from_env()
    assert cfg.base_url == "https://api.africastalking.com" and cfg.max_segments == 3 and cfg.sender_id is None
    assert "x" * 24 not in repr(cfg) and "api_key" not in repr(cfg)


def test_sandbox_default_uses_sandbox_url(monkeypatch):
    for k, v in {"SMS_ENABLED": "1", "AT_USERNAME": "sandbox", "AT_API_KEY": "k", "SMS_WEBHOOK_TOKEN": "y" * 24}.items():
        monkeypatch.setenv(k, v)
    cfg = sms.Config.from_env()
    assert cfg.sandbox and cfg.base_url == "https://api.sandbox.africastalking.com" and cfg.max_segments == 4
    assert "at-key-abc" not in repr(CFG) and CFG.webhook_token not in repr(CFG)
    assert "sms" in service.configured_channels()


# --- outbound ---------------------------------------------------------------------------------------------------

class FakeAT:
    def __init__(self, status=200, code=101, body=None):
        self.requests, self.status, self.code, self.body = [], status, code, body

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        if self.body is not None:
            return httpx.Response(self.status, text=self.body)
        if self.status != 200:
            return httpx.Response(self.status, text="The supplied authentication is invalid")
        num = parse_qs(req.content.decode())["to"][0]
        return httpx.Response(201 if self.code < 200 else 200, json={"SMSMessageData": {
            "Message": "Sent to 1/1 Total Cost: GHS 0.0000",
            "Recipients": [{"statusCode": self.code, "number": num, "status": "Success" if self.code < 200 else "InvalidPhoneNumber",
                            "cost": "GHS 0.0000", "messageId": "ATXid_1"}]}})


def test_send_posts_documented_form_fields_with_apikey_header():
    at = FakeAT()
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    r = ch.send(FARMER, OutboundMessage(text="Wo bɛtumi adua.", audio_path="/tmp/ignored.wav"))
    assert r.ok and "1 segment" in r.detail and "UCS-2" in r.detail and FARMER not in r.detail
    req = at.requests[0]
    assert str(req.url) == "https://api.sandbox.africastalking.com/version1/messaging"
    assert req.headers["apikey"] == "at-key-abc" and req.headers["accept"] == "application/json"
    assert req.headers["content-type"] == "application/x-www-form-urlencoded"
    form = parse_qs(req.content.decode())
    assert form == {"username": ["sandbox"], "to": [FARMER], "message": ["Wo bɛtumi adua."]}  # no 'from' unless set


def test_sender_id_is_sent_as_from_when_configured():
    at = FakeAT()
    cfg = sms.Config("myapp", "k", "t" * 24, sender_id="AGRIREACH", sandbox=False)
    sms.SmsChannel(cfg, httpx.Client(transport=httpx.MockTransport(at))).send(FARMER, OutboundMessage(text="hi"))
    assert str(at.requests[0].url) == "https://api.africastalking.com/version1/messaging"
    assert parse_qs(at.requests[0].content.decode())["from"] == ["AGRIREACH"]


@pytest.mark.parametrize("at,expect", [
    (FakeAT(code=403), "403 InvalidPhoneNumber"),
    (FakeAT(status=401), "HTTP 401"),
    (FakeAT(body="not json"), "unreadable"),
])
def test_send_failures_are_reported_without_the_number(at, expect):
    r = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at))).send(FARMER, OutboundMessage(text="hi"))
    assert not r.ok and expect in r.detail and FARMER not in r.detail and "at-key-abc" not in r.detail


def test_network_error_and_bad_number_are_reported():
    def boom(req):
        raise httpx.ConnectError("down")
    assert "network error" in sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(boom))).send(
        FARMER, OutboundMessage(text="hi")).detail
    at = FakeAT()
    r = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at))).send("0000000017", OutboundMessage(text="hi"))
    assert not r.ok and "international" in r.detail and at.requests == []


# --- inbound ----------------------------------------------------------------------------------------------------

def callback(text, msg_id="at-in-1", sender=FARMER):
    return {"date": "2026-10-25 18:00:00", "from": sender, "id": msg_id, "text": text, "to": "12345",
            "networkCode": "99999", "linkId": "L1"}


def test_parse_callback_form():
    item = sms.parse(urlencode(callback("Hello")).encode())
    assert item == {"message_id": "at-in-1", "from": FARMER, "text": "Hello", "to": "12345"}
    assert sms.parse(b"from=%2B233000000017&id=x") is None   # no text field: not an incoming message


def test_inbound_route_requires_the_secret_path_token(monkeypatch):
    seen = []

    async def fake_process(cfg, items, channel=None, transcriber=None):
        seen.append(items)
    monkeypatch.setattr(sms, "process", fake_process)
    app = FastAPI()
    app.include_router(sms.router(CFG))
    c = TestClient(app)
    body = urlencode(callback("When should I plant maize in Ejura?"))
    hdr = {"Content-Type": "application/x-www-form-urlencoded"}
    assert c.post("/channels/sms/inbound/wrong-token", content=body, headers=hdr).status_code == 404
    assert c.post("/channels/sms/inbound/", content=body, headers=hdr).status_code in (404, 405)
    assert c.post(f"/channels/sms/inbound/{CFG.webhook_token}x", content=body, headers=hdr).status_code == 404
    assert seen == []
    assert c.post(f"/channels/sms/inbound/{CFG.webhook_token}", content=b"x" * 20_000, headers=hdr).status_code == 413
    assert c.post(f"/channels/sms/inbound/{CFG.webhook_token}", content=b"id=1", headers=hdr).status_code == 400
    r = c.post(f"/channels/sms/inbound/{CFG.webhook_token}", content=body, headers=hdr)
    assert r.status_code == 200 and seen[0][0]["message_id"] == "at-in-1"


def test_inbound_to_answer_end_to_end_through_officer_gate():
    at = FakeAT()
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    item = sms.parse(urlencode(callback("When should I harvest soybean in Tamale?")).encode())
    res = asyncio.run(sms.process(CFG, [item], channel=ch))
    assert res[0]["status"] == "pending_review"
    sent = [parse_qs(r.content.decode())["message"][0] for r in at.requests]
    assert sent == [service.ACK]
    assert asyncio.run(sms.process(CFG, [item], channel=ch)) == [{"duplicate": True}]  # AT retry, same id
    con = db.connect()
    cid = res[0]["case_id"]
    assert service.deliver(con, cid, {"sms": ch})["ok"] is False                       # not approved: nothing sent
    assert len(at.requests) == 1
    db.officer_decide(con, cid, officer="Ama Mensah", decision="edit_approve", edited_text="Harvest at 9 of 10 pods.")
    db.release_to_farmer(con, cid)
    out = service.deliver(con, cid, {"sms": ch})
    assert out["ok"] is True
    assert parse_qs(at.requests[-1].content.decode())["message"] == ["Harvest at 9 of 10 pods."]
    logs = json.dumps([dict(r) for r in con.execute("SELECT * FROM tool_log")])
    deliveries = json.dumps([dict(r) for r in con.execute("SELECT * FROM channel_deliveries")])
    assert FARMER not in logs and FARMER not in deliveries and mask_sender(FARMER) in logs
    assert "at-key-abc" not in logs


def test_overlong_approved_answer_is_recorded_as_failed_not_cut():
    at = FakeAT()
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    res = asyncio.run(sms.process(CFG, [sms.parse(urlencode(callback("When should I plant maize in Ejura?")).encode())],
                                  channel=ch))
    con = db.connect()
    cid = res[0]["case_id"]
    long_text = "Wear gloves when you spray. " * 30
    db.officer_decide(con, cid, officer="Ama Mensah", decision="edit_approve", edited_text=long_text)
    db.release_to_farmer(con, cid)
    out = service.deliver(con, cid, {"sms": ch})
    assert out["ok"] is False and "segments" in out["detail"]
    assert len(at.requests) == 1                                                         # only the ack went out


def test_consent_prompt_comes_first_over_sms(monkeypatch):
    monkeypatch.setenv("AGRIREACH_CONSENT", "1")
    at = FakeAT()
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    res = asyncio.run(sms.process(CFG, [sms.parse(urlencode(callback("When should I plant maize?")).encode())], channel=ch))
    assert res[0]["status"] == "awaiting_consent" and res[0]["case_id"] is None
    prompt = parse_qs(at.requests[0].content.decode())["message"][0]
    assert prompt.startswith("AgriReach:") and sms.measure(prompt).segments <= CFG.max_segments
    stop = asyncio.run(sms.process(CFG, [sms.parse(urlencode(callback("STOP", "at-in-2")).encode())], channel=ch))
    assert stop[0]["status"] == "forgotten"


def test_empty_text_is_ignored_and_logged_masked():
    at = FakeAT()
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(at)))
    assert asyncio.run(sms.process(CFG, [sms.parse(urlencode(callback("   ")).encode())], channel=ch)) == []
    logs = json.dumps([dict(r) for r in db.connect().execute("SELECT * FROM tool_log")])
    assert "ignored" in logs and FARMER not in logs and at.requests == []


def test_secret_token_is_redacted_from_the_access_log():
    import logging
    sms.router(CFG)
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "POST", f"/channels/sms/inbound/{CFG.webhook_token}", "1.1", 200), None)
    for f in logging.getLogger("uvicorn.access").filters:
        f.filter(rec)
    assert CFG.webhook_token not in rec.getMessage() and "/channels/sms/inbound/***" in rec.getMessage()
