from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import sqlite3

import pytest

from agrireach import db, migrations


PILOT_RECORDED = "7b197e86411612805f89cc83e24011853cb7c046d21193ab10dfe7489274c5c2"
AUDIT_EXPECTED = "5283534006cb19119acefc776300c7e83691758ff67507f173b5fc2c801996f7"
SMS_TABLES = ("farmer_sms_contacts", "acknowledgement_jobs", "acknowledgement_attempts")


@pytest.mark.parametrize("failure", ["open", "verification"])
def test_bootstrap_does_not_change_legacy_schema_when_backup_fails(tmp_path, monkeypatch, failure):
    path = tmp_path / "legacy.sqlite"
    with closing(sqlite3.connect(path)) as con, con:
        con.execute("CREATE TABLE cases(id INTEGER PRIMARY KEY, question TEXT, crop TEXT, region TEXT, "
                    "draft TEXT, sources TEXT, status TEXT, officer TEXT, updated_at TEXT)")
        con.execute("INSERT INTO cases(id, question) VALUES (1, 'legacy')")
    before = path.read_bytes()
    connect = sqlite3.connect

    class InvalidBackup(sqlite3.Connection):
        def execute(self, sql, *args):
            if sql == "PRAGMA integrity_check":
                return super().execute("SELECT 'injected integrity failure'")
            return super().execute(sql, *args)

    def fail_backup(destination, *args, **kwargs):
        if ".before-" in str(destination):
            if failure == "open":
                raise sqlite3.OperationalError("injected backup failure")
            kwargs["factory"] = InvalidBackup
        return connect(destination, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fail_backup)
    expected = sqlite3.OperationalError if failure == "open" else RuntimeError
    with pytest.raises(expected, match="backup failure|Backup verification failed"):
        db.connect(str(path))
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_historical_upgrade_stops_before_ddl_if_backup_fails(tmp_path, monkeypatch, version):
    path = tmp_path / "historical.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(migrations, f"upgrade_v{version + 1}", lambda con: None)
        for later in range(version + 2, 7):
            patch.setattr(migrations, f"upgrade_v{later}", lambda *args: None)
        with closing(db.connect(str(path))) as con:
            db.agent_upsert_case(con, status="pending_review", question="legacy")
            assert con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == version
    before = path.read_bytes()
    connect = sqlite3.connect

    def fail_backup(destination, *args, **kwargs):
        if f".before-v{version + 1}-" in str(destination):
            raise sqlite3.OperationalError("injected backup failure")
        return connect(destination, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", fail_backup)
    with pytest.raises(sqlite3.OperationalError, match="injected backup failure"):
        db.connect(str(path))
    assert path.read_bytes() == before


def test_bootstrap_failure_rolls_back_and_retains_original_backup(tmp_path, monkeypatch):
    path = tmp_path / "current.sqlite"
    with closing(db.connect(str(path))) as con, con:
        con.execute("DROP TABLE channel_pending")
        con.execute("DROP TABLE channel_consent")
    before = path.read_bytes()
    monkeypatch.setitem(migrations.BOOTSTRAP_STATEMENTS, "channel_pending", "INVALID SQL")
    with pytest.raises(sqlite3.OperationalError, match="syntax error"):
        db.connect(str(path))
    assert path.read_bytes() == before
    (backup,) = tmp_path.glob("*.before-bootstrap-*.sqlite")
    with closing(sqlite3.connect(backup)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='channel_consent'").fetchone()


@pytest.fixture
def v5(tmp_path, monkeypatch):
    path = tmp_path / "synthetic # v5.sqlite"
    with monkeypatch.context() as patch:
        patch.setattr(migrations, "upgrade_v6", lambda con, path: None)
        with closing(db.connect(str(path))) as con:
            db.agent_upsert_case(con, status="pending_review", question="legacy maize question")
            assert [tuple(r) for r in con.execute(
                "SELECT version, checksum FROM schema_migrations ORDER BY version")] == migrations._valid_ledgers()[-2]
    return path


def test_v5_upgrade_and_verified_backup(v5):
    with closing(db.connect(str(v5))) as con:
        assert con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 6
        assert con.execute("SELECT question FROM cases").fetchone()[0] == "legacy maize question"
        assert con.execute("SELECT count(*) FROM farmer_sms_contacts").fetchone()[0] == 0
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    (backup,) = v5.parent.glob("*.before-v6-*.sqlite")
    with closing(sqlite3.connect(backup)) as con:
        assert con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 5
        assert con.execute("SELECT question FROM cases").fetchone()[0] == "legacy maize question"
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (SMS_TABLES[0],)).fetchone()
    saved = v5.read_bytes()
    with closing(db.connect(str(v5))):
        pass
    assert v5.read_bytes() == saved
    assert list(v5.parent.glob("*.before-v6-*.sqlite")) == [backup]


def test_upgrade_preserves_approval_assessment_and_audit_evidence(v5):
    with closing(sqlite3.connect(v5)) as con, con:
        con.execute("INSERT INTO safety_assessments VALUES (1, 1, 'snapshot', 'assessment', 'fixture')")
        con.execute("INSERT INTO approvals VALUES (1, 1, 1, NULL, 1, 'payload', 'fingerprint', 'fixture', 'fixture')")
        con.execute("INSERT INTO audit_events VALUES (1, 1, 'approval', 'officer', 'details', 'fixture')")
    tables = ("cases", "approvals", "safety_assessments", "audit_events")
    with closing(sqlite3.connect(v5)) as con:
        before = {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
    with closing(db.connect(str(v5))) as con:
        assert {table: [tuple(row) for row in con.execute(f"SELECT * FROM {table}")]
                for table in tables} == before
        for table in tables[1:]:
            with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                con.execute(f"UPDATE {table} SET id=id WHERE id=1")
            with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                con.execute(f"DELETE FROM {table} WHERE id=1")
    (backup,) = v5.parent.glob("*.before-v6-*.sqlite")
    with closing(sqlite3.connect(backup)) as con:
        assert {table: con.execute(f"SELECT * FROM {table}").fetchall() for table in tables} == before


def test_adopts_compatible_legacy_sms_data(v5):
    with closing(sqlite3.connect(v5)) as con, con:
        for statement in migrations.STATEMENTS_V6:
            con.execute(statement.replace("CREATE TABLE", "create table if not exists").replace(" (", "  ("))
        con.execute("INSERT INTO farmer_sms_contacts VALUES (1, '+233240000001', 'granted', 'fixture')")
        con.execute("INSERT INTO acknowledgement_jobs VALUES (1, 1, 'accepted', 'claim', 'simulated', 'fixture')")
        con.execute("INSERT INTO acknowledgement_attempts VALUES (1, 1, 'claim', 'accepted', 'fixture', NULL, NULL)")
    with closing(db.connect(str(v5))) as con:
        for name in SMS_TABLES:
            assert con.execute(f"SELECT count(*) FROM {name}").fetchone()[0] == 1
        assert con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] == 6


@pytest.mark.parametrize("defect", ["partial", "wrong_constraint", "trigger"])
def test_rejects_incompatible_schema_before_writes(v5, defect):
    with closing(sqlite3.connect(v5)) as con, con:
        for statement in migrations.STATEMENTS_V6[:1 if defect == "partial" else 3]:
            if defect == "wrong_constraint":
                statement = statement.replace("'granted'", "'anything'")
            con.execute(statement)
        if defect == "trigger":
            con.execute("CREATE TRIGGER surprise AFTER INSERT ON farmer_sms_contacts BEGIN SELECT 1; END")
    before = v5.read_bytes()
    with pytest.raises(RuntimeError, match="Incompatible or incomplete"):
        db.connect(str(v5))
    assert v5.read_bytes() == before
    assert not list(v5.parent.glob("*.before-v6-*.sqlite"))


def test_reported_checksum_mismatch_is_rejected_before_any_writes(v5, monkeypatch):
    # Reproduce the audit's comparison. The actual reviewed implementation
    # expects the recorded pilot checksum, so only this test changes the expectation.
    assert migrations.CHECKSUM_V2 == PILOT_RECORDED
    assert hashlib.sha256("\n".join(migrations.STATEMENTS_V2[:7]).encode()).hexdigest() == AUDIT_EXPECTED
    before = v5.read_bytes()
    monkeypatch.setattr(migrations, "CHECKSUM_V2", AUDIT_EXPECTED)
    with pytest.raises(RuntimeError, match="Unsupported migration ledger"):
        db.connect(str(v5))
    assert v5.read_bytes() == before
    assert not list(v5.parent.glob("*.before-v6-*.sqlite"))


def test_altered_ledger_is_rejected_by_unchanged_validator(v5):
    with closing(sqlite3.connect(v5)) as con, con:
        con.execute("UPDATE schema_migrations SET checksum=? WHERE version=2", (AUDIT_EXPECTED,))
    before = v5.read_bytes()
    with pytest.raises(RuntimeError, match="Unsupported migration ledger"):
        db.connect(str(v5))
    assert v5.read_bytes() == before
    assert not list(v5.parent.glob("*.before-v6-*.sqlite"))


def test_backup_failure_leaves_v5_unchanged(v5, monkeypatch):
    connect = sqlite3.connect

    def fail_backup(path, *args, **kwargs):
        if str(path).endswith(".sqlite.partial"):
            raise sqlite3.OperationalError("injected backup failure")
        return connect(path, *args, **kwargs)

    before = v5.read_bytes()
    monkeypatch.setattr(sqlite3, "connect", fail_backup)
    with pytest.raises(sqlite3.OperationalError, match="injected backup failure"):
        db.connect(str(v5))
    assert v5.read_bytes() == before
    assert not list(v5.parent.glob("*.before-v6-*.sqlite"))


@pytest.mark.parametrize("failure", ["ddl", "ledger"])
def test_failed_v6_rolls_back_ddl_and_ledger(v5, monkeypatch, failure):
    if failure == "ddl":
        first, second, third = migrations.STATEMENTS_V6
        monkeypatch.setattr(migrations, "STATEMENTS_V6", (first, second + " INVALID", third))
    else:
        with closing(sqlite3.connect(v5)) as con, con:
            con.execute("CREATE TRIGGER fail_v6 BEFORE INSERT ON schema_migrations "
                        "WHEN NEW.version=6 BEGIN SELECT RAISE(ABORT, 'injected'); END")
    before = v5.read_bytes()
    with pytest.raises(sqlite3.Error):
        db.connect(str(v5))
    assert v5.read_bytes() == before
    assert len(list(v5.parent.glob("*.before-v6-*.sqlite"))) == 1


def test_concurrent_upgraders_create_one_backup(v5):
    def migrate(_):
        with closing(db.connect(str(v5))) as con:
            return con.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(migrate, range(2))) == [6, 6]
    assert len(list(v5.parent.glob("*.before-v6-*.sqlite"))) == 1


def test_verify_only_is_read_only_and_checks_schema(v5, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["migrations", str(v5), "--verify-only"])
    before = v5.read_bytes()
    with pytest.raises(RuntimeError, match="Schema version or checksum mismatch"):
        migrations.main()
    assert v5.read_bytes() == before
    with closing(db.connect(str(v5))):
        pass
    before = v5.read_bytes()
    migrations.main()
    assert "versions 1 through 6 verified" in capsys.readouterr().out
    assert v5.read_bytes() == before
    with closing(sqlite3.connect(v5)) as con, con:
        con.execute("DROP TABLE acknowledgement_attempts")
    before = v5.read_bytes()
    with pytest.raises(RuntimeError, match="Incompatible or incomplete"):
        migrations.main()
    assert v5.read_bytes() == before
