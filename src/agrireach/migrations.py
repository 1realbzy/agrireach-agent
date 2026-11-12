"""Versioned SQLite upgrades. Never discard evidence in a destructive downgrade."""
from __future__ import annotations

from contextlib import closing
import hashlib
import re
import sqlite3
import tempfile
from uuid import uuid4
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


BACKUP_STAGING_PREFIX = ".agrireach-backup-"


def validate_database_path(path: str | Path) -> Path:
    """Reject unpublished backup inputs and return the checked filesystem path."""
    requested = Path(path)
    resolved = requested.resolve()
    for candidate in (requested, resolved):
        if candidate.name.lower().endswith(".partial") or any(
            part.lower().startswith(BACKUP_STAGING_PREFIX) for part in candidate.parent.parts
        ):
            raise ValueError("Incomplete backup artifacts cannot be used as migration inputs")
    return resolved


def _migration_statements():
    return (STATEMENTS, STATEMENTS_V2, STATEMENTS_V3, STATEMENTS_V4, STATEMENTS_V5, STATEMENTS_V6)


def validate_existing_ledger(con, *, adopt_legacy_sms=False):
    """Reject unknown or incomplete upgraded databases before bootstrap writes."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "schema_migrations" not in tables:
        _sms_tables_exist(con)
        migrated_tables = {stmt.split()[2].split("(")[0]
                           for migration in _migration_statements()
                           for stmt in migration if stmt.startswith("CREATE TABLE ")}
        case_columns = {r[1] for r in con.execute("PRAGMA table_info(cases)")}
        if tables & migrated_tables or "revision" in case_columns or con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='cases_content_revision'"
        ).fetchone():
            raise RuntimeError("Missing schema_migrations table for upgraded schema")
        return 0, tables
    rows = con.execute("SELECT version,checksum,applied_at FROM schema_migrations ORDER BY version").fetchall()
    ledger = [(version, checksum) for version, checksum, _ in rows]
    if ledger not in _valid_ledgers() or any(not _valid_timestamp(row[2]) for row in rows):
        raise RuntimeError("Unsupported migration ledger; no bootstrap writes performed")
    version = len(ledger)
    if _sms_tables_exist(con, required=version == 6) and version < 6:
        if version != 5 or not adopt_legacy_sms:
            raise RuntimeError("Unrecorded acknowledgement schema; explicit legacy adoption required")
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
    if _pending_bootstrap(con, tables):
        raise RuntimeError("Incomplete bootstrap schema; missing required tables or columns")
    _verify_immutable_triggers(con, version)
    return version, tables


def _valid_timestamp(value):
    try:
        return datetime.fromisoformat(value).utcoffset() is not None
    except (TypeError, ValueError):
        return False


def _verify_migration(con, expected_version):
    version, _ = validate_existing_ledger(con)
    if version != expected_version:
        raise RuntimeError(f"Schema version or checksum mismatch; migration {expected_version} is incomplete")


BOOTSTRAP_STATEMENTS = {
    "cases": """CREATE TABLE IF NOT EXISTS cases (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question TEXT NOT NULL, crop TEXT, region TEXT,
      draft TEXT, final_text TEXT,
      sources TEXT DEFAULT '[]',
      priority TEXT DEFAULT 'routine', urgent_reasons TEXT DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'draft',
      officer TEXT, decided_at TEXT, officer_note TEXT,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""",
    "officers": """CREATE TABLE IF NOT EXISTS officers (
      name TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)""",
    "tool_log": """CREATE TABLE IF NOT EXISTS tool_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
      case_id INTEGER, actor TEXT NOT NULL, tool TEXT NOT NULL,
      args TEXT, result_summary TEXT, ok INTEGER NOT NULL)""",
    "channel_contacts": """CREATE TABLE IF NOT EXISTS channel_contacts (
      case_id INTEGER PRIMARY KEY REFERENCES cases(id),
      channel TEXT NOT NULL, sender_id TEXT NOT NULL,
      audio_path TEXT, transcript TEXT, stt TEXT, created_at TEXT NOT NULL)""",
    "channel_deliveries": """CREATE TABLE IF NOT EXISTS channel_deliveries (
      id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id),
      channel TEXT NOT NULL, kind TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT, ts TEXT NOT NULL)""",
    "channel_inbound_seen": """CREATE TABLE IF NOT EXISTS channel_inbound_seen (
      channel TEXT NOT NULL, message_id TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (channel, message_id))""",
    "channel_consent": """CREATE TABLE IF NOT EXISTS channel_consent (
      channel TEXT NOT NULL, sender_id TEXT NOT NULL, status TEXT NOT NULL, asked_at TEXT NOT NULL,
      decided_at TEXT, PRIMARY KEY (channel, sender_id))""",
    "channel_pending": """CREATE TABLE IF NOT EXISTS channel_pending (
      id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, sender_id TEXT NOT NULL,
      kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL)""",
}


def _pending_bootstrap(con, tables):
    statements = [statement for table, statement in BOOTSTRAP_STATEMENTS.items()
                  if table not in tables]
    columns = {row[1] for row in con.execute("PRAGMA table_info(cases)")}
    statements.extend(f"ALTER TABLE cases ADD COLUMN {column} TEXT"
                      for column in ("farmer_draft", "farmer_text") if column not in columns)
    return statements


def _verified_backup(con, path, label):
    """Copy the committed database while con holds a write reservation."""
    if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite integrity verification failed")
    if con.execute("PRAGMA foreign_key_check").fetchone():
        raise RuntimeError("Foreign key verification failed")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    backup_path = Path(f"{path}.before-{label}-{stamp}-{uuid4().hex}.sqlite")
    # An interrupted process can leave this private directory behind. Only a
    # verified copy is published alongside the source, by a same-volume rename.
    staging = Path(tempfile.mkdtemp(prefix=BACKUP_STAGING_PREFIX, dir=backup_path.parent))
    partial = staging / backup_path.with_suffix(".sqlite.partial").name
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    try:
        partial.touch(mode=0o600, exist_ok=False)
        with closing(sqlite3.connect(uri, uri=True)) as source, closing(sqlite3.connect(partial)) as backup:
            source.backup(backup)
            if (backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
                    or backup.execute("PRAGMA foreign_key_check").fetchone()):
                raise RuntimeError("Backup verification failed; no migration applied")
        partial.rename(backup_path)
    finally:
        partial.unlink(missing_ok=True)
        if not any(staging.iterdir()):
            staging.rmdir()


def ensure_schema(con: sqlite3.Connection, path: str, *, existing_file=True, adopt_legacy_sms=False) -> None:
    """Apply historical upgrades after backing up the original schema and data."""
    con.execute("PRAGMA foreign_keys=ON")
    # SQLite only runs DELETE triggers for REPLACE when recursive triggers are enabled.
    con.execute("PRAGMA recursive_triggers=ON")
    con.execute("BEGIN")
    try:
        version, _ = validate_existing_ledger(con, adopt_legacy_sms=adopt_legacy_sms)
    finally:
        con.rollback()
    needs_backup = path != ":memory:"
    if version < 5:
        try:
            con.execute("BEGIN IMMEDIATE")
            # Recheck under the lock. Another initializer may have finished.
            version, tables = validate_existing_ledger(con, adopt_legacy_sms=adopt_legacy_sms)
            if version < 5:
                if needs_backup and (existing_file or tables):
                    label = "safety" if version == 0 else f"v{version + 1}"
                    _verified_backup(con, path, label)
                needs_backup = False
            if version == 0:
                for statement in _pending_bootstrap(con, tables):
                    con.execute(statement)
                for statement in STATEMENTS:
                    con.execute(statement)
                con.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
                con.execute("INSERT INTO schema_migrations VALUES (?,?,?)",
                            (VERSION, CHECKSUM, datetime.now(timezone.utc).isoformat()))
                _verify_migration(con, VERSION)
            if 1 <= version < 5:
                # Keep the write reservation through the first historical upgrade.
                (upgrade_v2, upgrade_v3, upgrade_v4, upgrade_v5)[version - 1](con, reserved=True)
                version += 1
            else:
                if con.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Foreign key verification failed")
                con.commit()
        except BaseException:
            con.rollback()
            raise
    if version < 2:
        upgrade_v2(con)
    if version < 3:
        upgrade_v3(con)
    if version < 4:
        upgrade_v4(con)
    if version < 5:
        upgrade_v5(con)
    if version < 6:
        upgrade_v6(con, path if needs_backup else None, adopt_legacy_sms=adopt_legacy_sms)
        # Check the committed state at the entry point as well as before commit.
        con.execute("BEGIN")
        try:
            _verify_migration(con, 6)
        finally:
            con.rollback()


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
IMMUTABLE_TRIGGERS = {
    f"{table}_{action.lower()}": (
        f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
        "BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END"
    )
    for table in ("approvals", "advisory_submissions", "safety_assessments", "audit_events")
    for action in ("UPDATE", "DELETE")
}
STATEMENTS_V2.extend(IMMUTABLE_TRIGGERS.values())
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


def upgrade_v2(con, *, reserved=False):
    """Upgrade approval and delivery storage atomically; preserve legacy provenance."""
    import json
    try:
        if not reserved:
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
        _verify_migration(con, 2)
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v3(con, *, reserved=False):
    """Add private farmer case capability tokens without changing historical case evidence."""
    try:
        if not reserved:
            con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V3:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (3,?,?)",
                    (CHECKSUM_V3, datetime.now(timezone.utc).isoformat()))
        _verify_migration(con, 3)
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v4(con, *, reserved=False):
    """Create the durable inbound ledger; existing message IDs are not silently replayed."""
    try:
        if not reserved:
            con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V4:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (4,?,?)",
                    (CHECKSUM_V4, datetime.now(timezone.utc).isoformat()))
        _verify_migration(con, 4)
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        con.commit()
    except BaseException:
        con.rollback()
        raise


def upgrade_v5(con, *, reserved=False):
    """Add sender-scoped erasure and auditable reconciliation reasons."""
    try:
        if not reserved:
            con.execute("BEGIN IMMEDIATE")
        if con.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone():
            con.rollback()
            return
        for statement in STATEMENTS_V5:
            con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (5,?,?)",
                    (CHECKSUM_V5, datetime.now(timezone.utc).isoformat()))
        _verify_migration(con, 5)
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


def _verify_immutable_triggers(con, version):
    # Derive the effective inventory from the versioned SQL. In v2 the
    # case revision trigger is dropped and replaced by a different definition.
    expected = {}
    for migration in _migration_statements()[:version]:
        for stmt in migration:
            tokens = stmt.split()
            if tokens[:2] == ["CREATE", "TRIGGER"]:
                expected[tokens[2]] = stmt
            elif tokens[:2] == ["DROP", "TRIGGER"]:
                del expected[tokens[2]]
    actual = con.execute("SELECT lower(name), lower(tbl_name), sql FROM sqlite_master WHERE type='trigger'")
    protected_tables = {stmt.split(" ON ", 1)[1].split()[0] for stmt in expected.values()}
    definitions = {name: sql for name, table, sql in actual if table in protected_tables}
    for name, stmt in expected.items():
        if _sql_tokens(definitions.get(name) or "") != _sql_tokens(stmt):
            raise RuntimeError(f"Missing or incompatible immutable evidence trigger: {name}")
    if definitions.keys() - expected.keys():
        raise RuntimeError("Unexpected trigger on a protected evidence table")
    case_columns = {row[1] for row in con.execute("PRAGMA table_info(cases)")}
    if not {"id", "revision", "draft", "farmer_draft", "sources", "question", "crop", "region", "status"} <= case_columns:
        raise RuntimeError("Incomplete case revision schema")


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


def upgrade_v6(con, path, *, adopt_legacy_sms=False):
    """Back up and upgrade v5 under a write reservation, or adopt the exact legacy SMS schema."""
    try:
        con.execute("BEGIN IMMEDIATE")
        version, _ = validate_existing_ledger(con, adopt_legacy_sms=adopt_legacy_sms)
        if version == 6:
            con.rollback()
            return
        if version != 5:
            raise RuntimeError("Unsupported migration ledger; version 6 refused")
        existing = _sms_tables_exist(con)
        if path is not None:
            _verified_backup(con, path, "v6")
        elif con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity verification failed")
        if con.execute("PRAGMA foreign_key_check").fetchone():
            raise RuntimeError("Foreign key verification failed")
        if not existing:
            for statement in STATEMENTS_V6:
                con.execute(statement)
        con.execute("INSERT INTO schema_migrations VALUES (6,?,?)",
                    (CHECKSUM_V6, datetime.now(timezone.utc).isoformat()))
        _verify_migration(con, 6)
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
    parser.add_argument("--adopt-legacy-sms", action="store_true",
                        help="Explicitly adopt complete pre-ledger SMS tables from a known legacy v5 database")
    args = parser.parse_args()
    if args.adopt_legacy_sms and args.verify_only:
        parser.error("--adopt-legacy-sms requires a write migration")
    try:
        path = validate_database_path(args.path)
    except ValueError as exc:
        parser.error(str(exc))
    if args.verify_only:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as con:
            con.execute("BEGIN")  # Verify one consistent read-only snapshot.
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or con.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("SQLite integrity verification failed")
            if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone():
                raise RuntimeError("Missing schema_migrations table")
            if con.execute("SELECT version,checksum FROM schema_migrations ORDER BY version").fetchall() != _valid_ledgers()[-1]:
                raise RuntimeError("Schema version or checksum mismatch")
            _verify_migration(con, 6)
        print("Schema versions 1 through 6 verified; integrity, foreign keys and immutable evidence triggers OK")
    else:
        from agrireach import db
        con = db.connect(str(args.path), adopt_legacy_sms=args.adopt_legacy_sms)
        con.close()
        print("Migration complete. Verify the backup and database before restarting writers.")


if __name__ == "__main__":
    main()
