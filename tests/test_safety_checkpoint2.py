"""Transactions use real SQLite files and separate connections; no remote sends."""
import json
import sqlite3
import threading

import pytest

from agrireach import approval, db, delivery, judge, knowledge
from agrireach.channels import service
from agrireach.channels.base import SendResult

REFERRAL = "Consult your local agricultural extension officer before choosing or applying a pesticide."


def ready():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="FAW maize", draft="Officer draft",
                              sources=["APNI-SARI-2023-MAIZE:p20-faw-control"])
    db.save_contact(con, cid, channel="simulator", sender_id="sim:test")
    db.officer_decide(con, cid, officer="Ama", decision="approve", farmer_text=REFERRAL, expected_revision=1)
    return con, cid


def test_immutable_approval_and_atomic_decision(monkeypatch):
    con, cid = ready()
    row = con.execute("SELECT * FROM approvals").fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        con.execute("UPDATE approvals SET payload='x' WHERE id=?", (row["id"],))
    con.rollback()
    assert con.execute("SELECT count(*) FROM audit_events WHERE event_name='approval_recorded'").fetchone()[0] == 1
    assert db.get_case(con, cid)["status"] == "approved"


def test_release_binds_sources_and_exact_text(monkeypatch):
    con, cid = ready()
    db.release_to_farmer(con, cid)
    _record, payload = approval.validated_approval(con, cid)
    assert payload["farmer_text"] == REFERRAL
    real = knowledge.reference
    monkeypatch.setattr(knowledge, "reference", lambda i: real(i) | {"text": "Changed safety guidance"})
    with pytest.raises(db.GateError, match="fingerprint"):
        db.release_to_farmer(con, cid)


def test_concurrent_dispatch_has_one_send():
    con, cid = ready()
    db.release_to_farmer(con, cid)
    entered = threading.Event()
    finish = threading.Event()
    calls = []
    errors = []
    class Channel:
        def send(self, recipient, message):
            calls.append(message.text)
            entered.set()
            assert finish.wait(5)
            return SendResult(True)
    def first():
        try:
            service.deliver(db.connect(), cid, {"simulator": Channel()})
        except Exception as e:
            errors.append(e)
    thread = threading.Thread(target=first)
    thread.start()
    assert entered.wait(5)
    result = service.deliver(con, cid, {"simulator": Channel()})
    assert result["outcome"] == "unchanged"
    finish.set()
    thread.join(5)
    assert not thread.is_alive() and not errors
    assert calls == [REFERRAL]
    service.deliver(con, cid, {"simulator": Channel()})
    assert calls == [REFERRAL]


def test_interrupted_claim_cannot_retry():
    con, cid = ready()
    db.release_to_farmer(con, cid)
    job_id, claim_id = delivery.claim(con, cid)
    delivery.interrupted(con, job_id, officer="Ama")
    assert delivery.claim(con, cid) is None
    with pytest.raises(db.GateError):
        delivery.complete(con, cid, job_id, claim_id, "accepted")
    delivery.reconcile(con, job_id, officer="Ama", accepted=False, provider_evidence="Verified gateway nonacceptance record: test-123")
    assert delivery.claim(con, cid) is not None


def test_approval_audit_failure_rolls_back(monkeypatch):
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="x", draft="x")
    def failure(*a, **kw):
        raise RuntimeError("injected storage failure")
    monkeypatch.setattr(approval, "audit", failure)
    with pytest.raises(RuntimeError):
        db.officer_decide(con, cid, officer="Ama", decision="approve", farmer_text="Do not use unapproved pesticides.", expected_revision=1)
    assert db.get_case(con, cid)["status"] == "pending_review"
    assert con.execute("SELECT count(*) FROM approvals").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM advisory_submissions").fetchone()[0] == 0


def test_judge_failure_is_not_acknowledgeable(monkeypatch):
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="maize", draft="x", sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    monkeypatch.setattr(judge, "_call", lambda u: "malformed")
    with pytest.raises(db.SafetyError) as exc:
        db.officer_decide(con, cid, officer="Ama", decision="approve", farmer_text="Inspect maize leaves carefully.", expected_revision=1)
    assert exc.value.assessment["outcome"] == "assessment_unavailable"


