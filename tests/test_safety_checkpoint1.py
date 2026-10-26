"""Frozen policy and application boundary regressions. No remote calls."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agrireach import db, knowledge, safety_gate
from agrireach.api import app

FIXTURES = json.loads((Path(__file__).parent / "fixtures/safety/frozen_cases.json").read_text())


@pytest.mark.parametrize("case", FIXTURES)
def test_frozen_policy(case):
    result = safety_gate.assess(case["text"], [knowledge.reference(i) for i in case["sources"]])
    if case["label"] == "legitimate":
        assert result.outcome == "pass", result.to_dict()
    else:
        assert result.outcome != "pass", result.to_dict()


def create_case(con):
    return db.agent_upsert_case(con, status="pending_review", question="FAW maize",
                               draft="Internal officer draft", sources=["APNI-SARI-2023-MAIZE:p20-faw-control"])


@pytest.mark.parametrize("text", ["Spray pesticide every week.", "Use any pesticide you have.",
    "Mix two pesticides and spray without gloves.", "Do not consult your local AEA before spraying.",
    "Check your maize at least once a week.",
    "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI). Spray pesticide every week."])
def test_original_api_bypasses_blocked(text):
    con = db.connect()
    token = db.add_officer(con, "Ama")
    cid = create_case(con)
    response = TestClient(app).post(f"/officer/cases/{cid}/decision",
        headers={"Authorization": f"Bearer {token}"}, json={"decision": "approve", "farmer_text": text,
                                                         "confirmed": True, "expected_revision": 1})
    assert response.status_code == 422, response.text
    assert db.get_case(con, cid)["status"] == "pending_review"
    assert con.execute("SELECT count(*) FROM advisory_submissions").fetchone()[0] == 1


def test_explicit_text_and_revision_and_exact_preservation():
    con = db.connect()
    cid = create_case(con)
    with pytest.raises(db.SafetyError):
        db.officer_decide(con, cid, officer="Ama", decision="approve", expected_revision=1)
    with pytest.raises(db.GateError, match="revision"):
        db.officer_decide(con, cid, officer="Ama", decision="approve", farmer_text="x")
    text = "  Consult your local agricultural extension officer before choosing or applying a pesticide.\n"
    result = db.officer_decide(con, cid, officer="Ama", decision="approve", farmer_text=text, expected_revision=1)
    assert result["farmer_text"] == text
    assert result["revision"] == 2


@pytest.mark.parametrize("text", ["Do not use unapproved pesticides.", "Do not spray without gloves."])
def test_protective_negation(text):
    assert safety_gate.assess(text, []).outcome == "pass"


def test_recovery_does_not_require_assessment():
    con = db.connect()
    cid = create_case(con)
    db.officer_decide(con, cid, officer="Ama", decision="request_info", expected_revision=1)
    row = db.reopen_case(con, cid, officer="Ama", expected_revision=2, information="Farmer clarified the crop")
    assert row["status"] == "pending_review"
    assert row["revision"] == 3
    db.officer_decide(con, cid, officer="Ama", decision="reject", expected_revision=3)
    assert db.get_case(con, cid)["status"] == "rejected"


def test_source_edits_invalidate_revision():
    con = db.connect()
    cid = create_case(con)
    with con:
        con.execute("UPDATE cases SET sources='[]' WHERE id=?", (cid,))
    with pytest.raises(db.GateError, match="stale_revision"):
        db.officer_decide(con, cid, officer="Ama", decision="reject", expected_revision=1)


def test_referral_must_cover_each_chemical_requirement():
    faw = knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")
    storage = knowledge.reference("APNI-SARI-2023-MAIZE:p22-sacks")
    herbicide = knowledge.reference("APNI-SARI-2023:weeds-herbicide")
    referral = safety_gate.sentences(faw["text"])[1]
    assert safety_gate.assess(referral, [faw]).outcome == "pass"
    # An armyworm referral cannot replace a separate preuse storage obligation.
    assert safety_gate.assess(referral, [faw, storage]).outcome == "safety_blocked"
    assert safety_gate.assess(referral, [herbicide]).outcome == "safety_blocked"
    general = "Consult your local agricultural extension officer before choosing or applying a pesticide."
    assert safety_gate.assess(general, [faw, storage, herbicide]).outcome == "pass"


def test_simulator_cli_cannot_release_unsafe_text(monkeypatch, capsys):
    from agrireach.channels import simulator
    con = db.connect()
    cid = create_case(con)
    token = db.add_officer(con, "Ama")
    db.save_contact(con, cid, channel="simulator", sender_id="sim:safety-test")
    monkeypatch.setenv("AGRIREACH_OFFICER_TOKEN", token)
    exit_code = simulator.main(["officer-approve", "--case", str(cid), "--officer", "Ama", "--revision",
                    str(db.get_case(con, cid)["revision"]), "--farmer-text", "Spray pesticide every week."])
    response = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert response["error"]["outcome"] == "safety_blocked"
    assert db.get_case(con, cid)["status"] == "pending_review"
    assert simulator.SimulatorChannel().messages() == []
