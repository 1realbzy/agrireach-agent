"""Officer email/password hashing, login, lockout, add_officer script, and retired tokens."""
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agrireach import db, passwords
from agrireach.api import app
from agrireach.migrations import CHECKSUM, CHECKSUM_V2, ensure_schema, upgrade_v3
import officer_helpers

c = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]
PASSWORD = "correct-horse-12"


def test_password_hash_is_argon2id_and_not_plaintext():
    digest = passwords.hash_password(PASSWORD)
    assert digest.startswith("$argon2id$")
    assert PASSWORD not in digest
    assert passwords.verify_password(PASSWORD, digest)
    assert not passwords.verify_password("wrong-password-12", digest)
    assert not passwords.verify_password(PASSWORD, None)
    assert not passwords.verify_password("", digest)


def test_hash_password_enforces_minimum_length():
    with pytest.raises(ValueError, match="at least 12"):
        passwords.hash_password("short")


def test_add_officer_stores_normalized_email_and_hash_only():
    db.add_officer(db.connect(), "Ama Mensah", email="Ama@AgriReach.Demo", password=PASSWORD)
    con = db.connect()
    row = con.execute("SELECT email, password_hash FROM officers WHERE name=?", ("Ama Mensah",)).fetchone()
    assert row["email"] == "ama@agrireach.demo"
    assert row["password_hash"].startswith("$argon2id$")
    dump = "\n".join(con.iterdump())
    assert PASSWORD not in dump
    assert "Ama@AgriReach.Demo" not in dump


def test_login_success_issues_session_that_is_not_stored_in_clear():
    db.add_officer(db.connect(), "Ama Mensah", email="ama@agrireach.demo", password=PASSWORD)
    result = db.login_officer(db.connect(), "AMA@agrireach.demo", PASSWORD)
    assert result is not None
    name, token, expires = result
    assert name == "Ama Mensah" and token and expires
    con = db.connect()
    assert token not in "\n".join(con.iterdump())
    assert db.officer_for_session(con, token) == "Ama Mensah"
    assert db.officer_for_session(con, "not-a-real-session") is None


def test_login_failure_does_not_reveal_whether_email_or_password_is_wrong():
    db.add_officer(db.connect(), "Ama Mensah", email="ama@agrireach.demo", password=PASSWORD)
    assert db.login_officer(db.connect(), "ama@agrireach.demo", "wrong-password-12") is None
    assert db.login_officer(db.connect(), "unknown@agrireach.demo", PASSWORD) is None
    r_wrong = c.post("/officer/login", json={"email": "ama@agrireach.demo", "password": "wrong-password-12"})
    r_missing = c.post("/officer/login", json={"email": "unknown@agrireach.demo", "password": PASSWORD})
    assert r_wrong.status_code == r_missing.status_code == 401
    assert r_wrong.json() == r_missing.json() == {"detail": "Sign in details were not recognised."}


def test_login_api_success_and_unauthorised_routes():
    db.add_officer(db.connect(), "Ama Mensah", email="ama@agrireach.demo", password=PASSWORD)
    r = c.post("/officer/login", json={"email": "ama@agrireach.demo", "password": PASSWORD})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["officer"] == "Ama Mensah"
    assert body["token"]
    assert body["token"] not in "\n".join(db.connect().iterdump())
    headers = {"Authorization": f"Bearer {body['token']}"}
    assert c.get("/officer/queue", headers=headers).status_code == 200
    assert c.get("/officer/queue").status_code == 401
    assert c.get("/officer/queue", headers={"Authorization": "Bearer not-a-real-session"}).status_code == 401
    assert c.post("/officer/logout", headers=headers).status_code == 200
    assert c.get("/officer/queue", headers=headers).status_code == 401


def test_lockout_after_repeated_failures():
    db.add_officer(db.connect(), "Ama Mensah", email="ama@agrireach.demo", password=PASSWORD)
    for _ in range(db.LOGIN_FAILURE_LIMIT - 1):
        assert c.post("/officer/login", json={"email": "ama@agrireach.demo", "password": "wrong-password-12"}).status_code == 401
    locked = c.post("/officer/login", json={"email": "ama@agrireach.demo", "password": "wrong-password-12"})
    assert locked.status_code == 429
    still = c.post("/officer/login", json={"email": "ama@agrireach.demo", "password": PASSWORD})
    assert still.status_code == 429
    assert locked.json() == {"detail": "Too many sign-in attempts. Try again later."}


def test_migrated_token_officer_cannot_sign_in_until_password_is_set(tmp_path):
    path = tmp_path / "token-officers.sqlite"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
    con.execute("INSERT INTO schema_migrations VALUES (1, ?, 't')", (CHECKSUM,))
    con.execute("INSERT INTO schema_migrations VALUES (2, ?, 't')", (CHECKSUM_V2,))
    con.execute("CREATE TABLE officers(name TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO officers VALUES ('Ama Mensah', 'abc123deadbeef', '2026-01-01T00:00:00+00:00')")
    con.commit()
    upgrade_v3(con)
    cols = {r[1] for r in con.execute("PRAGMA table_info(officers)")}
    assert "password_hash" in cols and "email" in cols and "token_sha256" not in cols
    row = con.execute("SELECT name, email, password_hash FROM officers").fetchone()
    assert tuple(row) == ("Ama Mensah", None, None)
    assert "abc123deadbeef" not in "\n".join(con.iterdump())
    assert db.login_officer(con, "ama@agrireach.demo", PASSWORD) is None
    db.add_officer(con, "Ama Mensah", email="ama@agrireach.demo", password=PASSWORD)
    assert db.login_officer(con, "ama@agrireach.demo", PASSWORD) is not None


