from contextlib import closing
import sqlite3

import pytest

from agrireach import db, migrations


@pytest.mark.parametrize("replacement", [None, "BEFORE UPDATE ON approvals BEGIN SELECT 1; END",
                                          "BEFORE UPDATE ON approvals WHEN 0 BEGIN "
                                          "SELECT RAISE(ABORT, 'immutable evidence'); END"])
def test_verify_only_detects_incompatible_approval_trigger(tmp_path, monkeypatch, replacement):
    path = tmp_path / "trigger.sqlite"
    with closing(db.connect(str(path))) as con, con:
        con.execute("DROP TRIGGER approvals_update")
        if replacement:
            con.execute(f"CREATE TRIGGER approvals_update {replacement}")
    before = path.read_bytes()
    monkeypatch.setattr("sys.argv", ["migrations", str(path), "--verify-only"])
    with pytest.raises(RuntimeError, match="immutable evidence trigger"):
        migrations.main()
    assert path.read_bytes() == before
    with pytest.raises(RuntimeError, match="immutable evidence trigger"):
        db.connect(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize(("sql", "error"), [
    ("DROP TABLE schema_migrations", "Missing schema_migrations table"),
    ("DROP TABLE approvals", "Incomplete migration schema"),
    ("DROP TABLE channel_pending", "Incomplete bootstrap schema"),
    ("UPDATE schema_migrations SET version=7 WHERE version=6", "Schema version or checksum mismatch"),
    ("UPDATE schema_migrations SET checksum='wrong' WHERE version=2", "Schema version or checksum mismatch"),
])
def test_verify_only_rejects_incomplete_or_incompatible_schema(tmp_path, monkeypatch, sql, error):
    path = tmp_path / "verify.sqlite"
    with closing(db.connect(str(path))):
        pass
    with closing(sqlite3.connect(path)) as con, con:
        con.execute(sql)
    before = path.read_bytes()
    monkeypatch.setattr("sys.argv", ["migrations", str(path), "--verify-only"])
    with pytest.raises(RuntimeError, match=error):
        migrations.main()
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
