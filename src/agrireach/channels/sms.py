"""SMS adapter for Africa's Talking. CODE ONLY: no account, never sent or received a real SMS, off by default.

It is enabled only when SMS_ENABLED=1 and the required settings below are present; the API then mounts
POST /channels/sms/inbound/<SMS_WEBHOOK_TOKEN>. Setup, and what is still missing before real use: docs/sms-setup.md.

  AT_USERNAME          Africa's Talking app username ('sandbox' in the sandbox)
  AT_API_KEY           API key, sent in the 'apiKey' request header
  SMS_WEBHOOK_TOKEN    your own random string (20+ characters); the secret last part of the inbound callback URL
  AT_SENDER_ID         optional registered sender ID or short code, sent as 'from'; AT's default sender if empty
  AT_SANDBOX           1 (default) = api.sandbox.africastalking.com, 0 = live api.africastalking.com
  SMS_MAX_SEGMENTS     most SMS parts one message may use (default 4); longer texts are refused, never cut

Security: Africa's Talking does not sign its callbacks, so the inbound route is protected only by the secret token in
its path (constant-time compare, 404 otherwise) and by HTTPS. The token is redacted from uvicorn's access log.
Sender numbers are masked in logs and in delivery details; the API key is never logged.

Length: plain text goes as GSM-7 (160 characters, or 153 per part when split; [ ] { } ~ ^ | \\ and the euro sign
take two). Any other character, such as the Twi and Dagbani letters ɛ ɔ ŋ, makes the whole message UCS-2
(70 characters, or 67 per part). A text over SMS_MAX_SEGMENTS parts is not sent and the officer is told to shorten
it; no sentence (a pesticide safety line, say) is ever dropped to make it fit.
"""
from __future__ import annotations

import hmac
import logging
import math
import os
import re
from dataclasses import dataclass
from urllib.parse import parse_qs

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from agrireach import db
from agrireach.channels import service
from agrireach.channels.base import InboundMessage, OutboundMessage, SendResult, mask_sender

LIVE_BASE = "https://api.africastalking.com"
SANDBOX_BASE = "https://api.sandbox.africastalking.com"
MAX_BODY_BYTES = 16_000      # an incoming-SMS callback is a short form; anything bigger is refused
ACCEPTED = {100: "Processed", 101: "Sent", 102: "Queued"}  # accepted by AT, not yet delivered to the handset
PHONE_RE = re.compile(r"^\+\d{7,15}$")

# GSM 03.38 basic character set (without the escape character) and its extension table (two units each).
GSM7_BASIC = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                 "ÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM7_EXT = set("^{}\\[~]|€\f")


@dataclass(frozen=True)
class Length:
    encoding: str            # 'GSM-7' or 'UCS-2'
    units: int               # septets for GSM-7, UTF-16 code units for UCS-2
    segments: int            # SMS parts the network will bill and deliver
    non_gsm: tuple = ()      # characters that forced UCS-2


def measure(text: str) -> Length:
    non_gsm = tuple(dict.fromkeys(c for c in text if c not in GSM7_BASIC and c not in GSM7_EXT))
    if non_gsm:
        units, single, multi, enc = len(text.encode("utf-16-le")) // 2, 70, 67, "UCS-2"
    else:
        units, single, multi, enc = sum(2 if c in GSM7_EXT else 1 for c in text), 160, 153, "GSM-7"
    segments = 0 if units == 0 else 1 if units <= single else math.ceil(units / multi)
    return Length(enc, units, segments, non_gsm)


def _parts(n: int) -> str:
    return f"{n} segment" + ("" if n == 1 else "s")


def max_parts() -> int:
    """SMS_MAX_SEGMENTS for officer prompts (default 4). Config.from_env() rejects a bad value at startup."""
    try:
        n = int(os.getenv("SMS_MAX_SEGMENTS", "4"))
    except ValueError:
        return 4
    return n if n >= 1 else 4


def _cap(limit: int, unicode: bool) -> int:
    single, multi = (70, 67) if unicode else (160, 153)
    return single if limit == 1 else multi * limit


