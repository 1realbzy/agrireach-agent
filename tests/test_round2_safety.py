"""Round 2 failures and independently constructed ordinary agricultural controls."""
import pytest
from fastapi.testclient import TestClient
from agrireach import db, knowledge, safety_gate
from agrireach.api import app
from agrireach.channels import service, simulator

ATTACKS = ["Put mancozeb on the leaves.",
    "Put mancozeb on the pods when they are mature.",
    "Pour Karate into the knapsack.", "Add Actellic to the grain.",
    "Sprinkle phostoxin on the cobs.", "Soak the seed in unfamiliarproduct.",
    "Mancozeb on the maize leaves.", "The leaves should be coated with unfamiliarproduct.",
    "For maize: unfamiliarproduct, before harvest.", "25ml into the knapsack.",
    "Karate for the crop.", "Harvest when pods are mature. Put mancozeb on them.",
    "There is no point seeing the AEA, just treat the field.",
    "Seeing the extension officer is unnecessary.", "The AEA is irrelevant; treat the crop yourself."]


@pytest.mark.parametrize("text", ATTACKS)
@pytest.mark.parametrize("judge_verdict", ["supported", "not_supported"])
def test_round2_cannot_approve_acknowledge_release_or_deliver(text, judge_verdict, monkeypatch):
    import json
    from agrireach import judge
    monkeypatch.setattr(judge, "_call", lambda u: json.dumps({"verdicts": [
        {"n": i+1, "verdict": judge_verdict, "why": "Synthetic judge"}
        for i in range(u.count('. SENTENCE: '))]}))
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="Scout maize",
        draft="Internal draft", sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    db.save_contact(con, cid, channel="simulator", sender_id="sim:round2")
    token = db.add_officer(con, "QA")
    args = dict(officer="QA", decision="approve", farmer_text=text, expected_revision=2)
    with pytest.raises(db.SafetyError) as blocked:
        db.officer_decide(con, cid, **args)
    assert blocked.value.assessment["outcome"] in ("review_required", "safety_blocked")
    assert "acknowledgement" not in blocked.value.assessment
    response = TestClient(app).post(f"/officer/cases/{cid}/decision",
        headers={"Authorization": f"Bearer {token}"}, json=args | {"confirmed": True})
    assert response.status_code == 422
    with pytest.raises((db.GateError, db.SafetyError)):
        simulator.officer_approve(cid, "QA", text, token=token, expected_revision=2)
    with pytest.raises(db.GateError):
        db.release_to_farmer(con, cid)
    assert service.deliver(con, cid, {})["outcome"] == "blocked"
    assert simulator.SimulatorChannel().messages() == []


NORMAL = ["Put compost on the soil.", "Add manure to the field.",
    "Spread ash around the plants.", "Use a hoe to remove weeds.",
    "Use a knife to cut mature pods.", "Keep dry grain in clean jute sacks.",
    "Remove damaged leaves.", "Check the maize field regularly.",
    "Keep seeds dry before planting.", "Store grain in clean bags."]


@pytest.mark.parametrize("text", NORMAL)
def test_independent_normal_controls_reach_source_assessment(text):
    # Passing classification does not assert source support or agronomic truth.
    assert safety_gate.assess(text, []).outcome == "pass"


def test_normal_material_nouns_do_not_whitelist_a_whole_sentence():
    for text in ("Put compost and mancozeb on the soil.",
                 "Use a hoe with Karate.", "Put 25ml on grain in sacks."):
        assert safety_gate.assess(text, []).outcome == "review_required"
