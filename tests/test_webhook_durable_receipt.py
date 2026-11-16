"""Webhook durability regressions using disposable SQLite and no network calls."""
import hashlib
import hmac
import json
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agrireach import db
from agrireach.channels import sms, whatsapp


def test_sms_ack_requires_committed_inbox(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "sms.sqlite"))
    cfg = sms.Config("sandbox", "unused", "s" * 24)
    seen = []

    async def worker(_cfg, item):
        row = db.connect().execute(
            "SELECT state,sender_id FROM channel_inbox WHERE channel='sms' AND message_id=?",
            (item["message_id"],)).fetchone()
        assert row is not None and row["state"] == "pending"
        seen.append(row["sender_id"])

    monkeypatch.setattr(sms, "process_durable", worker)
    app = FastAPI()
    app.include_router(sms.router(cfg))
    client = TestClient(app)
    body = urlencode({"id": "sms-1", "from": "+233000000001", "text": "maize"})
    url = "/channels/sms/inbound/" + cfg.webhook_token
    first = client.post(url, content=body)
    second = client.post(url, content=body)
    assert first.status_code == 200 and first.json()["duplicate"] is False
    assert second.status_code == 200 and second.json()["duplicate"] is True
    assert seen == ["+233000000001"]


def test_whatsapp_ack_requires_committed_inbox(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "wa.sqlite"))
    cfg = whatsapp.Config("verify", "secret", "unused", "1234")
    seen = []

    async def worker(_cfg, item):
        row = db.connect().execute(
            "SELECT state,sender_id FROM channel_inbox WHERE channel='whatsapp' AND message_id=?",
            (item["message_id"],)).fetchone()
        assert row is not None and row["state"] == "pending"
        seen.append(row["sender_id"])

    monkeypatch.setattr(whatsapp, "process_durable", worker)
    app = FastAPI()
    app.include_router(whatsapp.router(cfg))
    client = TestClient(app)
    payload = {"entry": [{"changes": [{"field": "messages", "value": {
        "messages": [{"id": "wa-1", "from": "233000000001", "type": "text",
                      "text": {"body": "maize"}}]}}]}]}
    body = json.dumps(payload).encode()
    headers = {"X-Hub-Signature-256": "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()}
    first = client.post("/channels/whatsapp/webhook", content=body, headers=headers)
    second = client.post("/channels/whatsapp/webhook", content=body, headers=headers)
    assert first.status_code == 200 and first.json()["queued"] == 1
    assert second.status_code == 200 and second.json()["queued"] == 0
    assert seen == ["233000000001"]