def limit_fact(limit: int | None = None) -> str:
    """The SMS limit in plain words, shown to the officer on every SMS case."""
    n = limit or max_parts()
    return (f"SMS limit for this farmer: {n} parts, which is {_cap(n, False)} characters of standard text, or "
            f"{_cap(n, True)} if the text has any Twi, Ga, Ewe or Dagbani letter (ɛ ɔ ŋ ɣ), curly quote or emoji")


def _too_long(text: str, limit: int) -> tuple[str, int] | None:
    m = measure(text)
    if m.segments <= limit:
        return None
    why = f"Unicode because of {', '.join(m.non_gsm[:8])}" if m.encoding == "UCS-2" else "standard SMS characters"
    return (f"too long for SMS: this text needs {m.segments} parts ({why}); the limit is {limit}. "
            f"Shorten it to {_cap(limit, m.encoding == 'UCS-2')} characters or fewer"), m.units


def length_prompt(text: str, limit: int | None = None) -> str | None:
    """Approval prompt for an SMS case whose farmer text won't fit; None if it fits. Never shortens anything."""
    hit = _too_long(text, limit or max_parts())
    return None if hit is None else f"{hit[0]} before approving (it is {hit[1]} now). Nothing is cut automatically."


def check(text: str, limit: int | None = None) -> dict:
    """Length facts for the officer's current farmer text (the /sms-check route)."""
    m, n = measure(text), limit or max_parts()
    return {"parts": m.segments, "limit": n, "encoding": "Unicode" if m.encoding == "UCS-2" else "standard",
            "characters": m.units, "max_characters": _cap(n, m.encoding == "UCS-2"),
            "unicode_because_of": list(m.non_gsm[:8]), "prompt": length_prompt(text, n)}


@dataclass(frozen=True)
class Config:
    username: str
    api_key: str
    webhook_token: str
    sender_id: str | None = None
    sandbox: bool = True
    max_segments: int = 4

    @property
    def base_url(self) -> str:
        return SANDBOX_BASE if self.sandbox else LIVE_BASE

    @classmethod
    def from_env(cls) -> "Config":
        missing = [k for k in ("AT_USERNAME", "AT_API_KEY", "SMS_WEBHOOK_TOKEN") if not os.getenv(k)]
        if missing:
            raise RuntimeError(f"SMS adapter is enabled but not configured: missing {', '.join(missing)}")
        username, token = os.environ["AT_USERNAME"], os.environ["SMS_WEBHOOK_TOKEN"]
        sandbox = os.getenv("AT_SANDBOX", "1") != "0"
        if sandbox and username != "sandbox":
            raise RuntimeError("SMS adapter misconfigured: AT_SANDBOX=1 (the default) but AT_USERNAME is not "
                               "'sandbox' (Africa's Talking's sandbox username is always 'sandbox'). "
                               "Set AT_SANDBOX=0 only for a live app.")
        if len(token) < 20:
            raise RuntimeError("SMS adapter misconfigured: SMS_WEBHOOK_TOKEN must be at least 20 characters "
                               "(a long random string; it is the only protection on the inbound route)")
        try:
            max_segments = int(os.getenv("SMS_MAX_SEGMENTS", "4"))
        except ValueError:
            max_segments = 0
        if max_segments < 1:
            raise RuntimeError("SMS adapter misconfigured: SMS_MAX_SEGMENTS must be a whole number of 1 or more")
        return cls(username, os.environ["AT_API_KEY"], token, os.getenv("AT_SENDER_ID") or None, sandbox, max_segments)

    def __repr__(self) -> str:  # never print the key or the webhook token
        return (f"Config(username={self.username}, sandbox={self.sandbox}, sender_id={self.sender_id}, "
                f"max_segments={self.max_segments})")


def enabled() -> bool:
    return os.getenv("SMS_ENABLED", "0") == "1"


