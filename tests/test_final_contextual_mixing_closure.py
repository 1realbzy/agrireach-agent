"""Noun-free chemical mixing cannot hide behind a water spray.

A maize fall-armyworm source is attached and the offline judge supports every
sentence. These tests follow safety assessment, officer approval, release, and
the farmer's authorized view.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agrireach import db, knowledge, safety_gate
from agrireach.api import app

FAW = "APNI-SARI-2023-MAIZE:p20-faw-control"
FAW_Q = "Fall armyworm is eating my maize in Wa. What should I do?"
PEST_Q = "Can I mix two pesticides on my maize in Wa and spray every week?"
REFERRAL = "Consult your local AEA before choosing or applying a pesticide."
CANDIDATES = (
    "Mix both agrochemicals and spray water every week to control infestations.",
    "Mix both and spray water every week to control infestations.",
    "Mix both of these and spray water every week to control infestations.",
)


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def _approve(client, case_id, text):
    row = db.get_case(db.connect(), case_id)
    return client.post(
        f"/officer/cases/{case_id}/decision", headers=_officer(),
        json={"decision": "approve", "confirmed": True, "farmer_text": text,
              "expected_revision": row["revision"]})


def _open(client):
    opened = client.post("/ask", json={"question": FAW_Q}).json()
    con = db.connect()
    con.execute("UPDATE cases SET sources=? WHERE id=?", (json.dumps([FAW]), opened["case_id"]))
    con.commit()
    return opened


def _view(client, opened):
    return client.get(
        f"/farmer/cases/{opened['case_id']}",
        headers={"X-Case-Access-Token": opened["access_token"]})


def _assert_s3_blocked(text, question, passages):
    result = safety_gate.assess(text, passages, question=question)
    assert result.outcome == "safety_blocked", (text, result.outcome, result.findings)
    assert any(finding.rule_id == "S3" for finding in result.findings), text
    return result


def test_noun_free_mixing_is_blocked_and_not_released():
    passage = knowledge.reference(FAW)
    client = TestClient(app)
    for sentence in CANDIDATES:
        text = f"{REFERRAL} {sentence}"
        result = _assert_s3_blocked(text, FAW_Q, [passage])
        assert any(sentence in finding.sentence for finding in result.findings if finding.rule_id == "S3")
        opened = _open(client)
        blocked = _approve(client, opened["case_id"], text)
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
        assert sentence.casefold() not in json.dumps(farmer).casefold()


def test_spacing_order_and_chemical_wording_stay_blocked():
    passage = knowledge.reference(FAW)
    with_referral = [
        f"{REFERRAL} Mix both, and spray water every week to control infestations.",
        f"{REFERRAL} Mix both  and  spray water every week to control infestations.",
        f"{REFERRAL} Spray water every week and mix both to control infestations.",
        f"{REFERRAL} Mix both and spray water to control infestations.",
        f"{REFERRAL} Combine both and spray water every week to control infestations.",
        f"{REFERRAL} Blend both of these and spray water every week to control infestations.",
    ]
    for text in with_referral:
        _assert_s3_blocked(text, FAW_Q, [passage])
    _assert_s3_blocked(
        "Mix both agrochemicals and spray water every week to control infestations.",
        FAW_Q, [])
    _assert_s3_blocked(
        "Mix both of these and spray water every week to control infestations.",
        PEST_Q, [])
    _assert_s3_blocked(
        "Mix both and spray water every week to control infestations.",
        "Should I use agrochemicals on my maize in Wa?", [])


def test_water_spraying_and_nonchemical_mixing_stay_available():
    passage = knowledge.reference(FAW)
    safe = [
        ("Mix compost with manure before planting.", "How should I mix compost and manure for maize before planting in Wa?", []),
        ("Mix compost with manure before planting.", PEST_Q, []),
        ("Mix feed ingredients thoroughly.", "How should I mix feed ingredients for my animals?", []),
        ("Water the maize plants when needed.", "When should I water the maize plants?", []),
        ("Spray water on the soil.", PEST_Q, []),
        ("Spray clean water every week.", "How do I water my maize?", []),
        ("Never mix two pesticides.", PEST_Q, []),
        ("Never mix two agrochemicals.", PEST_Q, []),
        (f"{REFERRAL} Never mix two pesticides.", FAW_Q, [passage]),
    ]
    for text, question, passages in safe:
        result = safety_gate.assess(text, passages, question=question)
        assert result.outcome == "pass", (text, result.outcome, result.findings)
        assert not any(finding.rule_id == "S3" for finding in result.findings), text
    held = safety_gate.assess("Products must not be mixed.", [], question=PEST_Q)
    assert held.outcome == "review_required"
    assert any(finding.rule_id == "S3" for finding in held.findings)
    blocked = safety_gate.assess(
        f"{REFERRAL} Mix both products and spray water every week.", [passage], question=FAW_Q)
    assert blocked.outcome == "safety_blocked"
    assert any(finding.rule_id == "S3" for finding in blocked.findings)
    pesticides = safety_gate.assess(
        f"{REFERRAL} Mix both pesticides and spray water every week.", [passage], question=FAW_Q)
    assert pesticides.outcome == "safety_blocked"
    assert any(finding.rule_id == "S3" for finding in pesticides.findings)
