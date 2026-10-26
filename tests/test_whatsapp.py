"""WhatsApp Cloud API adapter, offline only: signature checks, verification, parsing, and HTTP via a mock transport.
Numbers here are fictional (555-01xx range). Nothing is registered with Meta."""
import asyncio
import hashlib
import hmac
import json

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agrireach import api, db
from agrireach.channels import service, whatsapp
from agrireach.channels.base import OutboundMessage, mask_sender

CFG = whatsapp.Config("verify-me", "app-secret", "token-abc", "1234567890", graph_base="https://graph.test")
FARMER = "15555550100"


def sign(body: bytes, secret="app-secret") -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def payload(*messages):
    return {"object": "whatsapp_business_account", "entry": [{"id": "WABA", "changes": [
        {"field": "messages", "value": {"messaging_product": "whatsapp", "messages": list(messages),
                                        "statuses": [{"id": "wamid.status", "status": "delivered"}]}}]}]}


TEXT = {"from": FARMER, "id": "wamid.T1", "type": "text", "text": {"body": "When should I harvest soybean in Tamale?"}}
AUDIO = {"from": FARMER, "id": "wamid.A1", "type": "audio",
         "audio": {"id": "MEDIA1", "mime_type": "audio/ogg; codecs=opus", "voice": True}}


def test_signature_verification():
    body = json.dumps(payload(TEXT)).encode()
    assert whatsapp.verify_signature("app-secret", body, sign(body))
    assert not whatsapp.verify_signature("app-secret", body + b" ", sign(body))         # body changed
    assert not whatsapp.verify_signature("app-secret", body, sign(body, "other"))       # wrong secret
    assert not whatsapp.verify_signature("app-secret", body, None)                      # header missing
    assert not whatsapp.verify_signature("app-secret", body, sign(body)[7:])            # no sha256= prefix
    assert not whatsapp.verify_signature("", body, sign(body, ""))                      # no secret configured


def test_subscription_verification():
    assert whatsapp.verify_subscription(CFG, "subscribe", "verify-me", "123") == "123"
    assert whatsapp.verify_subscription(CFG, "subscribe", "wrong", "123") is None
    assert whatsapp.verify_subscription(CFG, "unsubscribe", "verify-me", "123") is None


def test_parse_keeps_text_and_voice_notes_and_ignores_statuses():
    items = whatsapp.parse(payload(TEXT, AUDIO, {"from": FARMER, "id": "wamid.I1", "type": "image"}))
    assert [i["type"] for i in items] == ["text", "audio", "image"]
    assert items[0]["text"].startswith("When") and items[1]["audio_id"] == "MEDIA1"


def test_webhook_routes_verify_and_reject_bad_signatures(monkeypatch):
    seen = []

    async def fake_process(cfg, items):
        seen.append(items)
    monkeypatch.setattr(whatsapp, "process", fake_process)
    app = FastAPI()
    app.include_router(whatsapp.router(CFG))
    c = TestClient(app)
    ok = c.get("/channels/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                     "hub.challenge": "42"})
    assert ok.status_code == 200 and ok.text == "42"
    assert c.get("/channels/whatsapp/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "x",
                                                       "hub.challenge": "42"}).status_code == 403
    body = json.dumps(payload(TEXT)).encode()
    assert c.post("/channels/whatsapp/webhook", content=body,
                  headers={"X-Hub-Signature-256": sign(body, "forged")}).status_code == 401
    assert c.post("/channels/whatsapp/webhook", content=body).status_code == 401
    assert seen == []  # nothing processed without a valid signature
    r = c.post("/channels/whatsapp/webhook", content=body, headers={"X-Hub-Signature-256": sign(body)})
    assert r.status_code == 200 and len(seen) == 1 and seen[0][0]["message_id"] == "wamid.T1"


def test_adapter_is_off_by_default_and_needs_full_config(monkeypatch):
    assert not whatsapp.enabled()
    assert not any("whatsapp" in getattr(r, "path", "") for r in api.app.routes)
    monkeypatch.setenv("WHATSAPP_ENABLED", "1")
    with pytest.raises(RuntimeError, match="missing"):
        whatsapp.Config.from_env()
    assert "token-abc" not in repr(CFG) and "app-secret" not in repr(CFG)


class FakeGraph:
    """Mock Graph API: media lookup, media download, and message send."""

    def __init__(self, send_status=200):
        self.requests, self.send_status = [], send_status

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.requests.append(req)
        assert req.headers["authorization"] == "Bearer token-abc"
        if req.url.path == "/v26.0/MEDIA1":
            return httpx.Response(200, json={"url": "https://media.test/MEDIA1", "mime_type": "audio/ogg; codecs=opus"})
        if req.url.host == "media.test":
            return httpx.Response(200, content=b"OggS-fake-audio")
        if req.url.path == "/v26.0/1234567890/messages":
            if self.send_status != 200:
                return httpx.Response(self.send_status, json={"error": {"code": 131047, "message": "Re-engagement message"}})
            return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})
        return httpx.Response(404)


class FakeTranscriber:
    def transcribe(self, path):
        from agrireach.channels import stt
        return stt.check(stt.Transcript("When should I harvest my soybean? I farm near Tamale.", "en", 0.98, 3.0, "fake"))


def test_voice_note_end_to_end_with_mocked_graph_api_and_gate():
    graph = FakeGraph()
    ch = whatsapp.WhatsAppChannel(CFG, httpx.Client(transport=httpx.MockTransport(graph)))
    res = asyncio.run(whatsapp.process(CFG, whatsapp.parse(payload(AUDIO)), channel=ch, transcriber=FakeTranscriber()))
    assert res[0]["status"] == "pending_review"
    sends = [json.loads(r.content) for r in graph.requests if r.url.path.endswith("/messages")]
    assert [s["text"]["body"] for s in sends] == [service.ACK] and sends[0]["to"] == FARMER
    # A webhook retry with the same message id does not create a second case.
    again = asyncio.run(whatsapp.process(CFG, whatsapp.parse(payload(AUDIO)), channel=ch, transcriber=FakeTranscriber()))
    assert again == [{"duplicate": True}]
    con = db.connect()
    cid = res[0]["case_id"]
    assert service.deliver(con, cid, {"whatsapp": ch})["ok"] is False  # not approved: nothing sent
    db.officer_decide(con, cid, officer="Ama Mensah", decision="edit_approve", edited_text="Harvest at 9 of 10 pods.", farmer_text="Harvest at 9 of 10 pods.", expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
    db.release_to_farmer(con, cid)
    assert service.deliver(con, cid, {"whatsapp": ch})["ok"] is True
    sends = [json.loads(r.content) for r in graph.requests if r.url.path.endswith("/messages")]
    assert sends[-1]["text"]["body"] == "Harvest at 9 of 10 pods."
    all_logs = json.dumps([dict(r) for r in con.execute("SELECT * FROM tool_log")])
    assert FARMER not in all_logs and mask_sender(FARMER) in all_logs and "token-abc" not in all_logs


def test_send_failure_is_reported_not_hidden():
    ch = whatsapp.WhatsAppChannel(CFG, httpx.Client(transport=httpx.MockTransport(FakeGraph(send_status=400))))
    r = ch.send(FARMER, OutboundMessage(text="hello"))
    assert not r.ok and "131047" in r.detail
    assert not ch.send(FARMER, OutboundMessage(text="x" * 5000)).ok
