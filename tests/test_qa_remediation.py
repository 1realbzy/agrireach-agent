"""Independent QA regressions: synthetic inputs, no providers or live models."""
import pytest

from agrireach import approval, knowledge, safety_gate


@pytest.mark.parametrize("text", [
    "Use Gramoxone on the weeds.", "Use mancozeb on the maize.",
    "Use Lambda Super on the crop.", "Drench the maize with Karate 5EC.",
    "Drench the maize with Karate.", "Treat the maize with Actellic.",
    "Dust the cobs with Actellic before bagging.", "Apply unfamiliarname to the leaves.",
    "Treat the field using newmaterial.", "Apply it every three days.",
    "Drench maize in Gramoxone.", "Use the new product on the crop.",
])
def test_c1_product_instructions_cannot_reach_judge(text, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A deterministic hold must not consult the probabilistic judge")
    from agrireach import claim_check
    monkeypatch.setattr(claim_check, "check_claims", forbidden)
    for sources in ([], [knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")]):
        candidate = "Consult your local AEA before choosing or applying a pesticide. " + text
        ctx = {"case": {"farmer_draft": None}, "sources": sources, "contact": None}
        result = approval.assess_candidate(candidate, ctx)
        assert result["outcome"] == "review_required", result
        assert any(f["rule_id"] == "S3" for f in result["findings"])


def test_unconfigured_channel_allows_recovery():
    from agrireach import db
    from agrireach.channels import service
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="maize", draft="draft")
    db.save_contact(con, cid, channel="whatsapp", sender_id="sim:qa")
    db.officer_decide(con, cid, officer="Ama", decision="approve", expected_revision=2,
                      farmer_text="Do not use unapproved pesticides.")
    db.release_to_farmer(con, cid)
    assert service.deliver(con, cid, {})["outcome"] == "definitely_failed"
    row = db.reopen_case(con, cid, officer="Ama", expected_revision=3, information="Channel setup needed")
    assert row["status"] == "pending_review"
    db.officer_decide(con, cid, officer="Ama", decision="reject", expected_revision=row["revision"])


@pytest.mark.parametrize("recipient,text", [("local-number", "Hello"), ("+233200000000", "x" * 1000)])
def test_sms_local_validation_proves_no_attempt(recipient, text):
    from agrireach.channels.sms import Config, SmsChannel
    from agrireach.channels.base import OutboundMessage
    class NoNetwork:
        def post(self, *args, **kwargs):
            pytest.fail("Provider must not be called")
    result = SmsChannel(Config("sandbox", "fake", "fake"), NoNetwork()).send(recipient, OutboundMessage(text))
    assert result.outcome == "definitely_failed"


def test_authenticated_reconciliation_single_use():
    from fastapi.testclient import TestClient
    from agrireach.api import app
    from agrireach import db, delivery
    from test_safety_checkpoint2 import ready
    con, cid = ready()
    db.release_to_farmer(con, cid)
    job, claim = delivery.claim(con, cid)
    delivery.complete(con, cid, job, claim, "unknown")
    token = db.add_officer(con, "Ama")
    client = TestClient(app)
    url = f"/officer/delivery-jobs/{job}/reconcile"
    body = {"accepted": False, "provider_evidence": "Verified sandbox nonacceptance record QA-1"}
    assert client.post(url, json=body).status_code == 401
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(url, headers=headers, json=body).status_code == 200
    assert client.post(url, headers=headers, json=body).status_code == 409
    assert con.execute("SELECT count(*) FROM audit_events WHERE event_name='delivery_reconciled' AND case_id=?", (cid,)).fetchone()[0] == 1


def test_s1_relevance_uses_question_and_keeps_ambiguity():
    faw = knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")
    storage = knowledge.reference("APNI-SARI-2023-MAIZE:p22-sacks")
    referral = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area."
    assert safety_gate.assess(referral, [faw, storage], question="Armyworm in maize").outcome == "pass"
    for question in ("Storage of maize", "Armyworm and storage", "Unclassified problem"):
        assert safety_gate.assess(referral, [faw, storage], question=question).outcome == "safety_blocked"
    assert safety_gate.assess("I do not know.", [faw], question="Armyworm").outcome == "safety_blocked"
    assert safety_gate.assess(referral, [storage | {"id": "unknown"}], question="Armyworm").outcome == "review_required"


@pytest.mark.parametrize("text", ["You do not need to consult your local AEA.",
    "Skip the AEA and treat the field yourself.", "You don't need to ask your extension officer."])
def test_consultation_bypass_is_deterministic(text):
    result = safety_gate.assess(text, [])
    assert result.outcome == "safety_blocked"
    assert any(f.rule_id == "S2" for f in result.findings)


@pytest.mark.parametrize("text", ["Talk to your local extension agent about which pesticide to use.",
    "Ask your local AEA which fall armyworm pesticide to use (APNI).",
    "I do not know which pesticide to recommend."])
def test_registered_referrals_are_not_s3_uncertainty(text):
    assert safety_gate.assess(text, []).outcome == "pass"


def test_supported_templates_and_source_text_need_no_judge(monkeypatch):
    from agrireach import db, judge
    def unavailable(*args, **kwargs):
        pytest.fail("Verified source sentences/templates must not require a judge")
    monkeypatch.setattr(judge, "_call", unavailable)
    con = db.connect()
    source = knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")
    cid = db.agent_upsert_case(con, status="pending_review", question="Armyworm maize", draft="draft", sources=[source["id"]])
    text = source["text"] + " Consult your local AEA before choosing or applying a pesticide."
    result = db.officer_decide(con, cid, officer="Ama", decision="approve", expected_revision=1, farmer_text=text)
    assert result["status"] == "approved"


def test_language_checks_assess_reply_not_proposal():
    assert safety_gate.assess("Harvest the maize at Kɔforidua when it is ready.", [], language="twi").outcome == "pass"
    assert safety_gate.assess("Keep grain at 30°C.", []).outcome == "pass"
    assert safety_gate.assess("Bere bɛn na metumi dua aburo?", []).outcome == "review_required"


def test_model_independent_voice_note_approval():
    import asyncio
    from agrireach import db
    from agrireach.channels import simulator
    from test_channels import FakeTranscriber, CLIP
    out = asyncio.run(simulator.ask("sim:qa-voice", audio=CLIP,
        transcriber=FakeTranscriber("When should I harvest my soybean? I farm near Tamale.")))
    con = db.connect()
    row = db.get_case(con, out["case_id"])
    token = db.add_officer(con, "QA Officer")
    # The officer chooses complete source text, independently of model drafting.
    text = "Harvest when 9 out of 10 pods are mature."
    result = simulator.officer_approve(row["id"], "QA Officer", text,
        token=token, expected_revision=row["revision"])
    assert result["ok"]
    assert simulator.SimulatorChannel().messages("sim:qa-voice")[-1]["text"] == text


def test_product_hold_survives_api_db_release_delivery(monkeypatch):
    from agrireach import db
    from agrireach.api import app
    from agrireach.channels import service
    from fastapi.testclient import TestClient
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="Weeds in maize", draft="draft",
                               sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    db.save_contact(con, cid, channel="simulator", sender_id="sim:c1")
    token = db.add_officer(con, "QA")
    body = {"decision": "approve", "farmer_text": "Use Gramoxone on the weeds.",
            "expected_revision": 2, "confirmed": True}
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.post(f"/officer/cases/{cid}/decision", headers=headers, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["outcome"] == "review_required"
    body["acknowledgement"] = "forged"
    assert client.post(f"/officer/cases/{cid}/decision", headers=headers, json=body).status_code == 409
    with pytest.raises(db.GateError):
        db.release_to_farmer(con, cid)
    assert service.deliver(con, cid, {})["outcome"] == "blocked"
    assert not con.execute("SELECT 1 FROM approvals").fetchone()


def test_protective_skip_negation_is_not_a_reversal():
    for text in ("Do not skip the AEA.", "Never skip your local extension officer."):
        assert not any(f.rule_id == "S2" for f in safety_gate.assess(text, []).findings)


def test_acknowledgement_binding_ignores_explanation_wording(monkeypatch):
    import json
    from agrireach import db, judge
    con = db.connect()
    db.add_officer(con, "QA")
    cid = db.agent_upsert_case(con, status="pending_review", question="maize", draft="draft",
                               sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    explanations = iter(["First explanation", "Same concern, different prose"])
    monkeypatch.setattr(judge, "_call", lambda u: json.dumps({"verdicts": [
        {"n": 1, "verdict": "not_supported", "why": next(explanations)}]}))
    args = dict(officer="QA", decision="approve", expected_revision=1, farmer_text="Inspect maize leaves carefully.")
    with pytest.raises(db.SafetyError) as exc:
        db.officer_decide(con, cid, **args)
    db.officer_decide(con, cid, acknowledgement=exc.value.assessment["acknowledgement"], **args)
    assert db.get_case(con, cid)["status"] == "approved"


def test_concurrent_reconciliation_has_one_winner():
    import threading
    from agrireach import db, delivery
    from test_safety_checkpoint2 import ready
    con, cid = ready()
    db.release_to_farmer(con, cid)
    job, claim = delivery.claim(con, cid)
    delivery.complete(con, cid, job, claim, "unknown")
    barrier = threading.Barrier(2)
    outcomes = []
    def reconcile():
        connection = db.connect()
        barrier.wait(timeout=5)
        try:
            delivery.reconcile(connection, job, officer="Ama", accepted=False,
                               provider_evidence="Verified nonacceptance QA-concurrency")
            outcomes.append("resolved")
        except db.GateError:
            outcomes.append("conflict")
        finally:
            connection.close()
    threads = [threading.Thread(target=reconcile) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["conflict", "resolved"]
    assert con.execute("SELECT count(*) FROM audit_events WHERE event_name='delivery_reconciled'").fetchone()[0] == 1


def test_unknown_rejection_keeps_external_disposition():
    from agrireach import db, delivery
    from test_safety_checkpoint2 import ready
    con, cid = ready()
    db.release_to_farmer(con, cid)
    job, claim = delivery.claim(con, cid)
    delivery.complete(con, cid, job, claim, "unknown")
    db.mark_not_delivered(con, cid, "Unknown provider result", actor="QA")
    db.officer_decide(con, cid, officer="Ama", decision="reject",
                      expected_revision=db.get_case(con, cid)["revision"])
    assert con.execute("SELECT state FROM delivery_jobs WHERE id=?", (job,)).fetchone()[0] == "unknown"
    with pytest.raises(db.GateError):
        delivery.claim(con, cid)


@pytest.mark.parametrize("body", [{"SMSMessageData": {"Recipients": []}},
    {"SMSMessageData": {"Recipients": [{"statusCode": 101}]}}])
def test_incomplete_sms_response_remains_unknown(body):
    import httpx
    from agrireach.channels.sms import Config, SmsChannel
    from agrireach.channels.base import OutboundMessage
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=body)))
    result = SmsChannel(Config("sandbox", "fake", "fake"), client).send("+233200000000", OutboundMessage("hello"))
    assert result.outcome == "unknown"
