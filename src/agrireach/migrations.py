"""Versioned SQLite upgrades. Never discard evidence in a destructive downgrade."""
from __future__ import annotations

from contextlib import closing
import hashlib
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

VERSION = 1
STATEMENTS = [
    "ALTER TABLE cases ADD COLUMN revision INTEGER NOT NULL DEFAULT 1",
    "CREATE TRIGGER cases_content_revision AFTER UPDATE OF draft,farmer_draft,sources,question,crop,region,status ON cases WHEN NEW.revision=OLD.revision BEGIN UPDATE cases SET revision=revision+1 WHERE id=NEW.id; END",
    "CREATE TABLE advisory_submissions(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id), revision INTEGER NOT NULL, officer TEXT NOT NULL, farmer_text TEXT, officer_text TEXT, decision TEXT NOT NULL, note TEXT, created_at TEXT NOT NULL)",
    "CREATE TABLE safety_assessments(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id), snapshot TEXT NOT NULL, assessment TEXT NOT NULL, created_at TEXT NOT NULL)",
]
CHECKSUM = hashlib.sha256("\n".join(STATEMENTS).encode()).hexdigest()


def validate_existing_ledger(con):
    """Reject unknown or incomplete upgraded databases before bootstrap writes."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_migrations" not in tables:
        _sms_tables_exist(con)
        return
    ledger = [tuple(r) for r in con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")]
    if ledger not in _valid_ledgers():
        raise RuntimeError("Unsupported migration ledger; no bootstrap writes performed")
    _sms_tables_exist(con, required=len(ledger) >= 6)
    required = {"cases", "advisory_submissions", "safety_assessments"}
    if len(ledger) >= 2:
        required |= {"approvals", "acknowledgement_challenges", "audit_events", "delivery_jobs", "delivery_attempts"}
    if len(ledger) >= 3:
        required.add("farmer_case_access")
    if len(ledger) >= 4:
        required.add("channel_inbox")
    if len(ledger) >= 5:
        cols = {r[1] for r in con.execute("PRAGMA table_info(channel_inbox)")}
        if not {"sender_id", "outcome_reason"} <= cols:
            raise RuntimeError("Incomplete inbox migration; missing privacy or outcome columns")
    if not required <= tables:
        raise RuntimeError("Incomplete migration schema; stop writers and recover from verified evidence")


def ensure_schema(con: sqlite3.Connection, path: str) -> None:
    """Apply versioned upgrades, backing up existing data before schema changes.

    Raises RuntimeError on unknown versions or invalid integrity. A failed DDL or
    backfill rolls back with the ledger unchanged. Reopening is a verified no op.
    Backup restoration must occur offline; never restore over new audit evidence.
    """
    con.execute("PRAGMA foreign_keys=ON")
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    if exists:
        rows = con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
        ledger = [tuple(row) for row in rows]
        if ledger == _valid_ledgers()[-1]:
            validate_existing_ledger(con)
            return
        if ledger not in _valid_ledgers():
            raise RuntimeError("Unsupported migration ledger; stop writers and inspect the database")
        if len(rows) == 1 and path != ":memory:":
            backup_path = Path(f"{path}.before-v2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.sqlite")
            backup_path.touch(mode=0o600, exist_ok=False)
            with closing(sqlite3.connect(backup_path)) as backup:
                con.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Version two backup verification failed")
        upgrade_v2(con)
        upgrade_v3(con)
        upgrade_v4(con)
        upgrade_v5(con)
        upgrade_v6(con, path)
        return
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Database integrity check failed; no migration applied")
    if path != ":memory:" and con.execute("SELECT 1 FROM cases LIMIT 1").fetchone():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = Path(f"{path}.before-safety-{stamp}.sqlite")
        backup.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(backup)) as target:
            con.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("Backup verification failed; no migration applied")
    try:
        con.execute("BEGIN IMMEDIATE")
        # A second opener may have migrated while this connection made a backup.
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone():
            con.rollback()
            return ensure_schema(con, path)
        for statement in STATEMENTS:
            con.execute(statement)
        con.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
        con.execute("INSERT INTO schema_migrations VALUES (?,?,?)", (VERSION, CHECKSUM, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
        upgrade_v2(con)
        upgrade_v3(con)
        upgrade_v4(con)
        upgrade_v5(con)
        upgrade_v6(con, path)
    except BaseException:
        con.rollback()
        raise


STATEMENTS_V2 = [
    "DROP TRIGGER cases_content_revision",
    "CREATE TRIGGER cases_content_revision AFTER UPDATE OF draft,farmer_draft,sources,question,crop,region ON cases WHEN NEW.revision=OLD.revision BEGIN UPDATE cases SET revision=revision+1 WHERE id=NEW.id; END",
    "CREATE TABLE approvals(id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id), revision INTEGER NOT NULL, submission_id INTEGER REFERENCES advisory_submissions(id), assessment_id INTEGER REFERENCES safety_assessments(id), payload TEXT NOT NULL, fingerprint TEXT NOT NULL, provenance TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE acknowledgement_challenges(token_hash TEXT PRIMARY KEY, case_id INTEGER NOT NULL REFERENCES cases(id), assessment_id INTEGER NOT NULL REFERENCES safety_assessments(id), binding TEXT NOT NULL, expires_at TEXT NOT NULL, consumed_approval INTEGER REFERENCES approvals(id))",
    "CREATE TABLE audit_events(id INTEGER PRIMARY KEY, case_id INTEGER REFERENCES cases(id), event_name TEXT NOT NULL, actor TEXT NOT NULL, details TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE TABLE delivery_jobs(id INTEGER PRIMARY KEY, approval_id INTEGER NOT NULL REFERENCES approvals(id), channel TEXT NOT NULL, recipient_hash TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('pending','sending','accepted','definitely_failed','unknown','undeliverable')), claim_id TEXT, updated_at TEXT NOT NULL, UNIQUE(approval_id,channel))",
    "CREATE TABLE delivery_attempts(id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES delivery_jobs(id), claim_id TEXT NOT NULL UNIQUE, outcome TEXT NOT NULL, started_at TEXT NOT NULL, completed_at TEXT, detail TEXT)",
]
# Immutable content is distinct from mutable delivery state. An administrator who
# controls SQLite can still drop these guards; that is outside the trust boundary.
for _table in ("approvals", "advisory_submissions", "safety_assessments", "audit_events"):
    for _action in ("UPDATE", "DELETE"):
        STATEMENTS_V2.append(f"CREATE TRIGGER {_table}_{_action.lower()} BEFORE {_action} ON {_table} BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END")
CHECKSUM_V2 = hashlib.sha256("\n".join(STATEMENTS_V2).encode()).hexdigest()

STATEMENTS_V3 = [
    "CREATE TABLE farmer_case_access(case_id INTEGER PRIMARY KEY REFERENCES cases(id), token_sha256 TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)",
]
CHECKSUM_V3 = hashlib.sha256("\n".join(STATEMENTS_V3).encode()).hexdigest()


STATEMENTS_V4 = [
    "CREATE TABLE channel_inbox(id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, message_id TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN (\'pending\',\'processing\',\'completed\',\'failed\',\'uncertain\')), attempt_count INTEGER NOT NULL DEFAULT 0, lease_id TEXT, case_id INTEGER REFERENCES cases(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(channel,message_id))",
    "CREATE INDEX channel_inbox_pending_idx ON channel_inbox(state,created_at,id)",
]
CHECKSUM_V4 = hashlib.sha256("\n".join(STATEMENTS_V4).encode()).hexdigest()


STATEMENTS_V5 = [
    "ALTER TABLE channel_inbox ADD COLUMN sender_id TEXT",
    "ALTER TABLE channel_inbox ADD COLUMN outcome_reason TEXT",
    "CREATE INDEX channel_inbox_sender_idx ON channel_inbox(channel,sender_id)",
]
CHECKSUM_V5 = hashlib.sha256("\n".join(STATEMENTS_V5).encode()).hexdigest()


STATEMENTS_V6 = (
    """CREATE TABLE farmer_sms_contacts (
        case_id INTEGER PRIMARY KEY REFERENCES cases(id),
        phone_e164 TEXT NOT NULL,
        consent TEXT NOT NULL CHECK (consent = 'granted'),
        created_at TEXT NOT NULL)""",
    """CREATE TABLE acknowledgement_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id INTEGER NOT NULL UNIQUE REFERENCES cases(id),
        state TEXT NOT NULL CHECK (state IN ('pending','sending','accepted','definitely_failed','unknown','undeliverable')),
        claim_id TEXT,
        mode TEXT NOT NULL CHECK (mode IN ('simulated','live')),
        updated_at TEXT NOT NULL)""",
    """CREATE TABLE acknowledgement_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id INTEGER NOT NULL REFERENCES acknowledgement_jobs(id),
        claim_id TEXT NOT NULL UNIQUE,
        outcome TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        detail TEXT)""",
)
CHECKSUM_V6 = hashlib.sha256("\n".join(STATEMENTS_V6).encode()).hexdigest()


def _valid_ledgers():
    first = [(1, CHECKSUM)]
    second = first + [(2, CHECKSUM_V2)]
    third = second + [(3, CHECKSUM_V3)]
    fourth = third + [(4, CHECKSUM_V4)]
    fifth = fourth + [(5, CHECKSUM_V5)]
    return (first, second, third, fourth, fifth, fifth + [(6, CHECKSUM_V6)])


def upgrade_v2(con):
    """Upgrade approval and delivery storage atomically; preserve legacy provenance."""
    import json
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V2:
            con.execute(statement)
        for row in con.execute("SELECT * FROM cases WHERE officer IS NOT NULL AND status IN ('approved','released','not_delivered','undeliverable')").fetchall():
            payload = dict(row)
            text = json.dumps(payload, sort_keys=True)
            con.execute("INSERT INTO approvals(case_id,revision,payload,fingerprint,provenance,created_at) VALUES (?,?,?,?,'legacy_unvalidated',?)",
                        (row['id'], row['revision'], text, hashlib.sha256(text.encode()).hexdigest(), row['updated_at']))
        con.execute("INSERT INTO schema_migrations VALUES (2,?,?)", (CHECKSUM_V2, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v3(con):
    """Add private farmer case capability tokens without changing historical case evidence."""
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V3:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (3,?,?)",
                    (CHECKSUM_V3, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v4(con):
    """Create the durable inbound ledger; existing message IDs are not silently replayed."""
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V4:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (4,?,?)",
                    (CHECKSUM_V4, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v5(con):
    """Add sender-scoped erasure and auditable reconciliation reasons."""
    try:
        con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V5:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (5,?,?)",
                    (CHECKSUM_V5, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def _sql_tokens(sql):
    """Compare the known schema independent of SQL formatting and keyword case."""
    return tuple(token if token.startswith("'") else token.lower()
                 for token in re.findall(r"'(?:''|[^'])*'|\w+|[^\s]", sql))


def _sms_tables_exist(con, *, required=False):
    expected = {statement.split()[2]: _sql_tokens(statement) for statement in STATEMENTS_V6}
    names = tuple(expected)
    objects = con.execute(
        "SELECT lower(name), type, sql FROM sqlite_master "
        "WHERE lower(name) IN (?, ?, ?) OR (lower(tbl_name) IN (?, ?, ?) AND sql IS NOT NULL)",
        names + names,
    ).fetchall()
    if not objects and not required:
        return False
    if (len(objects) != len(expected)
            or any(kind != "table" or _sql_tokens(sql or "") != expected.get(name)
                   for name, kind, sql in objects)):
        raise RuntimeError("Incompatible or incomplete acknowledgement schema; migration refused")
    return True


def upgrade_v6(con, path):
    """Back up and upgrade v5 under a write reservation, or adopt the exact legacy SMS schema."""
    try:
        con.execute("BEGIN IMMEDIATE")
        ledger = [tuple(row) for row in con.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version")]
        if ledger == _valid_ledgers()[-1]:
            _sms_tables_exist(con, required=True)
            con.commit()
            return
        if ledger != _valid_ledgers()[-2]:
            raise RuntimeError("Unsupported migration ledger; version 6 refused")
        existing = _sms_tables_exist(con)
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity verification failed")
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        if path != ":memory:":
            # A second connection reads the committed snapshot while BEGIN IMMEDIATE
            # prevents concurrent writers. Backing up from con would block on its transaction.
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
            backup_path = Path(f"{path}.before-v6-{stamp}.sqlite")
            partial = backup_path.with_suffix(".sqlite.partial")
            partial.touch(mode=0o600, exist_ok=False)
            uri = Path(path).resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(partial)) as backup:
                source.backup(backup)
                if (backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                        or backup.execute("PRAGMA foreign_key_check").fetchone()):
                    raise RuntimeError("Version six backup verification failed")
            partial.rename(backup_path)
        if not existing:
            for statement in STATEMENTS_V6:
                con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (6,?,?)",
                    (CHECKSUM_V6, datetime.now(timezone.utc).isoformat()))
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def main():
    """Offline operator migration/verification entry point. Never sends messages."""
    import argparse
    parser = argparse.ArgumentParser(description="Stop application writers before upgrading SQLite")
    parser.add_argument("path", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        with closing(sqlite3.connect(args.path.resolve().as_uri() + "?mode=ro", uri=True)) as con:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or con.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("SQLite integrity verification failed")
            ledger = con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
            if ledger != _valid_ledgers()[-1]:
                raise RuntimeError("Schema version or checksum mismatch")
            validate_existing_ledger(con)
        print("Schema versions 1 through 6 verified; integrity and foreign keys OK")
    else:
        from agrireach import db
        con = db.connect(str(args.path))
        con.close()
        print("Migration complete. Verify the backup and database before restarting writers.")


if __name__ == "__main__":
    main()
