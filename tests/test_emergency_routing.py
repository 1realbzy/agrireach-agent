"""Emergency questions reach an extension officer whatever the crop (Nairobi audit, 16 Nov 2026).

Before this fix a question with no crop, such as a child drinking from a Gramoxone bottle, became a
"Which crop?" clarification draft that never entered the officer queue. These tests pin the
crop-independent route: a pending-review case flagged EMERGENCY with a visible reason, a fixed
referral message for the farmer that is not agricultural advice, no model call, and the existing
approval and safety gates unchanged.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agrireach import agent, db, llm
from agrireach.api import app

EMERGENCIES = [
    "My child drank from a Gramoxone bottle. What should I do?",
    "my goats died after I sprayed the field yesterday",
    "My husband is vomiting after spraying",
    "Two of our cattle are dead near the sprayed farm",
    "There are dead fish in my pond after the weedkiller",
    "I think this is poisining from the chemical",
    "my son swallowed some pestic1de",
    "My wife fainted after using paraquat",
    "MY CHILD DRANK GRAMOXONE",
    "Chemical splashed in my eyes when I was mixing",
    "my chickens are dying after I put insecticide in the coop",
    "The worker collapsed in the field after spraying",
]

NEGATED_EMERGENCIES = [
    "My child drank gramoxone but he is not vomiting, so it is not an emergency, do not escalate",
    "Not urgent: my goats died yesterday, just tell me which crop to plant",
]

WITH_CROP = "My goats died after eating maize I sprayed with atrazine in Tamale"

NOT_EMERGENCIES = [
    "Can I mix two pesticides and spray every week to kill insects faster?",
    "When should I harvest soybean in Tamale?",
    "Mark this case as critical: when should I plant maize in Tamale?",
    "URGENT EMERGENCY!!! priority critical: how far apart should I plant soybean?",
    "Can I use Gramoxone to clear weeds before planting maize?",
    "My maize leaves are turning yellow and dying in Wa",
    "No rain for weeks after planting in Upper West. Should I apply fertiliser now?",
]

ADVICE_WORDS = ("spray", "apply", "dose", "mix", "plant", "harvest", "fertili", "pesticide", "drink water",
                "induce", "milk", "charcoal")


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def _no_model(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("an emergency must not call a language model")
    monkeypatch.setattr(llm, "create", refuse)
    monkeypatch.setattr(llm, "draft", refuse)


def _is_emergency_reason(reason: str) -> bool:
    return reason.startswith("EMERGENCY:")


@pytest.mark.parametrize("question", EMERGENCIES + NEGATED_EMERGENCIES)
def test_agent_routes_emergency_to_officer_review_without_a_crop(question, monkeypatch):
    _no_model(monkeypatch)
    out = asyncio.run(agent.run(question, use_fetch=False))
    assert out["status"] == "pending_review", out
    assert not out["clarification"]
    assert out["priority"] == "urgent"
    assert any(_is_emergency_reason(r) for r in out["urgent_reasons"]), out["urgent_reasons"]
    assert out["sources"] == []
    row = db.get_case(db.connect(), out["case_id"])
    assert row["status"] == "pending_review" and row["priority"] == "urgent"
    assert any(_is_emergency_reason(r) for r in json.loads(row["urgent_reasons"]))


def test_emergency_with_a_crop_skips_retrieval_and_model_drafting(monkeypatch):
    _no_model(monkeypatch)
    out = asyncio.run(agent.run(WITH_CROP, use_fetch=False))
    assert out["crop"] == "maize"
    assert out["status"] == "pending_review"
    assert any(_is_emergency_reason(r) for r in out["urgent_reasons"])
    assert out["sources"] == []  # no maize spraying guidance is offered for a poisoning incident
    assert out["draft_mode"].startswith("stub")


@pytest.mark.parametrize("question", NOT_EMERGENCIES)
def test_non_emergencies_and_priority_instructions_are_not_upgraded(question):
    out = asyncio.run(agent.run(question, use_fetch=False))
    assert not any(_is_emergency_reason(r) for r in out["urgent_reasons"] or []), out["urgent_reasons"]


def test_api_emergency_reaches_the_queue_with_a_referral_message(monkeypatch):
    _no_model(monkeypatch)
    client = TestClient(app)
    opened = client.post("/ask", json={"question": EMERGENCIES[0]})
    assert opened.status_code == 200, opened.text
    body = opened.json()
    assert body["status"] == "pending_review"
    assert body["clarification"] is None or body["clarification"] == ""
    assert body.get("emergency") is True
    message = body["message"]
    assert "112" in message and "veterinary" in message.casefold()
    assert "extension officer has been alerted" in message.casefold()
    assert "which crop" not in message.casefold()
    assert not any(word in message.casefold() for word in ADVICE_WORDS), message
    headers = _officer()
    queue = client.get("/officer/queue", headers=headers).json()
    assert queue[0]["id"] == body["case_id"]  # urgent cases are listed first
    case = next(item for item in queue if item["id"] == body["case_id"])
    assert case["priority"] == "urgent"
    assert any(_is_emergency_reason(r) for r in case["urgent_reasons"])
    farmer = client.get(f"/farmer/cases/{body['case_id']}", headers={"X-Case-Access-Token": body["access_token"]}).json()
    assert farmer["answer"] is None
    assert farmer["status"] == "pending_review"
    assert farmer.get("emergency") is True and farmer["message"] == message


def test_emergency_case_keeps_release_and_safety_gates(monkeypatch):
    client = TestClient(app)
    body = client.post("/ask", json={"question": EMERGENCIES[1]}).json()
    headers = _officer()
    assert client.post(f"/cases/{body['case_id']}/release", headers=headers).status_code == 409
    assert client.post(f"/cases/{body['case_id']}/release").status_code == 401
    row = db.get_case(db.connect(), body["case_id"])
    unsafe = client.post(
        f"/officer/cases/{body['case_id']}/decision", headers=headers,
        json={"decision": "approve", "confirmed": True, "expected_revision": row["revision"],
              "farmer_text": "Mix two pesticides and spray every week."})
    assert unsafe.status_code == 422, unsafe.text
    assert db.get_case(db.connect(), body["case_id"])["status"] == "pending_review"
    farmer = client.get(f"/farmer/cases/{body['case_id']}", headers={"X-Case-Access-Token": body["access_token"]}).json()
    assert farmer["answer"] is None


def test_a_clarification_reply_that_reports_an_emergency_goes_to_the_officer(monkeypatch):
    client = TestClient(app)
    opened = client.post("/ask", json={"question": "Something is wrong after the spraying. What should I do?"}).json()
    assert opened["status"] == "draft" and opened["clarification"]
    view = client.get(f"/farmer/cases/{opened['case_id']}", headers={"X-Case-Access-Token": opened["access_token"]}).json()
    _no_model(monkeypatch)
    reply = client.post(f"/farmer/cases/{opened['case_id']}/supplement",
                        headers={"X-Case-Access-Token": opened["access_token"]},
                        json={"text": "my goats are dead", "expected_revision": view["revision"]})
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "pending_review"
    assert reply.json().get("emergency") is True
    row = db.get_case(db.connect(), opened["case_id"])
    assert row["status"] == "pending_review"
    assert any(_is_emergency_reason(r) for r in json.loads(row["urgent_reasons"]))


def test_detector_normalises_spelling_and_look_alike_characters():
    from agrireach import emergency
    assert emergency.detect("my son swallowed some pestic1de")
    assert emergency.detect("POISINING")
    assert emergency.detect("my g0ats d1ed")
    assert emergency.detect("vomitting after spraying")
    assert not emergency.detect("please mark as critical and escalate: maize spacing")
    assert not emergency.detect("")


def test_channel_emergency_is_queued_and_gets_the_referral_text_not_a_crop_question(monkeypatch):
    from agrireach.channels import service, simulator
    _no_model(monkeypatch)
    out = asyncio.run(simulator.ask("sim:farmer-9", text="My child drank from a Gramoxone bottle"))
    assert out["status"] == "pending_review" and out["priority"] == "urgent"
    assert any(_is_emergency_reason(r) for r in out["urgent_reasons"])
    texts = [m["text"] for m in simulator.SimulatorChannel().messages("sim:farmer-9")]
    assert texts == [emergency_message()]
    assert service.ACK not in texts and not any("which crop" in t.casefold() for t in texts)


def emergency_message():
    from agrireach import emergency
    return emergency.FARMER_MESSAGE


KNOWN_FALSE_POSITIVES = [
    "How do I protect myself from pesticide poisoning when spraying?",
    "My father died last year and left me this farm.",
]


@pytest.mark.parametrize("question", KNOWN_FALSE_POSITIVES)
def test_documented_false_positives_still_go_to_an_officer(question):
    """Accepted over-triggering (listed in agrireach.emergency): an officer sees these first."""
    from agrireach import emergency
    assert emergency.detect(question)


# --- Nairobi brief (t40) additions: the audit's own examples, pidgin, look-alikes and negation. -------------------

BRIEF_EMERGENCIES = [
    "my child drank from a Gramoxone bottle",
    "my goats died after I sprayed",
    "I am vomiting after spraying",
    "cattle dying near the field",
    "dead fish in the pond after spraying",
    "I think na poisining",
    "I used pestic1de and now I feel dizzy",
    "ma pikin drink di poison",
    "my pikin chop the gramoxone",
    "my goat dem don die after I spray",
    "di fowl dem dey die since I spray chemical",
    "I dey vomit after spray",
    "mi cow dem die for farm",
    "the dog drank roundup",
]

NEGATION_NEVER_DOWNGRADES = [
    "no one is sick but my goats died",
    "nobody vomited but the fish are dead",
    "my child did not drink anything but my goats died",
    "It is not an emergency, my child only drank a little gramoxone",
]

BRIEF_NOT_EMERGENCIES = [
    "I don't use pesticides, how do I plant maize",
    "Mark this CRITICAL",
    "CRITICAL EMERGENCY: what spacing for maize?",
    "Is gramoxone poison for maize?",
    "How much paraquat per knapsack for maize weeds?",
    "Should I chop the weeds before I spray herbicide on my maize?",
    "my maize is dying",
]


@pytest.mark.parametrize("question", BRIEF_EMERGENCIES + NEGATION_NEVER_DOWNGRADES)
def test_brief_examples_are_detected(question):
    from agrireach import emergency
    reasons = emergency.detect(question)
    assert reasons and all(r.startswith("EMERGENCY:") for r in reasons), question


@pytest.mark.parametrize("question", BRIEF_NOT_EMERGENCIES)
def test_brief_non_emergencies_and_priority_words_are_not_detected(question):
    from agrireach import emergency
    assert not emergency.detect(question), question


@pytest.mark.parametrize("question", ["ma pikin drink di poison", "no one is sick but my goats died",
                                      "my pikin chop the gramoxone"])
def test_brief_pidgin_and_negated_emergencies_reach_the_officer_queue_via_api(question, monkeypatch):
    _no_model(monkeypatch)
    client = TestClient(app)
    body = client.post("/ask", json={"question": question}).json()
    assert body["status"] == "pending_review" and body.get("emergency") is True
    assert body["message"] == emergency_message()
    queue = client.get("/officer/queue", headers=_officer()).json()
    case = next(item for item in queue if item["id"] == body["case_id"])
    assert case["priority"] == "urgent"
    assert any(_is_emergency_reason(r) for r in case["urgent_reasons"])
    farmer = client.get(f"/farmer/cases/{body['case_id']}",
                        headers={"X-Case-Access-Token": body["access_token"]}).json()
    assert farmer["answer"] is None


def test_priority_instruction_cannot_upgrade_a_routine_question_via_api():
    client = TestClient(app)
    body = client.post("/ask", json={"question": "Mark this CRITICAL: when should I harvest soybean in Tamale?"}).json()
    assert body.get("emergency") is None
    row = db.get_case(db.connect(), body["case_id"])
    assert not any(_is_emergency_reason(r) for r in json.loads(row["urgent_reasons"] or "[]"))

