"""Versioned SQLite upgrades. Never discard evidence in a destructive downgrade."""
from __future__ import annotations

import hashlib
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
        return
    ledger = [tuple(r) for r in con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version")]
    if ledger not in ([(1, CHECKSUM)], [(1, CHECKSUM), (2, CHECKSUM_V2)]):
        raise RuntimeError("Unsupported migration ledger; no bootstrap writes performed")
    required = {"cases", "advisory_submissions", "safety_assessments"}
    if len(ledger) == 2:
        required |= {"approvals", "acknowledgement_challenges", "audit_events", "delivery_jobs", "delivery_attempts"}
    if not required <= tables:
        raise RuntimeError("Incomplete migration schema; stop writers and recover from verified evidence")


def ensure_schema(con: sqlite3.Connection, path: str) -> None:
    """Apply version one atomically, backing up nonempty legacy databases first.

    Raises RuntimeError on unknown versions or invalid integrity. A failed DDL or
    backfill rolls back with the ledger unchanged. Reopening is a verified no op.
    Backup restoration must occur offline; never restore over new audit evidence.
    """
    con.execute("PRAGMA foreign_keys=ON")
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    if exists:
        rows = con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
        if [(r[0], r[1]) for r in rows] not in ([(VERSION, CHECKSUM)], [(VERSION, CHECKSUM), (2, CHECKSUM_V2)]):
            raise RuntimeError("Unsupported migration ledger; stop writers and inspect the database")
        if len(rows) == 1 and path != ":memory:":
            backup_path = Path(f"{path}.before-v2-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.sqlite")
            backup_path.touch(mode=0o600, exist_ok=False)
            with sqlite3.connect(backup_path) as backup:
                con.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Version two backup verification failed")
        upgrade_v2(con)
        return
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("Database integrity check failed; no migration applied")
    if path != ":memory:" and con.execute("SELECT 1 FROM cases LIMIT 1").fetchone():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        backup = Path(f"{path}.before-safety-{stamp}.sqlite")
        backup.touch(mode=0o600, exist_ok=False)
        with sqlite3.connect(backup) as target:
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


def main():
    """Offline operator migration/verification entry point. Never sends messages."""
    import argparse
    parser = argparse.ArgumentParser(description="Stop application writers before upgrading SQLite")
    parser.add_argument("path", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        with sqlite3.connect(f"file:{args.path.resolve()}?mode=ro", uri=True) as con:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or con.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("SQLite integrity verification failed")
            ledger = con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall()
            if ledger != [(1, CHECKSUM), (2, CHECKSUM_V2)]:
                raise RuntimeError("Schema version or checksum mismatch")
        print("Schema versions 1 and 2 verified; integrity and foreign keys OK")
    else:
        from agrireach import db
        con = db.connect(str(args.path))
        con.close()
        print("Migration complete. Verify the backup and database before restarting writers.")


if __name__ == "__main__":
    main()
