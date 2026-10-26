"""Independent QA regressions: synthetic inputs, no providers or live models."""
import pytest

from agrireach import approval, knowledge, safety_gate


@pytest.mark.parametrize("text", [
    "Use Gramoxone on the weeds.", "Use mancozeb on the maize.",
    "Use Lambda Super on the crop.", "Drench the maize with Karate 5EC.",
    "Drench the maize with Karate.", "Treat the maize with Actellic.",
    "Dust the cobs with Actellic before bagging.", "Apply unfamiliarname to the leaves.",
    "Treat the field using newmaterial.", "Apply it every three days.",
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