def test_upgrade_v3_is_idempotent_and_fails_closed_on_bad_sql(monkeypatch, tmp_path):
    from agrireach import migrations
    path = tmp_path / "broken-v3.sqlite"
    con = db.connect(str(path))
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3]
    ensure_schema(con, str(path))
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations ORDER BY version")] == [1, 2, 3]
    con.close()
    broken = tmp_path / "broken-apply.sqlite"
    fresh = db.connect(str(broken))
    fresh.execute("DELETE FROM schema_migrations WHERE version=3")
    fresh.execute("DROP TABLE officer_sessions")
    fresh.execute("DROP TABLE officer_login_lockouts")
    fresh.commit()
    fresh.close()
    con = sqlite3.connect(broken)
    con.row_factory = sqlite3.Row
    monkeypatch.setattr(migrations, "STATEMENTS_V3", migrations.STATEMENTS_V3 + ["INVALID SQL"])
    with pytest.raises(sqlite3.OperationalError):
        migrations.upgrade_v3(con)
    assert [r[0] for r in con.execute("SELECT version FROM schema_migrations")] == [1, 2]
    assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='officer_sessions'").fetchone()


def test_add_officer_script_via_stdin(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/officers.db"
    env = {k: v for k, v in os.environ.items() if k not in {"AGRIREACH_OFFICER_PASSWORD", "LLM_API_KEY", "AGRIREACH_OPENROUTER_API_KEY"}}
    env.update({"DATABASE_URL": db_url, "PYTHONPATH": str(ROOT / "src"), "PWD": str(ROOT)})
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/add_officer.py"), "Ama Mensah", "ama@agrireach.demo"],
        input=f"{PASSWORD}\n{PASSWORD}\n",
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert "ama@agrireach.demo" in proc.stdout
    assert PASSWORD not in proc.stdout and PASSWORD not in proc.stderr
    monkeypatch.setenv("DATABASE_URL", db_url)
    assert db.login_officer(db.connect(), "ama@agrireach.demo", PASSWORD) is not None


def test_add_officer_script_env_password_and_rejects_argv_password(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/officers.db"
    env = {k: v for k, v in os.environ.items() if k not in {"LLM_API_KEY", "AGRIREACH_OPENROUTER_API_KEY"}}
    env.update({
        "DATABASE_URL": db_url,
        "PYTHONPATH": str(ROOT / "src"),
        "AGRIREACH_OFFICER_PASSWORD": PASSWORD,
    })
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/add_officer.py"), "Ama Mensah", "ama@agrireach.demo"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    assert PASSWORD not in proc.stdout and PASSWORD not in proc.stderr
    rejected = subprocess.run(
        [sys.executable, str(ROOT / "scripts/add_officer.py"), "Ama Mensah", "ama@agrireach.demo", PASSWORD],
        capture_output=True,
        text=True,
        env={**env, "AGRIREACH_OFFICER_PASSWORD": ""},  # unused; three argv is usage
        cwd=str(ROOT),
    )
    assert rejected.returncode != 0
    assert PASSWORD not in rejected.stdout
    # Usage text should not treat the third argument as accepted.
    monkeypatch.setenv("DATABASE_URL", db_url)
    # Empty env password would fail length if the script ran; it should have exited first.
    assert db.login_officer(db.connect(), "ama@agrireach.demo", PASSWORD) is not None


def test_add_officer_script_mismatch_and_short_password(tmp_path):
    db_url = f"sqlite:///{tmp_path}/officers.db"
    env = {k: v for k, v in os.environ.items() if k not in {"AGRIREACH_OFFICER_PASSWORD", "LLM_API_KEY", "AGRIREACH_OPENROUTER_API_KEY"}}
    env.update({"DATABASE_URL": db_url, "PYTHONPATH": str(ROOT / "src")})
    script = [sys.executable, str(ROOT / "scripts/add_officer.py"), "Ama Mensah", "ama@agrireach.demo"]
    mismatch = subprocess.run(script, input=f"{PASSWORD}\nother-password-1\n", capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert mismatch.returncode != 0
    assert "did not match" in mismatch.stderr
    assert PASSWORD not in mismatch.stdout and PASSWORD not in mismatch.stderr
    short = subprocess.run(script, input="short\nshort\n", capture_output=True, text=True, env=env, cwd=str(ROOT))
    assert short.returncode != 0
    assert "at least 12" in short.stderr


def test_farmer_waiting_messages():
    from agrireach.ui import FARMER_NEEDS_INFO, FARMER_REJECTED, FARMER_REVIEWING, farmer_waiting_message
    assert farmer_waiting_message({"status": "pending_review", "message": FARMER_REVIEWING}) == FARMER_REVIEWING
    assert farmer_waiting_message({"status": "rejected"}) == FARMER_REJECTED
    assert farmer_waiting_message({"status": "needs_info"}) == FARMER_NEEDS_INFO
