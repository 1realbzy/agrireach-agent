"""WhatsApp Cloud API adapter. CODE ONLY: not registered with Meta, not deployed, off by default.

It is enabled only when WHATSAPP_ENABLED=1 and every setting below is present; the API then mounts
GET/POST /channels/whatsapp/webhook. Setup, and what is still missing before real use: docs/whatsapp-setup.md.

  WHATSAPP_VERIFY_TOKEN     your own random string, typed into Meta's webhook settings (GET verification)
  WHATSAPP_APP_SECRET       the Meta app secret; every POST must carry a valid X-Hub-Signature-256 for it
  WHATSAPP_ACCESS_TOKEN     a system-user access token with whatsapp_business_messaging permission
  WHATSAPP_PHONE_NUMBER_ID  the business phone number id messages are sent from
  WHATSAPP_GRAPH_VERSION    Graph API version, default v26.0 (check Meta's changelog and pin deliberately)

Security: the POST body is authenticated (HMAC-SHA256 of the raw bytes with the app secret, constant-time compare)
before it is parsed; message ids are de-duplicated because Meta retries; sender numbers are masked in logs; tokens
are never logged. Replies are text only (WhatsApp does not accept WAV audio; see the setup doc).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

from agrireach import db
from agrireach.channels import service
from agrireach.channels.base import InboundMessage, OutboundMessage, SendResult, mask_sender

MAX_BODY_BYTES = 3_000_000   # Meta documents webhook payloads up to 3 MB; media arrives as an id, not bytes
MAX_TEXT_CHARS = 4096        # WhatsApp text message body limit
AUDIO_SUFFIX = {"audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/aac": ".aac", "audio/amr": ".amr"}


@dataclass(frozen=True)
class Config:
    verify_token: str
    app_secret: str
    access_token: str
    phone_number_id: str
    graph_version: str = "v26.0"
    graph_base: str = "https://graph.facebook.com"

    @classmethod
    def from_env(cls) -> "Config":
        missing = [k for k in ("WHATSAPP_VERIFY_TOKEN", "WHATSAPP_APP_SECRET", "WHATSAPP_ACCESS_TOKEN",
                               "WHATSAPP_PHONE_NUMBER_ID") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"WhatsApp adapter is enabled but not configured: missing {', '.join(missing)}")
        return cls(os.environ["WHATSAPP_VERIFY_TOKEN"], os.environ["WHATSAPP_APP_SECRET"],
                   os.environ["WHATSAPP_ACCESS_TOKEN"], os.environ["WHATSAPP_PHONE_NUMBER_ID"],
                   os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0"))

    def url(self, path: str) -> str:
        return f"{self.graph_base}/{self.graph_version}/{path.lstrip('/')}"

    def __repr__(self) -> str:  # never print secrets
        return f"Config(phone_number_id=***{self.phone_number_id[-2:]}, graph_version={self.graph_version})"


def enabled() -> bool:
    return os.getenv("WHATSAPP_ENABLED", "0") == "1"


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """X-Hub-Signature-256 is 'sha256=' + hex HMAC-SHA256 of the raw request body, keyed with the app secret."""
    if not app_secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):].strip().lower())


def verify_subscription(cfg: Config, mode: str | None, token: str | None, challenge: str | None) -> str | None:
    """GET verification: return the challenge to echo, or None to refuse."""
    if mode == "subscribe" and token is not None and challenge is not None and \
            hmac.compare_digest(token.encode(), cfg.verify_token.encode()):
        return challenge
    return None


def parse(payload: dict) -> list[dict]:
    """Inbound user messages from a webhook payload (statuses and other fields are ignored)."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            for m in (change.get("value") or {}).get("messages") or []:
                item = {"message_id": m.get("id"), "from": m.get("from"), "type": m.get("type")}
                if m.get("type") == "text":
                    item["text"] = (m.get("text") or {}).get("body", "")
                elif m.get("type") == "audio":
                    item["audio_id"] = (m.get("audio") or {}).get("id")
                    item["mime_type"] = (m.get("audio") or {}).get("mime_type", "")
                out.append(item)
    return out


