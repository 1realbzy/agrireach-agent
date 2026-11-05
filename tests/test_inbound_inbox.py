"""Phase 2 checkpoint 1: durable inbound storage and single-winner claims.

The webhook and channel processors are NOT yet wired to this table. These tests
verify persistence, uniqueness and conservative crash semantics only.
"""
import sqlite3

from agrireach import db


def test_inbox_persists_and_deduplicates(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    con = db.connect(path)
    payload = {"from": "+233000000000", "text": "maize"}
    assert db.enqueue_inbound(con, "sms", "m1", payload)
    assert not db.enqueue_inbound(con, "sms", "m1", {"text": "overwritten"})
    con.close()
    reopened = db.connect(path)
    row = reopened.execute("SELECT state,attempt_count,payload FROM channel_inbox").fetchone()
    assert row["state"] == "pending" and row["attempt_count"] == 0
    assert '"maize"' in row["payload"] and "overwritten" not in row["payload"]
    assert [r[0] for r in reopened.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1,2,3,4]


def test_only_one_worker_can_claim_and_finish(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    a, b = db.connect(path), db.connect(path)
    assert db.enqueue_inbound(a, "whatsapp", "m2", {"text": "soybean"})
    assert db.claim_inbound(a, "whatsapp", "m2", "lease-a") == {"text": "soybean"}
    assert db.claim_inbound(b, "whatsapp", "m2", "lease-b") is None
    assert not db.finish_inbound(b, "whatsapp", "m2", "lease-b", "completed")
    assert db.finish_inbound(a, "whatsapp", "m2", "lease-a", "completed")
    assert not db.finish_inbound(a, "whatsapp", "m2", "lease-a", "completed")
    assert db.claim_inbound(b, "whatsapp", "m2", "lease-c") is None


def test_interrupted_processing_is_not_automatically_retried(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    con = db.connect(path)
    db.enqueue_inbound(con, "sms", "m3", {"text": "maize"})
    assert db.claim_inbound(con, "sms", "m3", "crashed-worker")
    con.close()
    recovered = db.connect(path)
    assert db.claim_inbound(recovered, "sms", "m3", "new-worker") is None
    row = recovered.execute("SELECT state,attempt_count FROM channel_inbox WHERE message_id='m3'").fetchone()
    assert (row["state"], row["attempt_count"]) == ("processing", 1)
    # A recovery worker must first reconcile possible case creation and sends.


def test_reject_invalid_outcome_and_empty_ids(tmp_path):
    con = db.connect(str(tmp_path / "inbox.sqlite"))
    import pytest
    with pytest.raises(ValueError):
        db.enqueue_inbound(con, "sms", "", {})
    db.enqueue_inbound(con, "sms", "m4", {"text": "maize"})
    with pytest.raises(ValueError):
        db.finish_inbound(con, "sms", "m4", "lease", "pending")
