"""Private farmer sessions: phone is an identifier, never access; a session reads only its own cases. Offline."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

ROUTINE = "When should I harvest soybean in Tamale?"


def _session(client):
    response = client.post("/farmer/session")
    assert response.status_code == 200
    return response.json()["farmer_session"]


def test_session_lists_and_reads_only_its_own_cases():
    client = TestClient(app)
    mine, theirs = _session(client), _session(client)
    a = client.post("/ask", json={"question": ROUTINE}, headers={"X-Farmer-Session": mine}).json()
    b = client.post("/ask", json={"question": "my goats died after I sprayed"},
                    headers={"X-Farmer-Session": theirs}).json()
    listed = client.get("/farmer/session/cases", headers={"X-Farmer-Session": mine}).json()
    assert [item["case_id"] for item in listed] == [a["case_id"]]
    assert listed[0]["question"] == ROUTINE and listed[0]["answer"] is None
    assert client.get(f"/farmer/cases/{a['case_id']}", headers={"X-Farmer-Session": mine}).status_code == 200
    assert client.get(f"/farmer/cases/{b['case_id']}", headers={"X-Farmer-Session": mine}).status_code == 404


def test_same_phone_does_not_share_history_across_sessions():
    client = TestClient(app)
    first, second = _session(client), _session(client)
    phone = {"phone": "0240000001", "sms_consent": True}
    a = client.post("/ask", json={"question": ROUTINE} | phone, headers={"X-Farmer-Session": first}).json()
    client.post("/ask", json={"question": ROUTINE} | phone, headers={"X-Farmer-Session": second})
    listed = client.get("/farmer/session/cases", headers={"X-Farmer-Session": second}).json()
    assert a["case_id"] not in [item["case_id"] for item in listed]
    assert client.get(f"/farmer/cases/{a['case_id']}", headers={"X-Farmer-Session": second}).status_code == 404


def test_unknown_or_expired_session_is_refused_and_files_nothing():
    client = TestClient(app)
    before = db.connect().execute("SELECT count(*) FROM cases").fetchone()[0]
    assert client.post("/ask", json={"question": ROUTINE}, headers={"X-Farmer-Session": "made-up"}).status_code == 401
    assert db.connect().execute("SELECT count(*) FROM cases").fetchone()[0] == before
    assert client.get("/farmer/session/cases", headers={"X-Farmer-Session": "made-up"}).status_code == 401
    token = _session(client)
    a = client.post("/ask", json={"question": ROUTINE}, headers={"X-Farmer-Session": token}).json()
    with closing(db.connect()) as con, con:
        con.execute("UPDATE farmer_sessions SET expires_at=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"),))
    assert client.get("/farmer/session/cases", headers={"X-Farmer-Session": token}).status_code == 401
    assert client.get(f"/farmer/cases/{a['case_id']}", headers={"X-Farmer-Session": token}).status_code == 404


def test_session_token_is_stored_only_as_a_digest():
    client = TestClient(app)
    token = _session(client)
    stored = db.connect().execute("SELECT token_sha256 FROM farmer_sessions").fetchone()[0]
    assert token != stored and len(stored) == 64


def test_case_access_token_still_works_without_a_session():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": ROUTINE}).json()
    assert client.get(f"/farmer/cases/{opened['case_id']}",
                      headers={"X-Case-Access-Token": opened["access_token"]}).status_code == 200
    assert client.get(f"/farmer/cases/{opened['case_id']}").status_code == 404


def test_session_sees_only_officer_approved_text():
    """A session view goes through the same farmer body: no draft, no farmer_draft, answer None until release."""
    client = TestClient(app)
    token = _session(client)
    opened = client.post("/ask", json={"question": ROUTINE}, headers={"X-Farmer-Session": token}).json()
    view = client.get(f"/farmer/cases/{opened['case_id']}", headers={"X-Farmer-Session": token}).json()
    assert view["answer"] is None and "draft" not in view and "farmer_draft" not in view
