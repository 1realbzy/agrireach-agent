"""Upgrade a temporary legacy fixture copy and verify preserved publication/audit data."""
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from agrireach import migrations


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/safety/legacy.sql"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "legacy.sqlite"
        with sqlite3.connect(path) as con:
            con.executescript(fixture.read_text())
            before = con.execute("SELECT * FROM cases").fetchall()
            logs = con.execute("SELECT * FROM tool_log").fetchall()
        con = sqlite3.connect(path)
        con.row_factory = sqlite3.Row
        migrations.ensure_schema(con, str(path))
        assert [tuple(row)[:-1] for row in con.execute("SELECT * FROM cases")] == before
        assert [tuple(row) for row in con.execute("SELECT * FROM tool_log")] == logs
        assert con.execute("SELECT provenance FROM approvals").fetchone()[0] == "legacy_unvalidated"
        con.close()
        backups = list(Path(directory).glob("*.before-safety-*.sqlite"))
        assert backups
        for backup in backups:
            assert backup.stat().st_mode & 0o777 == 0o600
        subprocess.run([sys.executable, "-m", "agrireach.migrations", str(path), "--verify-only"], check=True)
    print("Legacy publication, audit rows, backfill, backup and verification preserved")


if __name__ == "__main__":
    main()
