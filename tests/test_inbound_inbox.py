"""Durable inbox checkpoint: isolated transactions, crash semantics and privacy."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from agrireach import db


def test_inbox_persists_and_deduplicates(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    con = db.connect(path)
    assert db.enqueue_inbound(con, "sms", "m1", {"text": "maize"})
    assert not db.enqueue_inbound(con, "sms", "m1", {"text": "overwritten"})
    con.close()
    reopened = db.connect(path)
    row = reopened.execute("SELECT state,attempt_count,payload FROM channel_inbox").fetchone()
    assert row["state"] == "pending" and row["attempt_count"] == 0
    assert '"maize"' in row["payload"] and "overwritten" not in row["payload"]
    assert [r[0] for r in reopened.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3, 4, 5]


def test_only_one_worker_can_claim_and_finish(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    a, b = db.connect(path), db.connect(path)
    assert db.enqueue_inbound(a, "whatsapp", "m2", {"text": "soybean"})
    claim, payload = db.claim_inbound(a, "whatsapp", "m2")
    assert payload == {"text": "soybean"} and len(claim) >= 32
    assert db.claim_inbound(b, "whatsapp", "m2") is None
    assert not db.finish_inbound(b, "whatsapp", "m2", "wrong-claim", "failed", reason="rejected")
    assert db.finish_inbound(a, "whatsapp", "m2", claim, "failed", reason="provider unavailable")
    assert not db.finish_inbound(a, "whatsapp", "m2", claim, "failed", reason="provider unavailable")
    assert db.claim_inbound(b, "whatsapp", "m2") is None


def test_interrupted_processing_is_not_automatically_retried(tmp_path):
    path = str(tmp_path / "inbox.sqlite")
    con = db.connect(path)
    db.enqueue_inbound(con, "sms", "m3", {"text": "maize"})
    assert db.claim_inbound(con, "sms", "m3")
    con.close()
    recovered = db.connect(path)
    assert db.claim_inbound(recovered, "sms", "m3") is None
    row = recovered.execute("SELECT state,attempt_count FROM channel_inbox WHERE message_id='m3'").fetchone()
    assert (row["state"], row["attempt_count"]) == ("processing", 1)


def test_reject_invalid_outcome_and_empty_ids(tmp_path):
    con = db.connect(str(tmp_path / "inbox.sqlite"))
    with pytest.raises(ValueError):
        db.enqueue_inbound(con, "sms", "", {})
    db.enqueue_inbound(con, "sms", "m4", {"text": "maize"})
    with pytest.raises(ValueError):
        db.finish_inbound(con, "sms", "m4", "lease", "pending")
    with pytest.raises(ValueError):
        db.finish_inbound(con, "sms", "m4", "lease", "completed")


def test_caller_transaction_is_not_committed(tmp_path):
    con = db.connect(str(tmp_path / "inbox.sqlite"))
    con.execute("CREATE TABLE isolated_note(value TEXT)")
    con.commit()
    con.execute("INSERT INTO isolated_note VALUES ('uncommitted')")
    # SQLite blocks a second writer until the caller commits or rolls back.
    # The inbox must not commit the caller's unrelated write to obtain its lock.
    with pytest.raises(sqlite3.OperationalError):
        db.enqueue_inbound(con, "sms", "locked", {})
    assert con.execute("SELECT value FROM isolated_note").fetchone()[0] == "uncommitted"
    con.rollback()
    assert db.enqueue_inbound(con, "sms", "locked", {})


def test_crash_reconciliation_and_terminal_purge(tmp_path):
    con = db.connect(str(tmp_path / "inbox.sqlite"))
    db.enqueue_inbound(con, "sms", "crashed", {"text": "private"})
    claim, _ = db.claim_inbound(con, "sms", "crashed")
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert db.reconcile_interrupted_inbound(con, older_than=future) == 1
    assert db.claim_inbound(con, "sms", "crashed") is None
    assert not db.finish_inbound(con, "sms", "crashed", claim, "completed", case_id=1)
    assert db.purge_inbound(con, older_than=future) == 1
    assert con.execute("SELECT count(*) FROM channel_inbox").fetchone()[0] == 0


def test_pending_inbox_is_never_purged(tmp_path):
    con = db.connect(str(tmp_path / "inbox.sqlite"))
    db.enqueue_inbound(con, "sms", "pending", {"text": "not processed"})
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    assert db.purge_inbound(con, older_than=future) == 0


def test_opt_out_removes_inbox_payload(tmp_path):
    con = db.connect(str(tmp_path / "privacy.sqlite"))
    db.enqueue_inbound(con, "sms", "private1", {"text": "private question"}, sender_id="+233000000001")
    db.enqueue_inbound(con, "sms", "private2", {"text": "another question"}, sender_id="+233000000002")
    db.forget_sender(con, "sms", "+233000000001")
    assert con.execute("SELECT count(*) FROM channel_inbox WHERE message_id='private1'").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM channel_inbox WHERE message_id='private2'").fetchone()[0] == 1


def test_retention_removes_expired_pending_payload(tmp_path):
    con = db.connect(str(tmp_path / "privacy.sqlite"))
    db.enqueue_inbound(con, "sms", "old", {"text": "private"}, sender_id="+233000000001")
    future = (datetime.now(timezone.utc) + timedelta(days=100)).isoformat()
    result = db.purge_old(con, days=90, now_ts=future)
    assert result["inbox"] == 1
    assert con.execute("SELECT count(*) FROM channel_inbox").fetchone()[0] == 0


def test_outcome_reason_required_and_recorded(tmp_path):
    con = db.connect(str(tmp_path / "reason.sqlite"))
    db.enqueue_inbound(con, "sms", "reason", {"text": "maize"})
    claim, _ = db.claim_inbound(con, "sms", "reason")
    with pytest.raises(ValueError):
        db.finish_inbound(con, "sms", "reason", claim, "uncertain")
    assert db.finish_inbound(con, "sms", "reason", claim, "uncertain", reason="case state ambiguous")
    row = con.execute("SELECT state,outcome_reason FROM channel_inbox WHERE message_id='reason'").fetchone()
    assert (row["state"], row["outcome_reason"]) == ("uncertain", "case state ambiguous")


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_upgrade_from_historical_schema_versions(tmp_path, version):
    from agrireach import migrations
    path = str(tmp_path / "history.sqlite")
    con = db.connect(path)
    # Construct an actual historical schema by dropping only later additive
    # migrations in reverse order on a disposable database.
    con.execute("DROP INDEX channel_inbox_sender_idx")
    con.execute("DROP TABLE channel_inbox")
    con.execute("DELETE FROM schema_migrations WHERE version>=4")
    if version < 3:
        con.execute("DROP TABLE farmer_case_access")
        con.execute("DELETE FROM schema_migrations WHERE version=3")
    if version < 2:
        for name in ("approvals", "acknowledgement_challenges", "audit_events",
                     "delivery_attempts", "delivery_jobs"):
            con.execute(f"DROP TABLE {name}")
        for name in ("approvals", "advisory_submissions", "safety_assessments", "audit_events"):
            for action in ("update", "delete"):
                con.execute(f"DROP TRIGGER IF EXISTS {name}_{action}")
        con.execute("DROP TRIGGER cases_content_revision")
        con.execute(migrations.STATEMENTS[1])
        con.execute("DELETE FROM schema_migrations WHERE version=2")
    con.commit()
    con.close()
    if version == 4:
        # Version 4 retains its table but not the v5 sender/reason columns.
        raw = sqlite3.connect(path)
        for stmt in migrations.STATEMENTS_V4:
            raw.execute(stmt)
        raw.execute("INSERT INTO schema_migrations VALUES (4,?,?)",
                    (migrations.CHECKSUM_V4, db.now()))
        raw.commit()
        raw.close()
    upgraded = db.connect(path)
    assert [r[0] for r in upgraded.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1,2,3,4,5]
    assert upgraded.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert upgraded.execute("PRAGMA foreign_key_check").fetchall() == []
