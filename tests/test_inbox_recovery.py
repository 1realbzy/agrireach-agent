"""Conservative recovery checks. No outbound provider or agent calls."""
from datetime import datetime, timedelta, timezone
from agrireach import db


def test_reconcile_stale_claim_preserves_evidence_without_replay(tmp_path):
    con = db.connect(str(tmp_path / "recovery.sqlite"))
    db.enqueue_inbound(con, "sms", "stale", {"text": "private"}, sender_id="+233000000001")
    claim, _ = db.claim_inbound(con, "sms", "stale")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert db.reconcile_interrupted_inbound(con, older_than=future) == 1
    row = con.execute("SELECT state,attempt_count,outcome_reason,payload FROM channel_inbox WHERE message_id='stale'").fetchone()
    assert row["state"] == "uncertain"
    assert row["attempt_count"] == 1
    assert "reconciliation required" in row["outcome_reason"]
    assert "private" in row["payload"]
    assert db.claim_inbound(con, "sms", "stale") is None
    assert not db.finish_inbound(con, "sms", "stale", claim, "completed", case_id=123)
    assert db.reconcile_interrupted_inbound(con, older_than=future) == 0


def test_recent_claim_not_reconciled(tmp_path):
    con = db.connect(str(tmp_path / "recovery.sqlite"))
    db.enqueue_inbound(con, "whatsapp", "recent", {"text": "maize"})
    db.claim_inbound(con, "whatsapp", "recent")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert db.reconcile_interrupted_inbound(con, older_than=past) == 0
    assert con.execute("SELECT state FROM channel_inbox WHERE message_id='recent'").fetchone()[0] == "processing"
