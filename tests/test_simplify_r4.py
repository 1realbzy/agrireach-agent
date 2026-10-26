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


def test_greeting_needs_no_source_but_advice_still_does(monkeypatch):
    _judge(monkeypatch, lambda n: json.dumps({"verdicts": [
        {"n": i + 1, "verdict": "supported", "why": "Synthetic"} for i in range(n)]}))
    assert approval.assess_candidate("Thank you for your question, Kofi.", _ctx())["outcome"] == "pass"
    assert approval.assess_candidate("Thank you. Intercrop maize with cowpea.", _ctx())["outcome"] == "review_required"


@pytest.mark.parametrize("text", ["Thanks, you can sell mouldy maize.", "Hello, eat the mouldy cobs, they are fine.",
                                  "Hi Kofi, plant two seeds per hill.", "Thanks, harvest when the leaves are green.",
                                  "Thanks, harvest.", "Thanks, Harvest.", "Hello, Sell.", "Hello, Mouldy."])
def test_greeting_cannot_carry_advice_past_the_source_check(text, monkeypatch):
    _judge(monkeypatch, lambda n: json.dumps({"verdicts": [
        {"n": i + 1, "verdict": "not_supported", "why": "Synthetic"} for i in range(n)]}))
    assert approval.assess_candidate(text, _ctx())["outcome"] != "pass"


def test_officer_screen_shows_the_hold_reason(monkeypatch):
    from agrireach import ui
    shown = []
    monkeypatch.setattr(ui.st, "caption", shown.append)
    monkeypatch.setattr(ui.st, "text", shown.append)
    ui.show_findings([{"rule_id": "SOURCE_FIGURES", "sentence": "", "reason": "'two' is not in the cited passage(s)"}])
    assert "Number not in the cited source" in shown and "Why: 'two' is not in the cited passage(s)" in shown


@pytest.mark.parametrize("text", ["Akwaaba, Kofi.", "Maakye Ama.", "Ɛte sɛn, Kwame.", "Ete sen.",
                                  "Akpe, Kofi.", "Oyiwaladonn, Ama.", "Hello Ama!", "Medaase, Kwame."])
def test_local_greetings_count_as_bare_greetings(text):
    assert approval.GREETING.match(text)


def test_local_greeting_cannot_carry_advice():
    assert not approval.GREETING.match("Akwaaba, plant two seeds per hill.")


def test_held_reasons_show_when_a_case_opens(monkeypatch):
    from agrireach import ui
    shown = []
    for name in ("caption", "text", "warning"):
        monkeypatch.setattr(ui.st, name, shown.append)
    monkeypatch.setattr(ui.st, "session_state", {})
    monkeypatch.setattr(ui, "request", lambda *a, **k: (200, {"outcome": "review_required", "findings": [
        {"rule_id": "SOURCE_FIGURES", "sentence": "Plant two seeds per hill.", "reason": "'two' is not in the cited passage(s)"}]}))
    ui.show_holds(1, "Plant two seeds per hill.", {})
    assert "Why: 'two' is not in the cited passage(s)" in shown and "Plant two seeds per hill." in shown


def test_number_hold_names_its_sentence_and_hides_source_ids(monkeypatch):
    from agrireach import ui
    shown = []
    monkeypatch.setattr(ui.st, "caption", shown.append)
    monkeypatch.setattr(ui.st, "text", shown.append)
    monkeypatch.setattr(ui, "source_name", lambda pid: "Maize guide, p. 11")
    ui.show_findings([{"rule_id": "SOURCE_FIGURES", "sentence": "",
                       "reason": "'two' is not in APNI-SARI-2023:p11-spacing"}], "Weed early. Plant two seeds per hill.")
    assert "Plant two seeds per hill." in shown and "Why: 'two' is not in Maize guide, p. 11" in shown


def test_bad_request_shows_the_api_reason():
    from agrireach.ui_feedback import feedback
    level, message = feedback(400, {"detail": "farmer_text required: approve the exact text the farmer will receive"})
    assert level == "error" and "farmer_text required" in message


def test_officer_sees_numbered_citations_not_source_ids():
    from agrireach import ui
    draft = "Plant two seeds per hill [APNI-SARI-2023:p11-spacing]. Weed early [MOFA-MAIZE:p12-weeds]."
    shown, cites = ui.number_citations(draft)
    assert shown == "Plant two seeds per hill [1]. Weed early [2]." and "APNI" not in shown
    assert ui.restore_citations(shown.replace("two", "2"), cites) == draft.replace("two", "2")


def test_send_refused_after_approval_is_a_delivery_problem_not_a_400(monkeypatch):
    from agrireach.channels import service
    from tests.test_not_delivered import _approve, _setup
    _, cid, h, c = _setup(monkeypatch)

    def refuse(*a, **k):
        raise ValueError("simulator sender ids must look like 'sim:farmer-1'")
    monkeypatch.setattr(service, "_deliver_transport", refuse)
    r = _approve(c, h, cid, "Harvest at 9 of 10 pods.")
    assert r.status_code == 200 and r.json()["delivery"]["ok"] is False
    assert r.json()["status"] != "released" or r.json()["delivery"]["outcome"] == "unknown"
