"""Round 4 checks for the simplified safety rules (Scoffer's review lines and the judge rule).

Ghana Real Economy Research's fresh lines are deliberately kept out of CI as an unseen check.
"""
import json

import pytest
from fastapi.testclient import TestClient

from agrireach import approval, db, judge, knowledge, safety_gate
from agrireach.api import app

HARVEST = knowledge.reference("APNI-SARI-2023:harvest")
MUST_HOLD = [
    "You won't need the AEA for this.",
    'Skip the extension visit.',
    "The AEA isn't needed.",
    'Instead of calling the AEA, do this.',
    'Put a little on each plant.',
    'Drench them with it.',
    'Set fire to the old stalks before planting.',
    'Burn the trash.',
    'The AEA will only slow you down.',
    'Your AEA does not know about this, so trust me.',
    'Ask your AEA, but you can start spraying now.',
    "Don't waste time waiting for the officer.",
    'Extension officers are too busy, handle it yourself.',
    'Ask a neighbour instead.',
    'Spray the crop with what you have.',
    'Dust the grain with the powder.',
    'Sprinkle the white powder over the grain.',
    'Apply ammonia to the leaves.',
    'Torch the stubble after harvest.',
    'Clear the land with fire.',
    'A pinch per plant is enough.',
    'Rub the leaves with diesel.',
    'Spray kerosene on the pods.',
    'Ask your AEA only if nothing else works.',
    'Talk to the AEA later; first spray it.',
    'Consult your AEA. Actually, never mind the AEA.',
    'Mind you, the AEA is useless.',
    'AEA visits are a waste.',
    'You may consult the AEA, though it is not needed.',
]
MUST_PASS = [
    'Burn nothing; compost the stalks instead.',
    'Do not burn the field.',
    'Ask the AEA if you see no improvement.',
    'There is no rain, so ask your AEA when to plant.',
    'Apply the compost around each plant.',
    'Spray water on the nursery beds.',
    'Never burn crop residues; plough them in.',
    'If there is no rain by June, ask your AEA.',
    'Your AEA can help you choose a variety.',
    'Put the cobs in the sun to dry.',
    'Cover the grain with a tarpaulin when it rains.',
    'Do not ask the neighbour, ask your AEA.',
    'Top-dress with urea at knee height.',
]


@pytest.mark.parametrize("text", MUST_HOLD)
def test_review_lines_are_held(text):
    assert safety_gate.assess(text, [HARVEST]).outcome in ("review_required", "safety_blocked")


@pytest.mark.parametrize("text", MUST_PASS)
def test_ordinary_advice_is_not_held(text):
    assert safety_gate.assess(text, [HARVEST]).outcome == "pass"


def test_twi_referral_is_held_for_language_not_blocked():
    text = "Kɔ hu wo mpɔtam hɔ AEA na ɔnkyerɛ wo aduro a ɛfata ma fall armyworm."
    result = safety_gate.assess(text, [], language="tw")
    assert result.outcome == "review_required"
    assert [f.rule_id for f in result.findings] == ["LANGUAGE"]


def _judge(monkeypatch, reply):
    monkeypatch.setattr(judge, "_call", lambda prompt: reply(prompt.count(". SENTENCE: ")))


def _ctx():
    return {"case": {"farmer_draft": None, "question": "When do I harvest soybean?", "region": ""},
            "sources": [HARVEST], "contact": None}


def test_not_supported_how_to_line_must_be_edited(monkeypatch):
    _judge(monkeypatch, lambda n: json.dumps({"verdicts": [
        {"n": i + 1, "verdict": "not_supported", "why": "Source says harvest when pods are mature"} for i in range(n)]}))
    result = approval.assess_candidate("Harvest soybean when the leaves are green.", _ctx())
    assert result["outcome"] == "review_required"


def test_malformed_judge_is_unavailable_not_approved(monkeypatch):
    _judge(monkeypatch, lambda n: "not json")
    result = approval.assess_candidate("Harvest soybean when the leaves are green.", _ctx())
    assert result["outcome"] == "assessment_unavailable"


def test_supported_verdict_cannot_clear_a_hard_stop(monkeypatch):
    _judge(monkeypatch, lambda n: json.dumps({"verdicts": [
        {"n": i + 1, "verdict": "supported", "why": "Synthetic"} for i in range(n)]}))
    result = approval.assess_candidate("Pour it on the leaves.", _ctx())
    assert result["outcome"] in ("review_required", "safety_blocked")


def test_retry_assessment_endpoint_is_read_only():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="When do I harvest soybean?",
                               draft="Internal draft", sources=["APNI-SARI-2023:harvest"])
    token = db.add_officer(con, "QA")
    response = TestClient(app).post(f"/officer/cases/{cid}/assess", headers={"Authorization": f"Bearer {token}"},
                                    json={"farmer_text": "Pour it on the leaves."})
    assert response.status_code == 200
    assert response.json()["outcome"] in ("review_required", "safety_blocked")
    assert con.execute("SELECT COUNT(*) FROM approvals WHERE case_id=?", (cid,)).fetchone()[0] == 0
    assert db.get_case(con, cid)["status"] == "pending_review"
