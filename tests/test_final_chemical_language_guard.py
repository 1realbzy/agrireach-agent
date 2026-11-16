"""Contextual chemical mixing: generic "products" cannot hide a pesticide instruction.

The offline judge supports every sentence. These tests follow the approval and
release functions, and check that the farmer does not receive withheld text.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agrireach import db, safety_gate
from agrireach.api import app

PEST_Q = "Can I mix two pesticides on my maize in Wa and spray every week?"
COMPOST_Q = "How should I mix compost and manure for maize before planting in Wa?"
PRODUCTS = "Mix both products and spray water every week."
PESTICIDES = "Mix both pesticides and spray water every week."
REFERRAL = "Consult your local AEA before choosing or applying a pesticide."
WATER = "Spray water on the soil."
COMPOST = "Mix the compost and the manure together before planting."
PROHIBITION = "Never mix two pesticides."
UNRELIABLE_BAN = "Do not mix both pesticides and spray water every week."


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def _approve(client, case_id, text):
    row = db.get_case(db.connect(), case_id)
    return client.post(
        f"/officer/cases/{case_id}/decision", headers=_officer(),
        json={"decision": "approve", "confirmed": True, "farmer_text": text,
              "expected_revision": row["revision"]})


def _open(client, question):
    opened = client.post("/ask", json={"question": question}).json()
    assert opened["status"] == "pending_review", opened
    con = db.connect()
    con.execute("UPDATE cases SET sources=? WHERE id=?", (json.dumps([]), opened["case_id"]))
    con.commit()
    return opened


def _view(client, opened):
    return client.get(
        f"/farmer/cases/{opened['case_id']}",
        headers={"X-Case-Access-Token": opened["access_token"]})


def test_products_wording_is_blocked_in_chemical_context_and_not_released():
    variants = [
        PRODUCTS,
        f"{REFERRAL} {PRODUCTS}",
        f"{PRODUCTS} {REFERRAL}",
        "Mix both products, and spray water every week.",
        "Spray water every week; mix both products.",
        "If the insects remain, mix both products and spray water every week.",
        "Use both products and spray water every week.",
        f"{WATER} {PRODUCTS}",
    ]
    for text in variants:
        result = safety_gate.assess(text, [], question=PEST_Q)
        assert result.outcome == "safety_blocked", text
        mixing = [finding for finding in result.findings if finding.rule_id == "S3"]
        assert mixing, text
        assert all(WATER not in finding.sentence for finding in mixing)
    water = safety_gate.assess(WATER, [], question=PEST_Q)
    assert water.outcome == "pass"
    assert not water.findings

    client = TestClient(app)
    opened = _open(client, PEST_Q)
    blocked = _approve(client, opened["case_id"], f"{REFERRAL} {PRODUCTS}")
    assert blocked.status_code == 422, blocked.text
    detail = blocked.json()["detail"]
    assert detail["outcome"] == "safety_blocked"
    assert any(finding["rule_id"] == "S3" for finding in detail["findings"])
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["status"] == "pending_review"
    assert stored["farmer_text"] is None
    released = client.post(f"/cases/{opened['case_id']}/release", headers=_officer())
    assert released.status_code == 409
    farmer = _view(client, opened).json()
    assert farmer["answer"] is None
    assert "mix both products" not in json.dumps(farmer).casefold()


def test_pesticide_wording_stays_blocked():
    result = safety_gate.assess(f"{REFERRAL} {PESTICIDES}", [], question=PEST_Q)
    assert result.outcome == "safety_blocked"
    assert any(finding.rule_id == "S3" for finding in result.findings)
    client = TestClient(app)
    opened = _open(client, PEST_Q)
    blocked = _approve(client, opened["case_id"], PESTICIDES)
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"]["outcome"] == "safety_blocked"
    assert _view(client, opened).json()["answer"] is None


def test_nonchemical_mixing_is_not_a_pesticide_instruction():
    result = safety_gate.assess(COMPOST, [], question=COMPOST_Q)
    assert result.outcome == "pass"
    assert not any(finding.rule_id == "S3" for finding in result.findings)
    products = safety_gate.assess(PRODUCTS, [], question=COMPOST_Q)
    assert products.outcome == "pass"
    assert not products.findings
    client = TestClient(app)
    opened = _open(client, COMPOST_Q)
    decision = _approve(client, opened["case_id"], COMPOST)
    assert decision.status_code == 422, decision.text
    detail = decision.json()["detail"]
    assert detail["outcome"] != "safety_blocked"
    assert not any(finding["rule_id"] == "S3" for finding in detail["findings"])
    assert _view(client, opened).json()["answer"] is None


def test_a_clear_mixing_ban_is_not_an_instruction_to_mix():
    banned = safety_gate.assess(PROHIBITION, [], question=PEST_Q)
    assert banned.outcome == "pass"
    assert not any(finding.rule_id == "S3" for finding in banned.findings)
    products_ban = safety_gate.assess("Do not mix these products.", [], question=PEST_Q)
    assert products_ban.outcome == "pass"
    unreliable = safety_gate.assess(UNRELIABLE_BAN, [], question=PEST_Q)
    assert unreliable.outcome == "safety_blocked"
    assert any(finding.rule_id == "S3" for finding in unreliable.findings)
    named = safety_gate.assess("Never mix glyphosate with another pesticide.", [], question=PEST_Q)
    assert named.outcome == "safety_blocked"

    client = TestClient(app)
    opened = _open(client, PEST_Q)
    decision = _approve(client, opened["case_id"], PROHIBITION)
    assert decision.status_code == 422, decision.text
    detail = decision.json()["detail"]
    assert detail["outcome"] == "review_required"
    assert not any(finding["rule_id"] == "S3" for finding in detail["findings"])
    assert db.get_case(db.connect(), opened["case_id"])["farmer_text"] is None
    farmer = _view(client, opened).json()
    assert farmer["answer"] is None
    assert "never mix" not in json.dumps(farmer).casefold()