class SmsChannel:
    name = "sms"

    def __init__(self, cfg: Config, client: httpx.Client | None = None):
        self.cfg, self.client = cfg, client or httpx.Client(timeout=30)

    def send(self, recipient_id: str, message: OutboundMessage) -> SendResult:
        """Text only (an audio_path is ignored). Refuses, rather than cuts, a text over the segment limit."""
        if not PHONE_RE.match(recipient_id or ""):
            return SendResult(False, "recipient is not an international number (+ and country code)")
        m = measure(message.text)
        hit = _too_long(message.text, self.cfg.max_segments)
        if hit:  # backstop: the officer is prompted, and approval refused, before it gets here
            return SendResult(False, f"not sent, nothing was cut: {hit[0]} (it is {hit[1]} now)")
        form = {"username": self.cfg.username, "to": recipient_id, "message": message.text}
        if self.cfg.sender_id:
            form["from"] = self.cfg.sender_id
        try:
            r = self.client.post(f"{self.cfg.base_url}/version1/messaging", data=form,
                                 headers={"apiKey": self.cfg.api_key, "Accept": "application/json"})
        except httpx.HTTPError as e:
            return SendResult(False, f"network error: {type(e).__name__}")
        scrub = lambda s: str(s).replace(recipient_id, mask_sender(recipient_id))[:160]  # noqa: E731
        if r.status_code >= 400:
            return SendResult(False, f"HTTP {r.status_code}: {scrub(r.text)}")
        try:
            data = r.json()["SMSMessageData"]
            rec = (data.get("Recipients") or [{}])[0]
        except (ValueError, KeyError, TypeError, AttributeError):
            return SendResult(False, f"unreadable response from Africa's Talking (HTTP {r.status_code})")
        code = rec.get("statusCode")
        if code in ACCEPTED:
            return SendResult(True, f"accepted by Africa's Talking (status {code} {ACCEPTED[code]}; "
                                    f"{_parts(m.segments)}, {m.encoding})")
        return SendResult(False, f"rejected by Africa's Talking: {code} {scrub(rec.get('status') or data.get('Message', ''))}")


def parse(raw: bytes) -> dict | None:
    """An incoming-message callback (application/x-www-form-urlencoded). None if it has no sender or no text field."""
    try:
        form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8"), keep_blank_values=True).items()}
    except UnicodeDecodeError:
        return None
    if "from" not in form or "text" not in form:
        return None
    return {"message_id": form.get("id") or None, "from": form["from"], "text": form["text"], "to": form.get("to", "")}


async def process(cfg: Config, items: list[dict], channel: SmsChannel | None = None, transcriber=None) -> list:
    """Turn parsed callbacks into cases (run after the callback has already answered 200)."""
    ch = channel or SmsChannel(cfg)
    con = db.connect()
    results = []
    for it in items:
        sender = it.get("from") or ""
        try:
            if not PHONE_RE.match(sender) or not (it.get("text") or "").strip():
                db.log(con, "channel:sms", "inbound_message", {"from": mask_sender(sender)},
                       "ignored: empty text or not an international number", ok=False)
                continue
            msg = InboundMessage("sms", sender, text=it["text"], message_id=it.get("message_id"))
            results.append(await service.handle_inbound(msg, channel=ch, transcriber=transcriber, con=con))
        except Exception as e:
            db.log(con, "channel:sms", "inbound_message", {"from": mask_sender(sender)},
                   f"FAILED: {type(e).__name__}", ok=False)
    return results


class _RedactToken(logging.Filter):
    """Keep the secret path token out of uvicorn's access log."""

    def __init__(self, token: str):
        super().__init__()
        self.token = token

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(a.replace(self.token, "***") if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = record.msg.replace(self.token, "***")
        return True


def router(cfg: Config) -> APIRouter:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _RedactToken) and f.token == cfg.webhook_token for f in access.filters):
        access.addFilter(_RedactToken(cfg.webhook_token))
    r = APIRouter()

    @r.post("/channels/sms/inbound/{token}")
    async def receive(token: str, request: Request, background: BackgroundTasks):
        if not hmac.compare_digest(token.encode(), cfg.webhook_token.encode()):
            raise HTTPException(404, "not found")
        if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
            raise HTTPException(413, "payload too large")
        raw = await request.body()
        if len(raw) > MAX_BODY_BYTES:
            raise HTTPException(413, "payload too large")
        item = parse(raw)
        if item is None:
            raise HTTPException(400, "not an incoming-message callback")
        background.add_task(process, cfg, [item])
        return {"ok": True}

    return r
