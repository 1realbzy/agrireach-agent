"""A pesticide-mixing question keeps its safety context while the crop is missing.

Clarification may ask which crop. It must not drop the chemical risk, diagnose a
disease, or let a later reply approve weekly mixing.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agrireach import db, llm
from agrireach.api import app

MIXING = "Can I mix two pesticides and spray every week to kill insects faster?"
PLANTING = "When should I plant in Tamale?"
MIX_TEXT = "Mix two pesticides and spray every week."


def _headers():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def _view(client, opened):
    return client.get(
        f"/farmer/cases/{opened['case_id']}",
        headers={"X-Case-Access-Token": opened["access_token"]}).json()


def _supplement(client, opened, text, revision):
    return client.post(
        f"/farmer/cases/{opened['case_id']}/supplement",
        headers={"X-Case-Access-Token": opened["access_token"]},
        json={"text": text, "expected_revision": revision})


def test_missing_crop_keeps_the_chemical_risk_and_does_not_draft(monkeypatch):
    calls = {"draft": 0}

    def draft(*_args, **_kwargs):
        calls["draft"] += 1
        raise AssertionError("clarification must not call the draft model")

    monkeypatch.setattr(llm, "draft", draft)
    client = TestClient(app)
    opened = client.post("/ask", json={"question": MIXING}).json()
    assert opened["status"] == "draft"
    assert "which crop" in opened["clarification"].casefold()
    assert "diagnos" not in opened["clarification"].casefold()
    assert "mix" not in opened["clarification"].casefold()
    assert calls["draft"] == 0
    row = db.get_case(db.connect(), opened["case_id"])
    reasons = json.loads(row["urgent_reasons"] or "[]")
    assert any("chemical" in reason for reason in reasons)
    assert row["priority"] == "urgent"
    assert (row["draft"] or "") == ""
    stored = json.loads(row["farmer_draft"])
    assert stored["text"] == ""
    assert any("chemical" in reason for reason in stored.get("safety_context") or [])
    farmer = _view(client, opened)
    assert farmer["answer"] is None
    assert "which crop" in farmer["clarification"].casefold()
    assert "diagnos" not in json.dumps(farmer).casefold()


def test_a_later_crop_answer_cannot_approve_weekly_mixing():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": MIXING}).json()
    crop = _supplement(client, opened, "maize", _view(client, opened)["revision"])
    assert crop.status_code == 200, crop.text
    assert crop.json()["status"] == "draft"
    assert "district" in crop.json()["clarification"].casefold() or "region" in crop.json()["clarification"].casefold()
    held = db.get_case(db.connect(), opened["case_id"])
    assert any("chemical" in reason for reason in json.loads(held["urgent_reasons"] or "[]"))
    place = _supplement(client, opened, "Wa", crop.json()["revision"])
    assert place.status_code == 200, place.text
    finished = place.json()
    assert finished["status"] == "pending_review"
    assert finished.get("answer") is None
    row = db.get_case(db.connect(), opened["case_id"])
    reasons = json.loads(row["urgent_reasons"] or "[]")
    assert any("chemical" in reason for reason in reasons)
    assert row["priority"] == "urgent"
    assert row["question"] == MIXING
    blocked = client.post(
        f"/officer/cases/{opened['case_id']}/decision", headers=_headers(),
        json={"decision": "approve", "confirmed": True, "farmer_text": MIX_TEXT,
              "expected_revision": row["revision"]})
    assert blocked.status_code == 422, blocked.text
    detail = blocked.json()["detail"]
    assert detail["outcome"] == "safety_blocked"
    assert any(finding["rule_id"] == "S3" for finding in detail["findings"])
    assert db.get_case(db.connect(), opened["case_id"])["status"] == "pending_review"
    farmer = _view(client, opened)
    assert farmer["answer"] is None
    assert "mix two pesticides" not in json.dumps(farmer).casefold()


def test_a_missing_crop_planting_question_is_not_a_chemical_diagnosis():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": PLANTING}).json()
    assert opened["status"] == "draft"
    assert "which crop" in opened["clarification"].casefold()
    assert "pesticide" not in opened["clarification"].casefold()
    assert "diagnos" not in opened["clarification"].casefold()
    row = db.get_case(db.connect(), opened["case_id"])
    reasons = json.loads(row["urgent_reasons"] or "[]")
    assert not any("chemical" in reason or "disease" in reason for reason in reasons)
    assert row["priority"] == "routine"
    stored = json.loads(row["farmer_draft"])
    assert "safety_context" not in stored
