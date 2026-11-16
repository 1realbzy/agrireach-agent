"""Stage C: a failed revalidation must not show legacy_unvalidated text as the farmer's answer."""
import hashlib
import json

import pytest
from fastapi.testclient import TestClient

from agrireach import approval, db, knowledge, safety_gate
from agrireach.api import app
from agrireach.ui import STATES

LEGACY = "LEGACY UNVALIDATED ADVICE"
AUTHORIZED = "Soybean should be harvested when 9 out of 10 pods are mature (brown in color or dry)."
UNSAFE = "Do not wear gloves when spraying pesticide."


def client():
    return TestClient(app)


def released_case(question="When should I harvest soybean in Tamale?", sources=None):
    con = db.connect()
    case_id = db.agent_upsert_case(
        con, status="draft", question=question, crop="soybean", region="tamale",
        draft="officer draft", sources=sources or [])
    con.execute("UPDATE cases SET status='released', officer='Ama Mensah', decided_at=? WHERE id=?", (db.now(), case_id))
    con.commit()
    return case_id


def insert_approval(case_id, payload, provenance):
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    fingerprint = safety_gate.fingerprint(payload) if provenance == "assessed" else hashlib.sha256(blob.encode()).hexdigest()
    if provenance == "assessed":
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    con = db.connect()
    revision = con.execute("SELECT revision FROM cases WHERE id=?", (case_id,)).fetchone()[0]
    con.execute(
        "INSERT INTO approvals(case_id,revision,payload,fingerprint,provenance,created_at) VALUES (?,?,?,?,?,?)",
        (case_id, revision, blob, fingerprint, provenance, db.now()))
    con.commit()
    return blob, fingerprint, provenance


def history(case_id):
    con = db.connect()
    return [tuple(row) for row in con.execute(
        "SELECT revision, payload, fingerprint, provenance, created_at FROM approvals WHERE case_id=? ORDER BY id",
        (case_id,))]


def legacy_payload():
    return {"status": "released", "farmer_text": LEGACY, "final_text": LEGACY, "officer": "Old Officer"}


def assessed_payload(case_id, farmer_text):
    con = db.connect()
    row = db.get_case(con, case_id)
    return {"farmer_text": farmer_text, "officer_text": "officer draft", "officer": "Ama Mensah",
            "context": approval.context(con, row), "assessment": {"outcome": "pass"}, "binding": "case-binding",
            "voice_script": None}


def test_gate_error_does_not_return_legacy_text_as_the_answer():
    case_id = released_case()
    insert_approval(case_id, legacy_payload(), "legacy_unvalidated")
    with pytest.raises(db.GateError) as caught:
        approval.validated_approval(db.connect(), case_id)
    assert not isinstance(caught.value, db.SafetyError)
    before = history(case_id)
    token = db.issue_farmer_case_token(db.connect(), case_id)
    other = released_case(question="A different farmer question")
    other_token = db.issue_farmer_case_token(db.connect(), other)
    view = client().get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token})
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["answer"] is None and body["status"] == "review_required"
    assert LEGACY not in json.dumps(body)
    assert "approved" not in STATES[body["status"]].casefold()
    assert client().get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": other_token}).status_code == 404
    assert history(case_id) == before


def test_safety_error_does_not_return_legacy_text_as_the_answer():
    case_id = released_case()
    insert_approval(case_id, legacy_payload(), "legacy_unvalidated")
    insert_approval(case_id, assessed_payload(case_id, UNSAFE), "assessed")
    with pytest.raises(db.SafetyError):
        approval.validated_approval(db.connect(), case_id)
    before = history(case_id)
    token = db.issue_farmer_case_token(db.connect(), case_id)
    view = client().get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token})
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["answer"] is None and body["status"] == "review_required"
    assert LEGACY not in json.dumps(body) and UNSAFE not in json.dumps(body)
    assert "approved" not in STATES[body["status"]].casefold()
    assert history(case_id) == before


def test_current_assessed_approval_is_returned_exactly():
    passage = knowledge.reference("APNI-SARI-2023:harvest")
    case_id = released_case(sources=[passage["id"]])
    insert_approval(case_id, legacy_payload(), "legacy_unvalidated")
    authorized = assessed_payload(case_id, AUTHORIZED)
    _blob, fingerprint, _provenance = insert_approval(case_id, authorized, "assessed")
    before = history(case_id)
    token = db.issue_farmer_case_token(db.connect(), case_id)
    body = client().get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token}).json()
    assert body["status"] == "released" and body["answer"] == AUTHORIZED
    assert body["answer"] != LEGACY
    row = db.get_case(db.connect(), case_id)
    approval_row = db.connect().execute(
        "SELECT revision, fingerprint, provenance FROM approvals WHERE case_id=? AND provenance='assessed'", (case_id,)).fetchone()
    assert approval_row["revision"] == row["revision"]
    assert approval_row["fingerprint"] == fingerprint == safety_gate.fingerprint(authorized)
    assert approval_row["provenance"] == "assessed"
    assert history(case_id) == before


def test_malformed_legacy_row_is_not_rewritten_or_shown():
    case_id = released_case()
    con = db.connect()
    revision = con.execute("SELECT revision FROM cases WHERE id=?", (case_id,)).fetchone()[0]
    blob = "not-json{{"
    fingerprint = "unchanged-fingerprint"
    con.execute(
        "INSERT INTO approvals(case_id,revision,payload,fingerprint,provenance,created_at) VALUES (?,?,?,?,?,?)",
        (case_id, revision, blob, fingerprint, "legacy_unvalidated", db.now()))
    con.commit()
    before = history(case_id)
    token = db.issue_farmer_case_token(db.connect(), case_id)
    view = client().get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token})
    assert view.status_code == 200, view.text
    body = view.json()
    assert body["answer"] is None and body["status"] == "review_required"
    assert history(case_id) == before
    assert history(case_id)[0][1] == blob and history(case_id)[0][2] == fingerprint
