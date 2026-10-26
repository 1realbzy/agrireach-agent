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
        if [(r[0], r[1]) for r in rows] != [(VERSION, CHECKSUM)]:
            raise RuntimeError("Unsupported migration ledger; stop writers and inspect the database")
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
    except BaseException:
        con.rollback()
        raise
