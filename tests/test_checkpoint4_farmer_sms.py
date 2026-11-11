"""Farmer phone consent and the administrative acknowledgement. No live SMS."""
import json
import sqlite3
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from agrireach import acknowledgement, agent, db
from agrireach.api import app
from agrireach.channels import mnotify

c = TestClient(app)
QUESTION = "When should I harvest soybean in Tamale?"
PHONE = "0240000001"
E164 = "+233240000001"
KEY = "mnotify-test-key-do-not-leak"


def _ask(**extra):
    return c.post("/ask", json={"question": QUESTION, **extra})


def _stored_phone(case_id):
    return db.connect().execute("SELECT phone_e164 FROM farmer_sms_contacts WHERE case_id=?", (case_id,)).fetchone()


def _job(case_id):
    return db.connect().execute("SELECT * FROM acknowledgement_jobs WHERE case_id=?", (case_id,)).fetchone()


def _blob_without_contact_table():
    con = db.connect()
    parts = []
    for table in ("tool_log", "audit_events", "acknowledgement_attempts", "model_usage"):
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone()
        if exists:
            parts.append(str(con.execute(f"SELECT * FROM {table}").fetchall()))
    return "\n".join(parts)


def test_legacy_question_without_a_phone_still_saves():
    body = _ask().json()
    assert body["status"] == "pending_review"
    assert "has been received" in body["message"]
    assert "under officer review" not in body["message"].lower()
    assert _stored_phone(body["case_id"]) is None
    assert _job(body["case_id"]) is None
    assert body["acknowledgement"]["status"] == "not_requested"
    assert body["acknowledgement"]["handset_delivered"] is False


def test_clarification_is_not_described_as_officer_review():
    body = c.post("/ask", json={"question": "When should I plant?"}).json()
    assert body["status"] == "draft" and body["clarification"]
    assert "awaiting your information" in body["message"].lower()
    assert "sent to an extension officer" not in body["message"].lower()
    assert "under officer review" not in body["message"].lower()


def test_invalid_phone_is_rejected_before_a_case_exists():
    response = _ask(phone="0302000001", sms_consent=True)
    assert response.status_code == 422
    assert PHONE not in response.text and "0302000001" not in response.text
    assert db.connect().execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0


@pytest.mark.parametrize("payload", [
    {"phone": PHONE, "access_token": KEY},
    {"question": QUESTION, "phone": int(PHONE), "sms_consent": KEY},
    {"question": {"nested": [PHONE, {"token": KEY}]}},
    [{"phone": PHONE, "access_token": KEY}],
])
def test_ask_validation_excludes_private_input(payload, caplog):
    response = c.post("/ask", json=payload, headers={"X-Case-Access-Token": KEY})
    assert response.status_code == 422
    for private in (PHONE, str(int(PHONE)), KEY):
        assert private not in response.text
        assert private not in caplog.text
    assert all({"loc", "type", "msg"} == set(error) for error in response.json()["detail"])


def test_ask_malformed_json_keeps_diagnostics_without_body(caplog):
    response = c.post("/ask", content=f'{{"phone":"{PHONE}","access_token":"{KEY}",',
                      headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    error, = response.json()["detail"]
    assert error["loc"][0] == "body" and error["type"] == "json_invalid"
    assert error["msg"] == "Invalid JSON body"
    for private in (PHONE, KEY):
        assert private not in response.text and private not in caplog.text


@pytest.mark.parametrize("phone", [PHONE, "invalid phone"])
def test_declined_consent_stores_nothing_and_sends_nothing(monkeypatch, phone):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    called = []
    monkeypatch.setattr(mnotify, "simulate", lambda case_id: called.append(case_id))
    body = _ask(phone=phone, sms_consent=False).json()
    assert body["acknowledgement"]["status"] == "not_requested"
    assert _stored_phone(body["case_id"]) is None and _job(body["case_id"]) is None and called == []
    assert PHONE not in json.dumps(body) and E164 not in json.dumps(body)


def test_explicit_consent_simulated_success_is_labelled(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    body = _ask(phone=PHONE, sms_consent=True).json()
    case_id, token = body["case_id"], body["access_token"]
    ack = body["acknowledgement"]
    assert ack["status"] == "accepted" and ack["simulated"] is True and ack["handset_delivered"] is False
    assert "simulated" in ack["message"] and "no message was sent to a phone" in ack["message"].lower()
    assert _stored_phone(case_id)["phone_e164"] == E164
    assert _job(case_id)["mode"] == "simulated" and _job(case_id)["state"] == "accepted"
    text = acknowledgement.message_for(case_id)
    draft = db.get_case(db.connect(), case_id)["farmer_draft"] or ""
    assert text == acknowledgement.TEMPLATE.format(case_reference=case_id)
    assert QUESTION not in text and token not in text and "pods" not in text
    assert draft not in text
    assert PHONE not in text and E164 not in text
    assert PHONE not in json.dumps(body) and E164 not in json.dumps(body) and token not in text
    private = _blob_without_contact_table()
    assert PHONE not in private and E164 not in private and KEY not in private
    farmer = c.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token}).json()
    assert farmer["answer"] is None
    assert farmer["acknowledgement"] == ack
    assert c.get(f"/farmer/cases/{case_id}").status_code == 404
    assert c.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": "wrong"}).status_code == 404
    assert c.post(f"/cases/{case_id}/release").status_code == 401


