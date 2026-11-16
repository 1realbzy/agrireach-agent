"""mNotify quick-SMS contract, mocked. No network and no real credentials."""
import json
import logging
from urllib.parse import quote_plus

import httpx
import pytest

from agrireach.channels import mnotify

PHONE = "+233240000001"
LOCAL = "0240000001"
KEY = "mnotify-test-key-do-not-leak"
CAMPAIGN = "A59CCB70-662D-45EF-9976-1EFAD249793D"
TEXT = "AgriReach: We have received your farming question. Reference: 4."


def _live(monkeypatch, *, key=KEY, sender="AgriReach", base="https://api.mnotify.com"):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")
    monkeypatch.setenv("MNOTIFY_API_KEY", key)
    monkeypatch.setenv("MNOTIFY_SENDER_ID", sender)
    monkeypatch.setenv("MNOTIFY_API_BASE", base)


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), timeout=30)


def _success():
    return {"status": "success", "code": "2000", "message": "messages sent successfully",
            "summary": {"_id": CAMPAIGN, "type": "API QUICK SMS", "total_sent": 1, "contacts": 1,
                        "total_rejected": 0, "numbers_sent": [LOCAL], "credit_used": 1, "credit_left": 10}}


def test_default_mode_is_disabled_and_unknown_mode_is_not_live(monkeypatch):
    monkeypatch.delenv("MNOTIFY_SMS_MODE", raising=False)
    assert mnotify.mode() == "disabled"
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "LIVE ")
    assert mnotify.mode() == "live"
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "africastalking")
    assert mnotify.mode() == "disabled"


def test_simulated_result_is_not_a_handset_delivery():
    result = mnotify.simulate(4)
    assert result.simulated and result.outcome == "accepted" and not result.handset_delivered
    assert result.detail.startswith("simulated:")
    assert "sent to a phone" in result.detail
    assert "delivered" not in result.detail


def test_live_request_uses_documented_quick_sms_fields(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=_success())

    _live(monkeypatch)
    result = mnotify.transmit(PHONE, TEXT, client=_client(handler))
    assert result.outcome == "accepted" and result.provider_id == CAMPAIGN and not result.handset_delivered
    assert "handset delivery is not confirmed" in result.detail
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/api/sms/quick"
    assert request.url.host == "api.mnotify.com"
    assert request.url.params["key"] == KEY
    body = request.read().decode()
    assert KEY not in body and PHONE not in body
    assert json.loads(body) == {"recipient": [LOCAL], "sender": "AgriReach", "message": TEXT,
                                "is_schedule": False, "schedule_date": ""}
    assert "africastalking" not in str(request.url)


def test_provider_rejection_timeout_and_malformed_response(monkeypatch):
    _live(monkeypatch)
    rejected = mnotify.transmit(PHONE, TEXT, client=_client(
        lambda request: httpx.Response(200, json={"status": "error", "code": "4004", "message": "credit is not enough"})))
    assert rejected.outcome == "definitely_failed" and "4004" in rejected.detail
    assert KEY not in rejected.detail and PHONE not in rejected.detail and LOCAL not in rejected.detail

    def timeout(request):
        raise httpx.ReadTimeout("timed out")

    unknown = mnotify.transmit(PHONE, TEXT, client=_client(timeout))
    assert unknown.outcome == "unknown" and unknown.detail.startswith("outcome unknown:")
    assert KEY not in unknown.detail and LOCAL not in unknown.detail

    malformed = mnotify.transmit(PHONE, TEXT, client=_client(lambda request: httpx.Response(200, text="<html>")))
    assert malformed.outcome == "unknown"
    assert "<html>" not in malformed.detail and KEY not in malformed.detail


def test_invalid_credentials_are_a_definite_refusal(monkeypatch):
    _live(monkeypatch)
    result = mnotify.transmit(PHONE, TEXT, client=_client(
        lambda request: httpx.Response(401, json={"status": "error", "code": "401", "message": KEY})))
    assert result.outcome == "definitely_failed" and "API key" in result.detail
    assert KEY not in result.detail and not result.handset_delivered


@pytest.mark.parametrize("sender", ["", "123456", "A" * 12])
def test_missing_or_invalid_configuration_does_not_call_out(monkeypatch, sender):
    calls = []
    _live(monkeypatch, key="" if sender == "" else KEY, sender=sender or "AgriReach")
    result = mnotify.transmit(PHONE, TEXT, client=_client(lambda request: calls.append(request) or httpx.Response(200)))
    assert result.outcome == "definitely_failed" and calls == []
    assert "not sent" in result.detail or "not configured" in result.detail or "not enabled" in result.detail