def test_acknowledgement_bound_and_single_use(monkeypatch):
    con = db.connect()
    db.add_officer(con, "Ama")
    cid = db.agent_upsert_case(con, status="pending_review", question="maize", draft="x", sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    monkeypatch.setattr(judge, "_call", lambda u: json.dumps({"verdicts": [{"n": i+1, "verdict": "not_supported", "why": "test concern"} for i in range(u.count('. SENTENCE: '))]}))
    args = dict(officer="Ama", decision="approve", farmer_text="Inspect maize leaves carefully.", expected_revision=1)
    with pytest.raises(db.SafetyError) as exc:
        db.officer_decide(con, cid, **args)
    assert exc.value.assessment["outcome"] == "acknowledgement_required"
    token = exc.value.assessment["acknowledgement"]
    db.officer_decide(con, cid, acknowledgement=token, **args)
    assert con.execute("SELECT consumed_approval FROM acknowledgement_challenges").fetchone()[0]
    with pytest.raises(db.GateError):
        db.officer_decide(con, cid, acknowledgement=token, **args)


@pytest.mark.parametrize("change", ["text", "officer", "credential", "expiry"])
def test_changed_acknowledgement_binding_is_refused(monkeypatch, change):
    con = db.connect()
    db.add_officer(con, "Ama")
    db.add_officer(con, "Kofi")
    cid = db.agent_upsert_case(con, status="pending_review", question="maize", draft="x", sources=["APNI-SARI-2023-MAIZE:p18-scouting"])
    monkeypatch.setattr(judge, "_call", lambda u: json.dumps({"verdicts": [{"n": i+1, "verdict": "not_supported", "why": "test concern"} for i in range(u.count('. SENTENCE: '))]}))
    args = dict(officer="Ama", decision="approve", farmer_text="Inspect maize leaves carefully.", expected_revision=1)
    with pytest.raises(db.SafetyError) as exc:
        db.officer_decide(con, cid, **args)
    token = exc.value.assessment["acknowledgement"]
    if change == "text":
        args["farmer_text"] += " "
    elif change == "officer":
        args["officer"] = "Kofi"
    elif change == "credential":
        db.add_officer(con, "Ama")
    else:
        with con:
            con.execute("UPDATE acknowledgement_challenges SET expires_at='2000-01-01'")
    with pytest.raises(db.GateError):
        db.officer_decide(con, cid, acknowledgement=token, **args)
    assert not con.execute("SELECT 1 FROM approvals").fetchone()


def test_migration_ledger_and_foreign_keys():
    con = db.connect()
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2]
    assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert not con.execute("PRAGMA foreign_key_check").fetchall()
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_legacy_migration_preserves_rows_and_verified_backup(tmp_path):
    path = tmp_path / "legacy.sqlite"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE cases(id INTEGER PRIMARY KEY, question TEXT, crop TEXT, region TEXT, draft TEXT, farmer_draft TEXT, sources TEXT, status TEXT, officer TEXT, farmer_text TEXT, final_text TEXT, updated_at TEXT)")
    con.execute("INSERT INTO cases VALUES(1,'question','','','internal',NULL,'[]','released','Ama',NULL,'legacy text','2026-01-01')")
    con.commit()
    before = tuple(con.execute("SELECT * FROM cases").fetchone())
    from agrireach.migrations import ensure_schema
    ensure_schema(con, str(path))
    assert tuple(con.execute("SELECT * FROM cases").fetchone())[:-1] == before
    assert con.execute("SELECT provenance FROM approvals").fetchone()[0] == "legacy_unvalidated"
    with pytest.raises(db.GateError, match="Fresh"):
        approval.validated_approval(con, 1)
    backups = list(tmp_path.glob("*.before-safety-*.sqlite"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert tuple(backup.execute("SELECT * FROM cases").fetchone()) == before
        assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    ensure_schema(con, str(path))
    assert len(list(tmp_path.glob("*.before-safety-*.sqlite"))) == 1


def test_migration_failure_rolls_back_version_two(monkeypatch, tmp_path):
    from agrireach import migrations
    con = sqlite3.connect(tmp_path / "broken.sqlite")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE cases(id INTEGER PRIMARY KEY, draft TEXT, farmer_draft TEXT, sources TEXT, question TEXT, crop TEXT, region TEXT, status TEXT, officer TEXT, updated_at TEXT)")
    con.commit()
    monkeypatch.setattr(migrations, "STATEMENTS_V2", migrations.STATEMENTS_V2 + ["INVALID SQL"])
    with pytest.raises(sqlite3.OperationalError):
        migrations.ensure_schema(con, str(tmp_path / "broken.sqlite"))
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations")] == [1]
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='approvals'").fetchone()
    assert con.execute("SELECT 1 FROM sqlite_master WHERE name='cases_content_revision'").fetchone()


def test_concurrent_approvals_have_one_winner():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="x", draft="x")
    barrier = threading.Barrier(2)
    outcomes = []
    def run():
        connection = db.connect()
        barrier.wait()
        try:
            db.officer_decide(connection, cid, officer="Ama", decision="approve",
                              farmer_text="Do not use unapproved pesticides.", expected_revision=1)
            outcomes.append("approved")
        except db.GateError:
            outcomes.append("stale")
        finally:
            connection.close()
    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(outcomes) == ["approved", "stale"]
    assert con.execute("SELECT count(*) FROM approvals").fetchone()[0] == 1
