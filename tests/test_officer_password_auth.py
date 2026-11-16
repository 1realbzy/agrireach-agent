"""Officer email/password sign-in with expiring, revocable server-side sessions (migration v7). Offline."""
from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from agrireach import db, officer_auth
from agrireach.api import app

EMAIL, NAME, PASSWORD = "ama.mensah@example.org", "Ama Mensah", "synthetic-Passw0rd-for-tests"


def _account(email=EMAIL, name=NAME, password=PASSWORD):
    return officer_auth.create_account(db.connect(), email, name, password)


def _login(client, email=EMAIL, password=PASSWORD, **kw):
    return client.post("/officer/auth/login", json={"email": email, "password": password}, **kw)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_is_hashed_with_scrypt_and_never_stored_plain():
    _account()
    row = db.connect().execute("SELECT password_hash FROM officer_accounts WHERE email=?", (EMAIL,)).fetchone()
    assert row["password_hash"].startswith("scrypt$16384$8$1$")
    assert PASSWORD not in row["password_hash"]
    assert officer_auth.verify_password(PASSWORD, row["password_hash"])
    assert not officer_auth.verify_password(PASSWORD + "x", row["password_hash"])


@pytest.mark.parametrize("bad", ["", "short", "x" * 11, "x" * 257])
def test_password_policy_refuses_weak_or_oversized_passwords(bad):
    with pytest.raises(ValueError):
        _account(password=bad)
    assert db.connect().execute("SELECT count(*) FROM officer_accounts").fetchone()[0] == 0


def test_login_returns_an_expiring_session_that_opens_officer_routes():
    _account()
    client = TestClient(app)
    response = _login(client, email="  AMA.Mensah@Example.org ")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["officer"] == NAME and body["email"] == EMAIL and body["token_type"] == "Bearer"
    expires = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=7, minutes=59) < expires - datetime.now(timezone.utc) <= timedelta(hours=8)
    assert client.get("/officer/queue", headers=_bearer(body["session_token"])).status_code == 200
    me = client.get("/officer/auth/me", headers=_bearer(body["session_token"])).json()
    assert me == {"officer": NAME, "email": EMAIL, "expires_at": body["expires_at"], "kind": "session"}
    stored = db.connect().execute("SELECT token_sha256 FROM officer_sessions").fetchone()[0]
    assert body["session_token"] not in stored and len(stored) == 64


@pytest.mark.parametrize("email,password", [(EMAIL, "wrong-password-123"), ("nobody@example.org", PASSWORD),
                                            ("not-an-email", PASSWORD)])
def test_wrong_email_or_password_gets_one_generic_401(email, password):
    _account()
    client = TestClient(app)
    response = _login(client, email=email, password=password)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."
    assert db.connect().execute("SELECT count(*) FROM officer_sessions").fetchone()[0] == 0


def test_expired_session_is_refused(monkeypatch):
    _account()
    client = TestClient(app)
    token = _login(client).json()["session_token"]
    with closing(db.connect()) as con, con:
        con.execute("UPDATE officer_sessions SET expires_at=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"),))
    assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401


def test_session_lifetime_is_configurable_but_capped(monkeypatch):
    monkeypatch.setenv("AGRIREACH_OFFICER_SESSION_HOURS", "1")
    assert officer_auth.session_hours() == 1
    monkeypatch.setenv("AGRIREACH_OFFICER_SESSION_HOURS", "1000")
    assert officer_auth.session_hours() == 24
    for bad in ("0", "-3", "forever", ""):
        monkeypatch.setenv("AGRIREACH_OFFICER_SESSION_HOURS", bad)
        assert officer_auth.session_hours() == 8


def test_logout_revokes_only_that_session():
    _account()
    client = TestClient(app)
    first = _login(client).json()["session_token"]
    second = _login(client).json()["session_token"]
    assert client.post("/officer/auth/logout", headers=_bearer(first)).json() == {"revoked": True}
    assert client.get("/officer/queue", headers=_bearer(first)).status_code == 401
    assert client.get("/officer/queue", headers=_bearer(second)).status_code == 200
    assert client.post("/officer/auth/logout", headers=_bearer(first)).json() == {"revoked": False}


def test_operator_revoke_disable_and_password_change_end_every_session():
    _account()
    client = TestClient(app)
    token = _login(client).json()["session_token"]
    assert officer_auth.revoke_sessions(db.connect(), EMAIL) == 1
    assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401
    token = _login(client).json()["session_token"]
    assert officer_auth.set_disabled(db.connect(), EMAIL, True) == 1
    assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401
    assert _login(client).status_code == 401  # a disabled account cannot sign in
    officer_auth.set_disabled(db.connect(), EMAIL, False)
    token = _login(client).json()["session_token"]
    assert officer_auth.set_password(db.connect(), EMAIL, "another-synthetic-passw0rd") == 1
    assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401
    assert _login(client).status_code == 401
    assert _login(client, password="another-synthetic-passw0rd").status_code == 200


def test_failed_logins_lock_the_email_with_429_and_retry_after(monkeypatch):
    monkeypatch.setenv("AGRIREACH_LOGIN_MAX_FAILURES", "3")
    _account()
    client = TestClient(app)
    for _ in range(3):
        assert _login(client, password="wrong-password-123").status_code == 401
    locked = _login(client)  # even the right password waits out the lock
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) > 0
    assert "try again" in locked.json()["detail"].casefold()
    assert db.connect().execute("SELECT count(*) FROM officer_sessions").fetchone()[0] == 0


