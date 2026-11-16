"""Per-client limit on farmer submissions (POST /ask and clarification replies). Offline; no model calls."""
from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

ROUTINE = "When should I harvest soybean in Tamale?"


def _cases():
    return db.connect().execute("SELECT COUNT(*) FROM cases").fetchone()[0]


def _limit(monkeypatch, n, window=600):
    monkeypatch.setenv("AGRIREACH_SUBMIT_LIMIT", str(n))
    monkeypatch.setenv("AGRIREACH_SUBMIT_WINDOW_SECONDS", str(window))


def test_ask_over_the_limit_gets_a_friendly_429_and_files_nothing(monkeypatch):
    _limit(monkeypatch, 3)
    client = TestClient(app)
    for _ in range(3):
        assert client.post("/ask", json={"question": ROUTINE}).status_code == 200
    before = _cases()
    blocked = client.post("/ask", json={"question": ROUTINE})
    assert blocked.status_code == 429
    detail = blocked.json()["detail"]
    assert "try again" in detail.casefold() and "112" in detail
    assert int(blocked.headers["Retry-After"]) > 0
    assert _cases() == before


def test_default_limit_is_ten_per_ten_minutes_and_bad_settings_fall_back(monkeypatch):
    from agrireach import ratelimit
    monkeypatch.delenv("AGRIREACH_SUBMIT_LIMIT", raising=False)
    monkeypatch.delenv("AGRIREACH_SUBMIT_WINDOW_SECONDS", raising=False)
    assert ratelimit.limits() == (10, 600)
    for bad in ("0", "-5", "lots", ""):
        monkeypatch.setenv("AGRIREACH_SUBMIT_LIMIT", bad)
        monkeypatch.setenv("AGRIREACH_SUBMIT_WINDOW_SECONDS", bad)
        assert ratelimit.limits() == (10, 600)  # never "unlimited" by accident


def test_window_expires(monkeypatch):
    from agrireach import ratelimit
    _limit(monkeypatch, 2, window=60)
    keys = [ratelimit.key("client", "198.51.100.7")]
    assert ratelimit.check(keys, now=1000.0) is None
    assert ratelimit.check(keys, now=1001.0) is None
    wait = ratelimit.check(keys, now=1002.0)
    assert wait is not None and 0 < wait <= 60
    assert ratelimit.check(keys, now=1061.0) is None  # the first submission left the window


def test_clarification_replies_count_toward_the_same_limit(monkeypatch):
    _limit(monkeypatch, 2)
    client = TestClient(app)
    opened = client.post("/ask", json={"question": "When should I plant soybean?"}).json()
    assert opened["clarification"]
    headers = {"X-Case-Access-Token": opened["access_token"]}
    view = client.get(f"/farmer/cases/{opened['case_id']}", headers=headers).json()
    reply = client.post(f"/farmer/cases/{opened['case_id']}/supplement", headers=headers,
                        json={"text": "Tamale", "expected_revision": view["revision"]})
    assert reply.status_code == 200
    again = client.post(f"/farmer/cases/{opened['case_id']}/supplement", headers=headers,
                        json={"text": "Tamale", "expected_revision": view["revision"]})
    assert again.status_code == 429
    assert client.post("/ask", json={"question": ROUTINE}).status_code == 429


def test_portal_client_header_is_ignored_unless_trusted(monkeypatch):
    _limit(monkeypatch, 1)
    monkeypatch.delenv("AGRIREACH_TRUST_PORTAL_CLIENT_HEADER", raising=False)
    client = TestClient(app)
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-AgriReach-Client": "a"}).status_code == 200
    # A caller cannot reset its own limit by inventing a new client id.
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-AgriReach-Client": "b"}).status_code == 429


def test_trusted_portal_header_gives_each_farmer_browser_its_own_limit(monkeypatch):
    _limit(monkeypatch, 1)
    monkeypatch.setenv("AGRIREACH_TRUST_PORTAL_CLIENT_HEADER", "1")
    client = TestClient(app)
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-AgriReach-Client": "a"}).status_code == 200
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-AgriReach-Client": "b"}).status_code == 200
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-AgriReach-Client": "a"}).status_code == 429


def test_same_phone_is_limited_across_clients(monkeypatch):
    _limit(monkeypatch, 1)
    monkeypatch.setenv("AGRIREACH_TRUST_PORTAL_CLIENT_HEADER", "1")
    client = TestClient(app)
    first = client.post("/ask", json={"question": ROUTINE, "phone": "0240000001", "sms_consent": True},
                        headers={"X-AgriReach-Client": "a"})
    assert first.status_code == 200
    second = client.post("/ask", json={"question": ROUTINE, "phone": "+233240000001", "sms_consent": True},
                         headers={"X-AgriReach-Client": "b"})
    assert second.status_code == 429
    assert "240000001" not in second.text


def test_officer_routes_are_not_rate_limited(monkeypatch):
    _limit(monkeypatch, 1)
    client = TestClient(app)
    client.post("/ask", json={"question": ROUTINE})
    assert client.post("/ask", json={"question": ROUTINE}).status_code == 429
    headers = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    for _ in range(3):
        assert client.get("/officer/queue", headers=headers).status_code == 200
    assert client.get("/officer/queue").status_code == 401  # officer sign-in unchanged


def test_portal_shows_the_429_text():
    from agrireach.ui_feedback import feedback
    level, text = feedback(429, {"detail": "Please wait a few minutes and try again."})
    assert level == "warning" and text == "Please wait a few minutes and try again."