def test_disabled_mode_records_consent_without_a_job(monkeypatch):
    monkeypatch.delenv("MNOTIFY_SMS_MODE", raising=False)
    body = _ask(phone=PHONE, sms_consent=True).json()
    assert body["acknowledgement"]["status"] == "disabled"
    assert "no message was sent" in body["acknowledgement"]["message"].lower()
    assert _stored_phone(body["case_id"])["phone_e164"] == E164
    assert _job(body["case_id"]) is None


def test_duplicate_case_has_one_acknowledgement_and_a_second_dispatch_does_not_send(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    calls = []
    monkeypatch.setattr(mnotify, "simulate", lambda case_id: calls.append(case_id) or mnotify.ProviderResult(
        "accepted", "simulated: acknowledgement recorded locally; no message was sent to a phone",
        f"simulated-{case_id}", True))
    first, second = _ask(phone=PHONE, sms_consent=True).json(), _ask(phone=PHONE, sms_consent=True).json()
    assert first["case_id"] != second["case_id"]
    assert len(calls) == 2
    acknowledgement.dispatch(db.connect(), _job(first["case_id"])["id"])
    assert calls == [first["case_id"], second["case_id"]]
    assert db.connect().execute("SELECT COUNT(*) FROM acknowledgement_jobs WHERE case_id=?",
                                (first["case_id"],)).fetchone()[0] == 1


def test_case_creation_failure_leaves_no_contact_or_job(monkeypatch):
    async def boom(*args, **kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(agent, "run", boom)
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    with pytest.raises(sqlite3.OperationalError):
        _ask(phone=PHONE, sms_consent=True)
    con = db.connect()
    assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM farmer_sms_contacts").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM acknowledgement_jobs").fetchone()[0] == 0


def test_enqueue_failure_keeps_the_saved_case(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("enqueue failed")

    monkeypatch.setattr(acknowledgement, "enqueue", fail)
    body = _ask(phone=PHONE, sms_consent=True).json()
    assert body["case_id"] and body["acknowledgement"]["status"] == "not_scheduled"
    assert "saved" in body["acknowledgement"]["message"].lower()
    assert "do not send the question again" in body["acknowledgement"]["message"].lower()
    assert db.connect().execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    assert _job(body["case_id"]) is None
    assert _stored_phone(body["case_id"]) is None


@pytest.mark.parametrize("failure, mode, expected", [
    ("remember_consent", "disabled", "not_scheduled"),
    ("complete", "simulated", "sending"),
    ("public_status", "simulated", "unknown"),
])
def test_post_save_sms_failure_returns_saved_case_and_token(monkeypatch, failure, mode, expected):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", mode)

    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("injected post-save failure")

    with monkeypatch.context() as patch:
        patch.setattr(acknowledgement, failure, fail)
        response = _ask(phone=PHONE, sms_consent=True)
    assert response.status_code == 200
    body = response.json()
    assert body["acknowledgement"]["status"] == expected
    assert "saved" in body["acknowledgement"]["message"]
    assert "injected" not in response.text
    assert db.connect().execute("SELECT count(*) FROM cases").fetchone()[0] == 1
    assert c.get(f"/farmer/cases/{body['case_id']}",
                 headers={"X-Case-Access-Token": body["access_token"]}).status_code == 200


def test_acknowledgement_is_available_for_clarification_and_regular_lookup(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    body = c.post("/ask", json={"question": "When should I plant?", "phone": PHONE, "sms_consent": True}).json()
    headers = {"X-Case-Access-Token": body["access_token"]}
    url = f"/farmer/cases/{body['case_id']}"
    view = c.get(url, headers=headers).json()
    assert view["clarification"] == body["clarification"]
    assert view["acknowledgement"] == body["acknowledgement"]
    con = db.connect()
    con.execute("UPDATE acknowledgement_jobs SET state='unknown'")
    con.commit()
    view = c.get(url, headers=headers).json()
    assert view["acknowledgement"]["status"] == "unknown"
    assert view["answer"] is None and PHONE not in json.dumps(view)


def test_provider_rejection_timeout_and_no_retry_of_unknown(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")
    monkeypatch.setenv("MNOTIFY_API_KEY", KEY)
    monkeypatch.setenv("MNOTIFY_SENDER_ID", "AgriReach")
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, json={"status": "error", "code": "4014", "message": "sender ID is not registered"})
        raise httpx.ReadTimeout("timed out")

    real_client = httpx.Client
    monkeypatch.setattr(
        mnotify.httpx, "Client",
        lambda *args, **kwargs: real_client(transport=httpx.MockTransport(handler), timeout=30))
    rejected = _ask(phone=PHONE, sms_consent=True).json()
    assert rejected["acknowledgement"]["status"] == "definitely_failed"
    assert rejected["acknowledgement"]["handset_delivered"] is False
    assert db.get_case(db.connect(), rejected["case_id"])["status"] == "pending_review"
    assert KEY not in json.dumps(rejected) and PHONE not in json.dumps(rejected)

    timed = _ask(phone="0200000002", sms_consent=True).json()
    assert timed["acknowledgement"]["status"] == "unknown"
    assert "will not be sent again automatically" in timed["acknowledgement"]["message"]
    before = calls["n"]
    again = acknowledgement.dispatch(db.connect(), _job(timed["case_id"])["id"])
    assert again["status"] == "unknown" and calls["n"] == before


def test_repeated_workers_send_once(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")
    monkeypatch.setenv("MNOTIFY_API_KEY", KEY)
    monkeypatch.setenv("MNOTIFY_SENDER_ID", "AgriReach")
    calls = []
    lock = threading.Lock()

    def transmit(phone, message, client=None):
        with lock:
            calls.append(message)
        return mnotify.ProviderResult("accepted", "accepted by mNotify; handset delivery is not confirmed", "camp-1", False)

    monkeypatch.setattr(mnotify, "transmit", transmit)
    body = _ask(phone=PHONE, sms_consent=False).json()
    job_id = acknowledgement.enqueue(db.connect(), body["case_id"], E164, "live")
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        acknowledgement.dispatch(db.connect(), job_id)

    threads = [threading.Thread(target=run), threading.Thread(target=run)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1
    assert QUESTION not in calls[0] and PHONE not in calls[0] and E164 not in calls[0]
    assert _job(body["case_id"])["state"] == "accepted"


def test_missing_mnotify_configuration_does_not_use_africas_talking(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")
    monkeypatch.delenv("MNOTIFY_API_KEY", raising=False)
    monkeypatch.setenv("SMS_ENABLED", "1")
    monkeypatch.setenv("AT_USERNAME", "sandbox")
    monkeypatch.setenv("AT_API_KEY", "at-secret")
    calls = []
    monkeypatch.setattr(mnotify.httpx, "Client", lambda *args, **kwargs: calls.append("http") or httpx.Client())
    body = _ask(phone=PHONE, sms_consent=True).json()
    assert body["acknowledgement"]["status"] == "definitely_failed"
    assert calls == []
    assert "at-secret" not in json.dumps(body)
    assert db.connect().execute("SELECT COUNT(*) FROM channel_deliveries").fetchone()[0] == 0


def test_officer_can_inspect_and_reconcile_without_sending(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    body = _ask(phone=PHONE, sms_consent=True).json()
    officer = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    hidden = c.get(f"/officer/cases/{body['case_id']}/acknowledgement")
    assert hidden.status_code == 401
    assert c.get(f"/officer/cases/{body['case_id']}/acknowledgement",
                 headers={"Authorization": f"Bearer {body['access_token']}"}).status_code == 401
    seen = c.get(f"/officer/cases/{body['case_id']}/acknowledgement", headers=officer).json()
    assert seen["simulated"] is True and seen["phone_masked"].endswith("01")
    assert PHONE not in json.dumps(seen) and E164 not in json.dumps(seen)
    assert "240000001" not in json.dumps(seen)
    con = db.connect()
    job_id = _job(body["case_id"])["id"]
    con.execute("UPDATE acknowledgement_jobs SET state='unknown', updated_at=? WHERE id=?", (db.now(), job_id))
    con.commit()
    recorded = c.post(f"/officer/acknowledgement-jobs/{job_id}/reconcile", headers=officer,
                      json={"accepted": True, "provider_evidence": "mnotify-campaign-record-1"})
    assert recorded.status_code == 200 and recorded.json()["handset_delivered"] is False
    assert _job(body["case_id"])["state"] == "accepted"
    assert c.post(f"/cases/{body['case_id']}/release", headers=officer).status_code == 409


def test_abandoned_claim_becomes_unknown_and_is_not_resent(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    calls = []
    original = mnotify.simulate
    monkeypatch.setattr(mnotify, "simulate", lambda case_id: calls.append(case_id) or original(case_id))
    body = _ask(phone=PHONE, sms_consent=False).json()
    job_id = acknowledgement.enqueue(db.connect(), body["case_id"], E164, "simulated")
    con = db.connect()
    claim = acknowledgement.claim(con, job_id)
    assert claim is not None
    con.execute("UPDATE acknowledgement_jobs SET updated_at='2000-01-01T00:00:00+00:00' WHERE id=?", (job_id,))
    con.commit()
    again = acknowledgement.dispatch(db.connect(), job_id)
    assert again["status"] == "unknown" and calls == []


def test_retention_removes_the_web_number_and_blocks_a_later_send(monkeypatch):
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "simulated")
    body = _ask(phone=PHONE, sms_consent=True).json()
    con = db.connect()
    con.execute("UPDATE farmer_sms_contacts SET created_at='2000-01-01T00:00:00+00:00' WHERE case_id=?", (body["case_id"],))
    con.execute("UPDATE acknowledgement_jobs SET state='pending', claim_id=NULL WHERE case_id=?", (body["case_id"],))
    con.commit()
    assert db.purge_old(con, days=90)["farmer_sms"] == 1
    assert _stored_phone(body["case_id"]) is None
    status = acknowledgement.dispatch(con, _job(body["case_id"])["id"])
    assert status["status"] == "undeliverable"
    assert db.get_case(con, body["case_id"])["question"] == QUESTION


def test_farmer_form_consent_is_optional_and_status_is_accurate(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []

    def backend(method, url, **kwargs):
        seen.append((method, url, kwargs.get("json")))
        if str(url).endswith("/ask"):
            payload = kwargs.get("json") or {}
            if payload.get("sms_consent"):
                return httpx.Response(200, json={
                    "case_id": 3, "access_token": "hidden-token", "status": "pending_review", "clarification": None,
                    "message": "Your question has been received. It is waiting for an extension officer to review. Advice is not available yet.",
                    "acknowledgement": {"status": "accepted", "simulated": True, "handset_delivered": False,
                                        "message": "A simulated SMS confirmation was recorded. No message was sent to a phone."}})
            return httpx.Response(200, json={
                "case_id": 4, "access_token": "hidden-token", "status": "draft",
                "clarification": "Which district or region is your farm in?",
                "message": "Awaiting your information before an officer can review this.",
                "acknowledgement": {"status": "not_requested", "simulated": False, "handset_delivered": False,
                                    "message": "No confirmation SMS was sent."}})
        if str(url).endswith("/farmer/cases/3"):
            return httpx.Response(200, json={"status": "pending_review", "answer": None,
                                            "acknowledgement": {"message": "Current SMS status from lookup"}})
        return httpx.Response(200, json={"draft_mode": "stub"})

    monkeypatch.setattr(httpx, "request", backend)
    screen = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    assert screen.checkbox(key="farmer_sms_consent").value is False
    screen.text_area(key="farmer_question").set_value(QUESTION)
    screen.text_input(key="farmer_phone").set_value("12345")
    screen.checkbox(key="farmer_sms_consent").set_value(True)
    screen.button(key="farmer_submit_button").click().run()
    assert not any(call[0] == "POST" for call in seen)
    assert any("Ghana mobile number" in item.value for item in screen.warning)

    plain = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    plain.text_area(key="farmer_question").set_value("When should I plant?")
    plain.text_input(key="farmer_phone").set_value("12345")
    plain.button(key="farmer_submit_button").click().run()
    assert seen[-1][2] == {"question": "When should I plant?"}
    assert any("Awaiting your information" in item.value for item in plain.info)
    assert not any("waiting for an extension officer to review" in item.value.lower() for item in plain.caption)

    agreed = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    agreed.text_area(key="farmer_question").set_value(QUESTION)
    agreed.text_input(key="farmer_phone").set_value(PHONE)
    agreed.checkbox(key="farmer_sms_consent").set_value(True)
    agreed.button(key="farmer_submit_button").click().run()
    assert {"question": QUESTION, "phone": PHONE, "sms_consent": True} in [call[2] for call in seen]
    assert any(item.value == "Your question has been received." for item in agreed.success)
    assert any("simulated" in item.value.lower() and "no message was sent to a phone" in item.value.lower() for item in agreed.info)
    assert any("waiting for an extension officer" in item.value.lower() for item in agreed.caption)
    agreed.button(key="farmer_check").click().run()
    assert any(item.value == "Current SMS status from lookup" for item in agreed.info)
