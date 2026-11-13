"""Offline recheck of the soybean harvest workflow that passed live inference.

Uses the curated harvest passage and the deterministic stub. It does not call a
provider and does not replace the saved live-evaluation evidence.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

QUESTION = "When should I harvest soybean in Tamale?"
SOURCE = "APNI-SARI-2023:harvest"


def test_soybean_harvest_retrieves_cites_and_returns_the_approved_text():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    opened = client.post("/ask", json={"question": QUESTION}).json()
    assert opened["status"] == "pending_review"
    assert opened.get("evidence_gap") is not True
    assert opened.get("clarification") in (None, "")
    case_id = opened["case_id"]
    case = client.get(f"/officer/cases/{case_id}", headers=headers).json()
    assert SOURCE in case["sources"]
    assert f"[{SOURCE}]" in case["draft"]
    assert "9 out of 10 pods" in case["draft"]
    assert case["draft"].startswith("[OFFLINE STUB DRAFT")
    proposal = case["farmer_draft"]["text"]
    assert "9 out of 10 pods" in proposal
    assert "[" not in proposal
    assert "i do not know" not in proposal.casefold()
    approved = client.post(
        f"/officer/cases/{case_id}/decision", headers=headers,
        json={"decision": "approve", "confirmed": True, "farmer_text": proposal,
              "expected_revision": case["revision"]})
    assert approved.status_code == 200, approved.text
    body = approved.json()
    assert body["status"] == "released"
    farmer = client.get(
        f"/farmer/cases/{case_id}",
        headers={"X-Case-Access-Token": opened["access_token"]}).json()
    assert farmer["answer"] == proposal
    assert farmer["approved_by"] == "Ama Mensah"
    assert farmer.get("evidence_gap") is not True
