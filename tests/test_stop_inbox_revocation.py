"""STOP invalidates all inbox claims for the sender, including in-flight claims.

This verifies database revocation and privacy. It does not prove that an external
provider send already underway can be cancelled.
"""
from agrireach import db


def test_stop_revokes_active_claim_and_pending_payloads(tmp_path):
    path = str(tmp_path / "stop.sqlite")
    a, b = db.connect(path), db.connect(path)
    sender = "+233000000001"
    assert db.enqueue_inbound(a, "sms", "active", {"text": "private active"}, sender_id=sender)
    assert db.enqueue_inbound(a, "sms", "pending", {"text": "private pending"}, sender_id=sender)
    claim, _ = db.claim_inbound(a, "sms", "active")
    db.forget_sender(b, "sms", sender)
    assert b.execute(
        "SELECT count(*) FROM channel_inbox WHERE channel='sms' AND sender_id=?",
        (sender,),
    ).fetchone()[0] == 0
    assert not db.finish_inbound(a, "sms", "active", claim, "completed", case_id=1)
    assert db.claim_inbound(a, "sms", "pending") is None
    a.close()
    b.close()


def test_stop_is_scoped_to_channel_and_sender(tmp_path):
    path = str(tmp_path / "stop.sqlite")
    con = db.connect(path)
    sender = "+233000000001"
    db.enqueue_inbound(con, "sms", "s1", {"text": "private"}, sender_id=sender)
    db.enqueue_inbound(con, "whatsapp", "w1", {"text": "keep"}, sender_id=sender)
    db.enqueue_inbound(con, "sms", "s2", {"text": "keep"}, sender_id="+233000000002")
    db.forget_sender(con, "sms", sender)
    remaining = {(r["channel"], r["message_id"]) for r in
                 con.execute("SELECT channel,message_id FROM channel_inbox")}
    assert remaining == {("whatsapp", "w1"), ("sms", "s2")}
    con.close()
