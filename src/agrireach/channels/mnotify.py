"""mNotify quick-SMS adapter for an administrative acknowledgement.

Official contract inspected from https://readthedocs.mnotify.com/ (BMS API):

* POST https://api.mnotify.com/api/sms/quick?key=<API key>
* JSON fields used: recipient (array of numbers), sender (at most 11 characters),
  message. The immediate-send sample uses local numbers, is_schedule=false,
  and an empty schedule_date.
* Success sample: {"status":"success","code":"2000",...,"summary":{"_id": ...}}.
  Code 2000 means the provider accepted the campaign. It is not handset delivery.
  The delivery-report GET is a separate call and is not used here.
* Documented refusal codes include 4000-4015. HTTP 401 is unauthorized.
* HTTP and provider body codes are interpreted separately.

Missing or invalid configuration never calls another provider. Africa's Talking
is not used. A simulated result is labelled simulated and is not handset delivery.
"""
from __future__ import annotations

import logging
import os
from http import HTTPStatus
from dataclasses import dataclass
from urllib.parse import quote, quote_plus, urlparse

import httpx

from agrireach.phone import to_local

DEFAULT_BASE = "https://api.mnotify.com"
QUICK_PATH = "/api/sms/quick"
MODES = ("disabled", "simulated", "live")
logger = logging.getLogger(__name__)

# Uvicorn configures logging before importing the app. Sanitize the emitting
# transport loggers before any handler sees a record, regardless of request
# context or thread. Keep only fixed operation names and standard HTTP status.
_HTTPX_REQUEST = 'HTTP Request: %s %s "%s %d %s"'
_HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_HEADER_TRACE_EVENTS = {
    "receive_response_headers.started",
    "receive_response_headers.complete",
    "receive_response_headers.failed",
}


class _ProviderLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = "HTTP transport activity"
        if record.name == "httpx" and record.msg == _HTTPX_REQUEST:
            method, _, _, code, _ = record.args
            method = method if method in _HTTP_METHODS else "OTHER"
            try:
                status = HTTPStatus(code)
            except ValueError:
                message = f"HTTP request: {method}"
            else:
                message = f"HTTP request: {method} {status.value} {status.phrase}"
        elif record.name.startswith("httpcore.") and isinstance(record.msg, str):
            event = record.msg.partition(" ")[0]
            if event in _HEADER_TRACE_EVENTS:
                message = event
        record.msg, record.args = message, ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


# Filters must be on the emitting loggers: parent logger filters are skipped
# during propagation. HTTPX logs the full URL before calling response hooks.
_provider_log_filter = _ProviderLogFilter()
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
              "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_name).addFilter(_provider_log_filter)

REJECTIONS = {
    "4000": "numeric sender IDs are not allowed",
    "4001": "recipient, sender and message must not be empty",
    "4002": "schedule date is empty while scheduling is on",
    "4003": "sender is longer than 11 characters",
    "4004": "credit is not enough",
    "4005": "the scheduled time is too soon",
    "4006": "message and message id conflict",
    "4007": "message id does not exist",
    "4008": "group is missing or empty",
    "4009": "voice file and voice id conflict",
    "4010": "voice file is too large",
    "4011": "voice upload failed",
    "4012": "voice bit rate is too high",
    "4013": "voice id does not exist",
    "4014": "sender ID is not registered",
    "4015": "sender name and purpose must not be empty",
}


@dataclass(frozen=True)
class ProviderResult:
    outcome: str
    detail: str
    provider_id: str | None = None
    simulated: bool = False

    @property
    def handset_delivered(self) -> bool:
        """Provider acceptance is never reported as delivery to a handset."""
        return False


@dataclass(frozen=True)
class LiveConfig:
    api_key: str
    sender_id: str
    base_url: str = DEFAULT_BASE

    def __repr__(self) -> str:
        return f"LiveConfig(sender_id={self.sender_id!r}, base_url={self.base_url!r})"


def mode() -> str:
    """Default is disabled. An unrecognised value is disabled, never live."""
    value = os.getenv("MNOTIFY_SMS_MODE", "disabled").strip().lower()
    return value if value in MODES else "disabled"


def live_config() -> LiveConfig | None:
    """Return live settings, or None when anything required is missing or unsafe."""
    if mode() != "live":
        return None
    key = os.getenv("MNOTIFY_API_KEY", "").strip()
    sender = os.getenv("MNOTIFY_SENDER_ID", "").strip()
    base = os.getenv("MNOTIFY_API_BASE", DEFAULT_BASE).strip().rstrip("/") or DEFAULT_BASE
    host = urlparse(base).hostname
    if not key or not sender or len(sender) > 11 or sender.isdigit():
        return None
    if host != "api.mnotify.com" or not base.startswith("https://"):
        return None
    return LiveConfig(key, sender, base)


