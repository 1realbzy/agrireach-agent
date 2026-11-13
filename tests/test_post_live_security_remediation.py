"""Regressions for the five confirmed post-live security findings.

The offline judge supports every sentence it sees. A passing result has to come
from the safety, approval, and release functions, not from a mocked rejection.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agrireach import agent, approval, db, knowledge, safety_gate
from agrireach.api import app

MIX = "Mix both pesticides and spray water every week."
REFERRAL = "Consult your local AEA before choosing or applying a pesticide."
EXPLOIT = f"{REFERRAL} {MIX}"
YELLOW = "My maize leaves are turning yellow in Wa. What should I do?"
CROP_YELLOW = "My crop's leaves are turning yellow in Wa. What should I do?"
CHEMICAL_Q = "Can I mix two pesticides and spray every week to kill insects faster?"
HARVEST_Q = "When should I harvest soybean in Tamale?"
GAP_MESSAGE = (
    "AgriReach has no sourced guidance for this question. An extension officer will investigate it. "
    "No treatment advice has been approved."
)
FAW = "APNI-SARI-2023-MAIZE:p20-faw-control"


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def _approve(client, case_id, text):
    row = db.get_case(db.connect(), case_id)
    return client.post(
        f"/officer/cases/{case_id}/decision", headers=_officer(),
        json={"decision": "approve", "confirmed": True, "farmer_text": text,
              "expected_revision": row["revision"]})


def _view(client, opened):
    return client.get(
        f"/farmer/cases/{opened['case_id']}",
        headers={"X-Case-Access-Token": opened["access_token"]})


def _faw_case(client):
    opened = client.post("/ask", json={"question": "Fall armyworm is eating my maize in Wa. What should I do?"}).json()
    con = db.connect()
    con.execute("UPDATE cases SET sources=? WHERE id=?", (json.dumps([FAW]), opened["case_id"]))
    con.commit()
    return opened


def test_water_spraying_does_not_exempt_pesticide_mixing():
    passage = knowledge.reference(FAW)
    variants = [
        EXPLOIT,
        f"{MIX} {REFERRAL}",
        f"{REFERRAL} Mix both pesticides, and spray water every week.",
        f"{REFERRAL} Spray water every week; mix both pesticides.",
        "If the insects remain, mix both pesticides and spray water every week.",
        "Do not mix both pesticides and spray water every week.",
        "Mix both pesticides and spray water every week!",
    ]
    for text in variants:
        result = safety_gate.assess(text, [passage], question="Fall armyworm is eating my maize.")
        assert result.outcome == "safety_blocked", text
        assert any(finding.rule_id == "S3" for finding in result.findings), text
    water = safety_gate.assess("Spray clean water every week.", [], question="How do I water my maize?")
    assert water.outcome == "pass"
    assert not any(finding.rule_id == "S3" for finding in water.findings)
    assert safety_gate.assess("Spray water on the soil.", [], question="How do I water my maize?").outcome == "pass"


def test_supporting_judge_cannot_release_the_mixing_exploit():
    client = TestClient(app)
    opened = _faw_case(client)
    blocked = _approve(client, opened["case_id"], EXPLOIT)
    assert blocked.status_code == 422, blocked.text
    detail = blocked.json()["detail"]
    assert detail["outcome"] == "safety_blocked"
    assert detail.get("judge_status") != "supported"
    assert any(finding["rule_id"] == "S3" for finding in detail["findings"])
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["status"] == "pending_review"
    assert stored["farmer_text"] is None
    released = client.post(f"/cases/{opened['case_id']}/release", headers=_officer())
    assert released.status_code == 409
    farmer = _view(client, opened).json()
    assert farmer["answer"] is None
    assert "mix both pesticides" not in json.dumps(farmer).casefold()


def test_uncertainty_prefix_does_not_make_a_referral_relevant_or_releasable():
    client = TestClient(app)
    harvest = knowledge.reference("APNI-SARI-2023:harvest")
    prefixed = f"I am not sure. {REFERRAL}"
    held = safety_gate.assess(prefixed, [harvest], question=HARVEST_Q)
    assert held.to_dict()["relevance"]["status"] == "unrelated"
    assert held.to_dict()["relevance"]["status"] != "not_applicable"
    assert held.outcome == "review_required"
    opened = client.post("/ask", json={"question": HARVEST_Q}).json()
    blocked = _approve(client, opened["case_id"], prefixed)
    assert blocked.status_code == 422, blocked.text
    assert any(finding["rule_id"] == "RELEVANCE" for finding in blocked.json()["detail"]["findings"])
    assert db.get_case(db.connect(), opened["case_id"])["status"] == "pending_review"

    yellow = client.post("/ask", json={"question": YELLOW}).json()
    assert yellow.get("evidence_gap") is True
    uncertain = safety_gate.assess(REFERRAL, [], question=YELLOW)
    assert uncertain.to_dict()["relevance"]["status"] == "uncertain"
    assert uncertain.outcome == "review_required"
    prefixed_gap = safety_gate.assess(prefixed, [], question=YELLOW)
    assert prefixed_gap.to_dict()["relevance"]["status"] == "uncertain"
    assert prefixed_gap.outcome != "pass"
    for text in (REFERRAL, prefixed):
        decision = _approve(client, yellow["case_id"], text)
        assert decision.status_code == 422, decision.text
        assert decision.json()["detail"]["outcome"] != "pass"
        assert decision.json()["detail"].get("judge_status") != "supported"
    assert db.get_case(db.connect(), yellow["case_id"])["farmer_text"] is None
    farmer = _view(client, yellow).json()
    assert farmer["answer"] is None
    assert farmer["evidence_gap"] is True
    assert farmer["message"] == GAP_MESSAGE


def _seal(case_id: int, farmer_text: str) -> str:
    """Store an assessed approval the way an older policy release would find it."""
    con = db.connect()
    con.execute(
        "UPDATE cases SET status='approved', farmer_text=?, final_text=?, officer=?, "
        "revision=revision+1, decided_at=?, updated_at=? WHERE id=?",
        (farmer_text, farmer_text, "Ama Mensah", db.now(), db.now(), case_id))
    con.commit()
    row = db.get_case(con, case_id)
    ctx = approval.context(con, row)
    payload = {
        "farmer_text": farmer_text, "officer_text": row["draft"], "officer": "Ama Mensah",
        "context": ctx, "assessment": {"outcome": "pass", "judge_status": "not_required", "findings": []},
        "binding": "historical", "voice_script": None,
    }
    encoded = json.dumps(payload)
    con.execute(
        "INSERT INTO approvals(case_id,revision,submission_id,assessment_id,payload,fingerprint,provenance,created_at) "
        "VALUES (?,?,NULL,NULL,?,?,'assessed',?)",
        (case_id, row["revision"], encoded, safety_gate.fingerprint(payload), db.now()))
    con.commit()
    return encoded


def test_historical_source_free_uncertainty_is_not_released_and_a_supported_approval_is():
    client = TestClient(app)
    headers = _officer()
    yellow = client.post("/ask", json={"question": YELLOW}).json()
    before = _seal(yellow["case_id"], "I do not know.")
    released = client.post(f"/cases/{yellow['case_id']}/release", headers=headers)
    assert released.status_code == 422, released.text
    detail = released.json()["detail"]
    assert detail["outcome"] == "review_required"
    assert any(finding["rule_id"] == "EVIDENCE_GAP" for finding in detail["findings"])
    con = db.connect()
    assert con.execute("SELECT payload FROM approvals WHERE case_id=?", (yellow["case_id"],)).fetchone()[0] == before
    assert db.get_case(con, yellow["case_id"])["status"] == "approved"
    farmer = _view(client, yellow).json()
    assert farmer["answer"] is None
    assert "i do not know" not in json.dumps(farmer).casefold()

    harvest = client.post("/ask", json={"question": HARVEST_Q}).json()
    proposal = client.get(f"/officer/cases/{harvest['case_id']}", headers=headers).json()["farmer_draft"]["text"]
    sealed = _seal(harvest["case_id"], proposal)
    ok = client.post(f"/cases/{harvest['case_id']}/release", headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "released"
    again = client.post(f"/cases/{harvest['case_id']}/release", headers=headers)
    assert again.status_code == 200, again.text
    assert con.execute("SELECT payload FROM approvals WHERE case_id=?", (harvest["case_id"],)).fetchone()[0] == sealed
    seen = _view(client, harvest).json()
    assert seen["answer"] == proposal


def test_an_already_delivered_historical_message_is_not_sent_again():
    client = TestClient(app)
    headers = _officer()
    yellow = client.post("/ask", json={"question": YELLOW}).json()
    con = db.connect()
    db.save_contact(con, yellow["case_id"], channel="simulator", sender_id="sim:historical-1")
    _seal(yellow["case_id"], "I do not know.")
    approval_id = con.execute("SELECT id FROM approvals WHERE case_id=?", (yellow["case_id"],)).fetchone()[0]
    con.execute("UPDATE cases SET status='released' WHERE id=?", (yellow["case_id"],))
    con.execute(
        "INSERT INTO delivery_jobs(approval_id,channel,recipient_hash,state,updated_at) VALUES (?,?,?,'accepted',?)",
        (approval_id, "simulator", db._token_hash("sim:historical-1"), db.now()))
    con.commit()
    payload = con.execute("SELECT payload FROM approvals WHERE id=?", (approval_id,)).fetchone()[0]
    again = client.post(f"/cases/{yellow['case_id']}/release", headers=headers)
    assert again.status_code == 200, again.text
    assert con.execute("SELECT count(*) FROM delivery_jobs WHERE approval_id=?", (approval_id,)).fetchone()[0] == 1
    assert con.execute("SELECT state FROM delivery_jobs WHERE approval_id=?", (approval_id,)).fetchone()[0] == "accepted"
    assert con.execute("SELECT payload FROM approvals WHERE id=?", (approval_id,)).fetchone()[0] == payload
    farmer = _view(client, yellow).json()
    assert farmer["answer"] is None


def _fail_retrieval(monkeypatch):
    """Replace the graph node. The node list keeps the function object from import."""
    async def retrieve(_state, _tools):
        raise RuntimeError("forced retrieval failure")

    monkeypatch.setattr(agent, "NODES", [retrieve if fn.__name__ == "retrieve" else fn for fn in agent.NODES])


def test_retrieval_failure_during_clarification_keeps_the_chemical_warning(monkeypatch):
    _fail_retrieval(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    opened = client.post("/ask", json={"question": CHEMICAL_Q}).json()
    first = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "maize", "expected_revision": opened["revision"]})
    assert first.status_code == 200, first.text
    failed = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "Wa", "expected_revision": first.json()["revision"]})
    assert failed.status_code >= 500, failed.text
    row = db.get_case(db.connect(), opened["case_id"])
    assert row["priority"] == "urgent"
    reasons = json.loads(row["urgent_reasons"] or "[]")
    assert any("chemical" in reason for reason in reasons)
    stored = json.loads(row["farmer_draft"])
    assert any("chemical" in reason for reason in stored.get("safety_context") or [])
    seen = _view(client, opened).json()
    assert seen["answer"] is None
    assert seen.get("processing_failure") is True
    assert "no treatment advice" in seen["message"].casefold()
    retry = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "Wa", "expected_revision": seen["revision"]})
    assert retry.status_code >= 500, retry.text
    assert db.connect().execute("SELECT count(*) FROM cases").fetchone()[0] == 1
    kept = db.get_case(db.connect(), opened["case_id"])
    assert kept["priority"] == "urgent"
    assert any("chemical" in reason for reason in json.loads(kept["urgent_reasons"] or "[]"))


def test_a_normal_planting_clarification_stays_routine_when_retrieval_fails(monkeypatch):
    _fail_retrieval(monkeypatch)
    client = TestClient(app, raise_server_exceptions=False)
    opened = client.post("/ask", json={"question": "When should I plant?"}).json()
    maize = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "maize", "expected_revision": opened["revision"]})
    assert maize.status_code == 200, maize.text
    failed = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "Tamale", "expected_revision": maize.json()["revision"]})
    assert failed.status_code >= 500, failed.text
    row = db.get_case(db.connect(), opened["case_id"])
    reasons = json.loads(row["urgent_reasons"] or "[]")
    assert row["priority"] == "routine"
    assert not any("chemical" in reason or "disease" in reason for reason in reasons)


def test_clarification_completion_and_lookup_use_the_same_evidence_gap_message():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": CROP_YELLOW}).json()
    assert opened["status"] == "draft"
    done = client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": "maize", "expected_revision": opened["revision"]})
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["answer"] is None
    assert body["evidence_gap"] is True
    assert body["message"] == GAP_MESSAGE
    seen = _view(client, opened).json()
    assert seen["answer"] is None
    assert seen["evidence_gap"] is True
    assert seen["message"] == body["message"]
    assert client.get(f"/farmer/cases/{opened['case_id']}").status_code == 404


def test_evidence_gap_completion_is_the_message_on_the_farmer_screen(monkeypatch):
    import httpx
    from streamlit import env_util
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    client = TestClient(app)
    opened = client.post("/ask", json={"question": CROP_YELLOW}).json()

    def backend(method, url, **kwargs):
        path = url[url.find("/"):] if "://" in url else url
        response = client.request(method, path, headers=kwargs.get("headers"), json=kwargs.get("json"))
        return httpx.Response(response.status_code, content=response.content)

    monkeypatch.setattr(httpx, "request", backend)
    screen = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    screen.session_state["farmer_supplement_case"] = opened["case_id"]
    screen.session_state["farmer_supplement_revision"] = opened["revision"]
    screen.session_state["farmer_supplement_token"] = opened["access_token"]
    screen.run()
    screen.text_input(key="farmer_supplement_text").set_value("maize")
    screen.button(key="farmer_supplement_button").click().run()
    visible = " ".join(item.value for item in list(screen.info) + list(screen.success) + list(screen.warning) + list(screen.error))
    assert GAP_MESSAGE in visible
    assert not any(item.value for item in screen.success if "approved advice" in item.value.casefold() and "no treatment" not in item.value.casefold())