class WhatsAppChannel:
    name = "whatsapp"

    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg, self.client = cfg, client or httpx.Client(timeout=30)

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.access_token}"}

    def send(self, recipient_id: str, message: OutboundMessage) -> SendResult:
        if len(message.text) > MAX_TEXT_CHARS:
            return SendResult(False, f"text is {len(message.text)} chars, over WhatsApp's {MAX_TEXT_CHARS}; "
                                     "officer should shorten it")
        body = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": recipient_id,
                "type": "text", "text": {"preview_url": False, "body": message.text}}
        try:
            r = self.client.post(self.cfg.url(f"{self.cfg.phone_number_id}/messages"), json=body, headers=self._auth())
        except httpx.HTTPError as e:
            return SendResult(False, f"network error: {type(e).__name__}")
        if r.status_code >= 400:
            # e.g. outside the 24-hour customer-service window a template message is required (see setup doc)
            err = (r.json().get("error") or {}) if r.headers.get("content-type", "").startswith("application/json") else {}
            return SendResult(False, f"HTTP {r.status_code} code {err.get('code', '?')}: {str(err.get('message', ''))[:120]}")
        try:
            provider_id = r.json()["messages"][0]["id"]
            if not isinstance(provider_id, str) or not provider_id:
                raise ValueError("missing message id")
        except (ValueError, KeyError, IndexError, TypeError):
            return SendResult(False, "outcome unknown: unreadable WhatsApp success response", "unknown")
        return SendResult(True, "accepted by WhatsApp Cloud API", provider_id=provider_id)

    def download_media(self, media_id: str) -> tuple[bytes, str]:
        meta = self.client.get(self.cfg.url(media_id), headers=self._auth())
        meta.raise_for_status()
        info = meta.json()
        data = self.client.get(info["url"], headers=self._auth())
        data.raise_for_status()
        return data.content, info.get("mime_type", "")


async def process(cfg: Config, items: list[dict], channel: WhatsAppChannel | None = None, transcriber=None) -> list:
    """Turn parsed webhook messages into cases (run after the webhook has already answered 200)."""
    ch = channel or WhatsAppChannel(cfg)
    con = db.connect()
    results = []
    for it in items:
        sender = it.get("from") or ""
        try:
            if it["type"] == "text":
                msg = InboundMessage("whatsapp", sender, text=it.get("text"), message_id=it["message_id"])
            elif it["type"] == "audio" and it.get("audio_id"):
                data, mime = ch.download_media(it["audio_id"])
                suffix = AUDIO_SUFFIX.get(mime.split(";")[0].strip(), ".bin")
                msg = InboundMessage("whatsapp", sender, audio_path=service.save_audio(data, suffix),
                                     message_id=it["message_id"])
            else:
                db.log(con, "channel:whatsapp", "inbound_message", {"from": mask_sender(sender), "type": it["type"]},
                       "ignored: only text and voice notes are handled", ok=False)
                continue
            results.append(await service.handle_inbound(msg, channel=ch, transcriber=transcriber, con=con))
        except Exception as e:
            db.log(con, "channel:whatsapp", "inbound_message", {"from": mask_sender(sender)},
                   f"FAILED: {type(e).__name__}", ok=False)
    return results


def router(cfg: Config) -> APIRouter:
    r = APIRouter()

    @r.get("/channels/whatsapp/webhook")
    def verify(request: Request):
        q = request.query_params
        challenge = verify_subscription(cfg, q.get("hub.mode"), q.get("hub.verify_token"), q.get("hub.challenge"))
        if challenge is None:
            raise HTTPException(403, "verification failed")
        return PlainTextResponse(challenge)

    @r.post("/channels/whatsapp/webhook")
    async def receive(request: Request, background: BackgroundTasks):
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, "payload too large")
        if not verify_signature(cfg.app_secret, raw, request.headers.get("x-hub-signature-256")):
            raise HTTPException(401, "bad signature")
        try:
            items = parse(json.loads(raw))
        except ValueError:
            raise HTTPException(400, "invalid JSON")
        background.add_task(process, cfg, items)
        return {"ok": True, "messages": len(items)}

    return r