def test_lock_expires_after_the_window(monkeypatch):
    monkeypatch.setenv("AGRIREACH_LOGIN_MAX_FAILURES", "2")
    _account()
    client = TestClient(app)
    for _ in range(2):
        _login(client, password="wrong-password-123")
    assert _login(client).status_code == 429
    old = (datetime.now(timezone.utc) - timedelta(seconds=901)).isoformat(timespec="seconds")
    with closing(db.connect()) as con, con:
        con.execute("UPDATE officer_login_attempts SET created_at=?", (old,))
    assert _login(client).status_code == 200


def test_one_client_guessing_many_emails_is_locked(monkeypatch):
    monkeypatch.setenv("AGRIREACH_LOGIN_MAX_FAILURES", "2")
    _account()
    client = TestClient(app)
    for i in range(8):  # per-client allowance is 4x the per-email limit
        assert _login(client, email=f"guess{i}@example.org", password="wrong-password-123").status_code == 401
    assert _login(client).status_code == 429


def test_login_attempts_store_no_email_or_password():
    _account()
    client = TestClient(app)
    _login(client, password="wrong-password-123")
    rows = db.connect().execute("SELECT * FROM officer_login_attempts").fetchall()
    text = json.dumps([dict(r) for r in rows])
    assert rows and EMAIL not in text and "wrong-password" not in text


@pytest.mark.parametrize("method,path,body", [
    ("get", "/officer/queue", None), ("get", "/officer/cases", None), ("get", "/officer/cases/1", None),
    ("post", "/officer/cases/1/decision", {"decision": "approve"}), ("post", "/cases/1/release", None),
    ("post", "/officer/cases/1/assess", {"farmer_text": "x"}), ("get", "/officer/auth/me", None),
    ("post", "/officer/cases/1/reopen", {"expected_revision": 1, "information": "x"}),
])
def test_officer_routes_refuse_missing_or_unknown_credentials(method, path, body):
    client = TestClient(app)
    for headers in ({}, _bearer("not-a-session"), _bearer("")):
        kwargs = {"headers": headers} | ({"json": body} if body is not None else {})
        assert getattr(client, method)(path, **kwargs).status_code == 401, (path, headers)


def test_farmer_case_token_and_farmer_session_cannot_sign_in_as_officer():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    farmer = client.post("/farmer/session").json()["farmer_session"]
    for token in (opened["access_token"], farmer):
        assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401


def test_legacy_tokens_can_be_switched_off(monkeypatch):
    legacy = db.add_officer(db.connect(), "Kofi Legacy")
    _account()
    client = TestClient(app)
    session = _login(client).json()["session_token"]
    assert client.get("/officer/queue", headers=_bearer(legacy)).status_code == 200
    monkeypatch.setenv("AGRIREACH_LEGACY_OFFICER_TOKENS", "0")
    assert client.get("/officer/queue", headers=_bearer(legacy)).status_code == 401
    assert client.get("/officer/queue", headers=_bearer(session)).status_code == 200


def test_session_approval_still_requires_the_full_approval_gate(monkeypatch):
    """Signing in with a session changes who is recorded, never what an approval must prove."""
    monkeypatch.setenv("AGRIREACH_LEGACY_OFFICER_TOKENS", "0")
    _account()
    client = TestClient(app)
    headers = _bearer(_login(client).json()["session_token"])
    opened = client.post("/ask", json={"question": "my goats died after I sprayed"}).json()
    assert client.post(f"/cases/{opened['case_id']}/release", headers=headers).status_code == 409
    row = db.get_case(db.connect(), opened["case_id"])
    unconfirmed = client.post(f"/officer/cases/{opened['case_id']}/decision", headers=headers,
                              json={"decision": "approve", "expected_revision": row["revision"],
                                    "farmer_text": "Call 112 now and contact a veterinary officer."})
    assert unconfirmed.status_code in (400, 409, 422), unconfirmed.text
    unsafe = client.post(f"/officer/cases/{opened['case_id']}/decision", headers=headers,
                         json={"decision": "approve", "confirmed": True, "expected_revision": row["revision"],
                               "farmer_text": "Mix two pesticides and spray every week."})
    assert unsafe.status_code == 422, unsafe.text
    assert db.get_case(db.connect(), opened["case_id"])["status"] == "pending_review"
    farmer = client.get(f"/farmer/cases/{opened['case_id']}",
                        headers={"X-Case-Access-Token": opened["access_token"]}).json()
    assert farmer["answer"] is None


def test_cli_creates_lists_revokes_without_printing_secrets(monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "officer_accounts", Path(__file__).resolve().parents[1] / "scripts" / "officer_accounts.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert cli.main(["create", EMAIL, NAME, "--password-stdin"]) == 0
    client = TestClient(app)
    token = _login(client).json()["session_token"]
    assert cli.main(["list"]) == 0
    assert cli.main(["revoke", EMAIL]) == 0
    out = capsys.readouterr().out
    assert EMAIL in out and "open sessions: 1" in out and "1 session(s) revoked" in out
    assert PASSWORD not in out and token not in out
    assert client.get("/officer/queue", headers=_bearer(token)).status_code == 401
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    with pytest.raises(SystemExit):
        cli.main(["create", "kofi@example.org", "Kofi", "--password-stdin"])