def simulate(case_id: int) -> ProviderResult:
    """Record a local result. Nothing is sent."""
    return ProviderResult(
        "accepted",
        "simulated: acknowledgement recorded locally; no message was sent to a phone",
        f"simulated-{case_id}",
        True,
    )


def transmit(phone_e164: str, message: str, *, client: httpx.Client | None = None) -> ProviderResult:
    """POST one quick SMS. The client is injectable so tests never touch the network."""
    if mode() != "live":
        return ProviderResult("definitely_failed", "mNotify live mode is not enabled; no message was sent")
    cfg = live_config()
    if cfg is None:
        return ProviderResult("definitely_failed", "mNotify is not configured; no message was sent")
    local = to_local(phone_e164)
    payload = {"recipient": [local], "sender": cfg.sender_id, "message": message,
               "is_schedule": False, "schedule_date": ""}
    own = client is None
    http = client or httpx.Client(timeout=30, trust_env=False)
    # The provider requires the key in the query. Its response may echo it.
    values = {cfg.api_key, quote(cfg.api_key, safe=""), quote_plus(cfg.api_key),
              repr(cfg.api_key)[1:-1], repr(cfg.api_key.encode())[2:-1], phone_e164, local}
    try:
        try:
            response = http.post(
                f"{cfg.base_url}{QUICK_PATH}",
                params={"key": cfg.api_key},
                json=payload,
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        except (httpx.ConnectTimeout, httpx.ConnectError):
            return ProviderResult("definitely_failed", "not sent: could not connect to mNotify")
        except (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.ReadError,
                httpx.WriteError, httpx.RemoteProtocolError):
            return ProviderResult("unknown", "outcome unknown: the mNotify request timed out or was interrupted")
        except httpx.HTTPError:
            return ProviderResult("unknown", "outcome unknown: the mNotify request failed without a readable response")
        except Exception:
            # A client hook or transport can raise an exception containing the
            # authenticated URL. Keep the failure visible without its raw details.
            logger.warning("Unexpected client error during the mNotify request")
            return ProviderResult("unknown", "outcome unknown: the mNotify client failed")
        try:
            body = response.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            body = None
        result = interpret(response.status_code, body, local_recipient=local)
        if result.provider_id and any(value in result.provider_id for value in values):
            return ProviderResult(result.outcome, result.detail)
        return result
    finally:
        if own:
            try:
                http.close()
            except Exception:
                logger.warning("Unexpected client error while closing the mNotify connection")


def interpret(status_code: int, payload: dict | None, *, local_recipient: str | None = None) -> ProviderResult:
    """Map a documented mNotify response. Unreadable or contradictory replies stay unknown."""
    if status_code >= 500:
        return ProviderResult("unknown", "outcome unknown: mNotify returned a server error")
    if status_code == 401:
        return ProviderResult("definitely_failed", "mNotify rejected the API key; no message was accepted")
    if status_code == 429:
        return ProviderResult("definitely_failed", "mNotify rate limit refused the request; no message was accepted")
    if status_code == 422:
        return ProviderResult("definitely_failed", "mNotify rejected the request during validation")
    code = str((payload or {}).get("code", "")).strip()
    status = str((payload or {}).get("status", "")).strip().lower()
    if code in REJECTIONS and status != "success":
        return ProviderResult("definitely_failed", f"mNotify refused the message ({code}: {REJECTIONS[code]})")
    if status_code in (400, 405):
        return ProviderResult("definitely_failed", "mNotify refused the request; no message was accepted")
    if status_code == 200 and status == "success" and code == "2000":
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        total = summary.get("total_sent")
        try:
            sent = None if total is None else int(total)
        except (TypeError, ValueError):
            return ProviderResult("unknown", "outcome unknown: mNotify sent-count was not readable")
        if sent is not None and sent < 1:
            return ProviderResult("definitely_failed", "mNotify reported that no message was sent")
        numbers = summary.get("numbers_sent")
        if isinstance(numbers, list) and local_recipient and not _listed(numbers, local_recipient):
            return ProviderResult("definitely_failed", "mNotify did not accept the recipient")
        campaign = summary.get("_id")
        provider_id = campaign if isinstance(campaign, str) and campaign else None
        if provider_id is None:
            return ProviderResult("unknown", "outcome unknown: mNotify success response had no campaign id")
        return ProviderResult("accepted", "accepted by mNotify; handset delivery is not confirmed", provider_id)
    if payload is None:
        return ProviderResult("unknown", "outcome unknown: mNotify response was not readable")
    return ProviderResult("unknown", "outcome unknown: mNotify response did not establish acceptance or rejection")


def _listed(numbers: list, local: str) -> bool:
    """True when the documented summary lists the recipient. The number is not copied into the result."""
    forms = {local, "233" + local[1:]}
    return any(str(item) in forms for item in numbers)