def test_another_provider_host_is_not_used(monkeypatch):
    calls = []
    _live(monkeypatch, base="https://api.africastalking.com")
    monkeypatch.setenv("SMS_ENABLED", "1")
    monkeypatch.setenv("AT_API_KEY", "at-secret")
    result = mnotify.transmit(PHONE, TEXT, client=_client(lambda request: calls.append(request) or httpx.Response(200)))
    assert result.outcome == "definitely_failed" and calls == []
    assert "at-secret" not in result.detail


def test_connect_failure_is_not_an_unknown_send(monkeypatch):
    _live(monkeypatch)

    def down(request):
        raise httpx.ConnectError("down")

    result = mnotify.transmit(PHONE, TEXT, client=_client(down))
    assert result.outcome == "definitely_failed" and result.detail.startswith("not sent:")


def test_config_repr_hides_the_key(monkeypatch):
    _live(monkeypatch)
    assert KEY not in repr(mnotify.live_config())


def test_httpx_request_log_keeps_diagnostics_without_api_key(monkeypatch, caplog):
    key = KEY + "/+= synthetic"
    _live(monkeypatch, key=key)
    caplog.set_level("DEBUG")

    def provider(request):
        assert request.url.params["key"] == key
        return httpx.Response(200, json=_success())

    with _client(provider) as client:
        result = mnotify.transmit(PHONE, TEXT, client=client)
    assert result.outcome == "accepted"
    assert key not in caplog.text and quote_plus(key) not in caplog.text
    assert "POST" in caplog.text and "200 OK" in caplog.text


def test_httpx_transport_error_details_are_redacted(monkeypatch, caplog):
    _live(monkeypatch)
    caplog.set_level("DEBUG")

    def provider(request):
        try:
            raise httpx.ReadError(f"broken response for {request.url} and {LOCAL}", request=request)
        except httpx.ReadError:
            logging.getLogger("httpcore.http11").debug("receive_response_headers.failed", exc_info=True)
            raise

    with _client(provider) as client:
        result = mnotify.transmit(PHONE, TEXT, client=client)
    assert result.outcome == "unknown"
    assert "receive_response_headers.failed" in caplog.text
    assert KEY not in caplog.text + result.detail
    assert LOCAL not in caplog.text + result.detail


def test_mnotify_does_not_follow_provider_redirects(monkeypatch):
    _live(monkeypatch)
    hosts = []

    def provider(request):
        hosts.append(request.url.host)
        return httpx.Response(307, headers={"Location": f"https://example.invalid/?key={KEY}"})

    with httpx.Client(transport=httpx.MockTransport(provider), follow_redirects=True) as client:
        result = mnotify.transmit(PHONE, TEXT, client=client)
    assert result.outcome == "unknown"
    assert hosts == ["api.mnotify.com"]


def test_unexpected_client_error_does_not_expose_authenticated_url(monkeypatch, caplog):
    _live(monkeypatch)

    def provider(request):
        raise RuntimeError(f"synthetic client error for {request.url}")

    with _client(provider) as client:
        result = mnotify.transmit(PHONE, TEXT, client=client)
    assert result.outcome == "unknown"
    assert "Unexpected client error" in caplog.text
    assert KEY not in caplog.text + result.detail


@pytest.mark.parametrize("body", [None, {"message": "validation error"}, {"code": "4001", "status": "error"}])
def test_http_422_is_a_definite_validation_refusal(body):
    result = mnotify.interpret(422, body)
    assert result.outcome == "definitely_failed" and "validation" in result.detail


def test_only_documented_immediate_success_can_confirm_acceptance():
    assert mnotify.interpret(200, _success() | {"code": "2001"}).outcome == "unknown"
    assert mnotify.interpret(503, _success()).outcome == "unknown"
    assert mnotify.interpret(503, {"code": "4014", "status": "error"}).outcome == "unknown"
    assert mnotify.interpret(200, {"code": "405", "status": "error"}).outcome == "unknown"
    refusal = mnotify.interpret(405, None)
    assert refusal.outcome == "definitely_failed" and "rate limit" not in refusal.detail
    assert "rate limit" in mnotify.interpret(429, None).detail
