"""Synthetic reproductions of the six independent review findings."""
from contextlib import closing
import json
import logging
import os
import socket
import sqlite3
import subprocess
import sys
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from agrireach import db, migrations
from agrireach.api import app
from agrireach.channels import mnotify


def test_cli_rejects_a_silently_ignored_v6_ledger_insert(tmp_path, monkeypatch, capsys):
    path = tmp_path / "v5.sqlite"
    with closing(db.connect(str(path))) as con, con:
        for ddl in reversed(migrations.STATEMENTS_V6):
            con.execute(f"DROP TABLE {ddl.split()[2]}")
        con.execute("DELETE FROM schema_migrations WHERE version=6")
        con.execute("CREATE TRIGGER ignore_v6 BEFORE INSERT ON schema_migrations "
                    "WHEN NEW.version=6 BEGIN SELECT RAISE(IGNORE); END")
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["migrations", str(path)])
    with pytest.raises(RuntimeError):
        migrations.main()
    assert "Migration complete" not in capsys.readouterr().out
    assert path.read_bytes() == before


def test_verify_rejects_missing_case_revision_trigger(tmp_path, monkeypatch):
    path = tmp_path / "revision.sqlite"
    with closing(db.connect(str(path))) as con, con:
        con.execute("DROP TRIGGER cases_content_revision")
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["migrations", str(path), "--verify-only"])
    with pytest.raises(RuntimeError, match="cases_content_revision"):
        migrations.main()
    assert path.read_bytes() == before


@pytest.mark.parametrize("route", ["acknowledgement", "delivery"])
@pytest.mark.parametrize("accepted", [True, False])
def test_authenticated_reconciliation_keeps_private_input_out_of_audit(route, accepted, caplog):
    with closing(db.connect()) as con:
        case_id = db.agent_upsert_case(con, status="pending_review", question="Synthetic case")
        officer_token = db.add_officer(con, "Synthetic officer")
        farmer_token = db.issue_farmer_case_token(con, case_id)
        with con:
            if route == "acknowledgement":
                con.execute("INSERT INTO acknowledgement_jobs VALUES (1, ?, 'unknown', NULL, 'simulated', ?)",
                            (case_id, db.now()))
            else:
                con.execute("INSERT INTO safety_assessments VALUES (1, ?, 'snapshot', 'assessment', ?)",
                            (case_id, db.now()))
                con.execute("INSERT INTO approvals VALUES (1, ?, 1, NULL, 1, 'payload', 'fingerprint', 'fixture', ?)",
                            (case_id, db.now()))
                con.execute("INSERT INTO delivery_jobs VALUES (1, 1, 'sms', 'hash', 'unknown', NULL, ?)", (db.now(),))
        secrets = ("+233240000001", farmer_token, officer_token, "synthetic-provider-credential")
        body = {"accepted": accepted, "provider_evidence": " ".join(secrets)}
        endpoint = f"/officer/{route}-jobs/1/reconcile"
        with TestClient(app) as client:
            denied = client.post(endpoint, json=body)
            headers = {"Authorization": f"Bearer {officer_token}"}
            response = client.post(endpoint, headers=headers, json=body)
            repeat = client.post(endpoint, headers=headers, json=body)
        assert (denied.status_code, response.status_code, repeat.status_code) == (401, 200, 409)
        (event,) = con.execute("SELECT * FROM audit_events").fetchall()
        assert (event["case_id"], event["actor"], event["event_name"]) == (case_id, "Synthetic officer", route + "_reconciled")
        details = json.loads(event["details"])
        assert details["accepted"] == accepted
        assert all(secret not in event["details"] + denied.text + response.text + repeat.text + caplog.text
                   for secret in secrets)
        assert details["job_id"] == 1 and details["revision"] == 1
        assert event["created_at"]


def test_httpcore_byte_repr_does_not_expose_provider_credential(monkeypatch, caplog):
    from httpcore import MockBackend

    key = "synthetic-é-credential"
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")
    monkeypatch.setenv("MNOTIFY_API_KEY", key)
    monkeypatch.setenv("MNOTIFY_SENDER_ID", "AgriReach")
    caplog.set_level(logging.DEBUG)

    wire_response = b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\nX-Echo: " + key.encode() + b"\r\n\r\n"
    transport = httpx.HTTPTransport(trust_env=False)
    transport._pool._network_backend = MockBackend([wire_response])
    with httpx.Client(transport=transport, trust_env=False) as client:
        assert mnotify.transmit("+233240000001", "Synthetic", client=client).outcome == "definitely_failed"
    assert "receive_response_headers.complete" in caplog.text
    assert repr(key.encode())[2:-1] not in caplog.text


def test_uvicorn_rejected_request_does_not_log_query(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # The standard development launcher runs this Uvicorn entrypoint.
    command = [sys.executable, "-m", "uvicorn", "agrireach.api:app", "--host", "127.0.0.1", "--port", str(port)]
    log_path = tmp_path / "uvicorn.log"
    with log_path.open("wb") as log:
        process = subprocess.Popen(command, env=os.environ, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(trust_env=False) as client:
                for _ in range(100):
                    if process.poll() is not None:
                        pytest.fail("Uvicorn exited during startup")
                    try:
                        response = client.get(f"http://127.0.0.1:{port}/officer/queue",
                                              params={"phone": "0240000001", "access_token": "synthetic-query-secret"})
                        break
                    except httpx.ConnectError:
                        time.sleep(0.1)
                else:
                    pytest.fail("Uvicorn did not start")
            assert response.status_code == 401
            for _ in range(100):
                if "401" in log_path.read_text(encoding="utf-8"):
                    break
                time.sleep(0.02)
        finally:
            process.terminate()
            process.wait()
    logs = log_path.read_text(encoding="utf-8")
    assert "0240000001" not in logs and "synthetic-query-secret" not in logs
    assert "401" in logs


@pytest.mark.parametrize("options", [[], ["--verify-only"]])
def test_cli_rejects_an_explicitly_selected_partial_database(tmp_path, monkeypatch, options):
    path = tmp_path / "backup.sqlite.partial"
    with closing(db.connect(str(path))):
        pass
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["migrations", str(path), *options])
    with pytest.raises(SystemExit):
        migrations.main()
    assert path.read_bytes() == before


@pytest.mark.parametrize(("action", "target"), [
    (sqlite3.SQLITE_CREATE_TABLE, "farmer_sms_contacts"),
    (sqlite3.SQLITE_INSERT, "schema_migrations"),
    (sqlite3.SQLITE_TRANSACTION, "COMMIT"),
])
def test_v6_rolls_back_when_first_ddl_ledger_or_commit_is_denied(tmp_path, action, target):
    from test_checkpoint4_migration import _historical_database

    path = tmp_path / "fault.sqlite"
    _historical_database(path, 5)
    before = path.read_bytes()
    with closing(sqlite3.connect(path)) as con:
        con.execute("PRAGMA foreign_keys=ON")
        denied = []

        def authorize(opcode, first, _second, _database, _trigger):
            if opcode == action and first == target:
                denied.append(first)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        con.set_authorizer(authorize)
        with pytest.raises(sqlite3.DatabaseError, match="not authorized"):
            migrations.upgrade_v6(con, str(path))
        assert denied == [target]
        assert not con.in_transaction
        assert migrations.validate_existing_ledger(con)[0] == 5
    assert path.read_bytes() == before
    (backup,) = tmp_path.glob("*.before-v6-*.sqlite")
    with closing(sqlite3.connect(backup)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert migrations.validate_existing_ledger(con)[0] == 5
    with closing(db.connect(str(path))) as con:
        assert migrations.validate_existing_ledger(con)[0] == 6


@pytest.mark.parametrize("version", [1, 6])
@pytest.mark.parametrize("replacement", ["missing", "inert"])
def test_case_revision_trigger_uses_version_specific_definition(tmp_path, version, replacement):
    from test_checkpoint4_migration import _historical_database

    path = tmp_path / "revision.sqlite"
    if version == 1:
        _historical_database(path, 1)
    else:
        db.connect(str(path)).close()
    with closing(sqlite3.connect(path)) as con, con:
        con.execute("DROP TRIGGER cases_content_revision")
        if replacement == "inert":
            con.execute("CREATE TRIGGER cases_content_revision AFTER UPDATE OF question ON cases "
                        "WHEN 0 BEGIN UPDATE cases SET revision=revision+1 WHERE id=NEW.id; END")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="cases_content_revision"):
        db.connect(str(path))
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", list(migrations.IMMUTABLE_TRIGGERS))
@pytest.mark.parametrize("replacement", ["missing", "inert"])
def test_verify_detects_every_immutable_trigger_defect(tmp_path, monkeypatch, name, replacement):
    path = tmp_path / "immutable.sqlite"
    with closing(db.connect(str(path))) as con, con:
        con.execute(f"DROP TRIGGER {name}")
        if replacement == "inert":
            con.execute(migrations.IMMUTABLE_TRIGGERS[name].replace(
                " BEGIN", " WHEN 0 BEGIN"))
    before = path.read_bytes()
    monkeypatch.setattr(sys, "argv", ["migrations", str(path), "--verify-only"])
    with pytest.raises(RuntimeError, match=name):
        migrations.main()
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


def test_verified_triggers_enforce_revision_and_append_only_evidence(tmp_path):
    path = tmp_path / "behavior.sqlite"
    with closing(db.connect(str(path))) as con, con:
        case_id = db.agent_upsert_case(con, status="pending_review", question="Original question")
        old_revision = db.get_case(con, case_id)["revision"]
        con.execute("UPDATE cases SET question='Changed question' WHERE id=?", (case_id,))
        assert db.get_case(con, case_id)["revision"] == old_revision + 1
        con.execute("INSERT INTO advisory_submissions VALUES (1, ?, 1, 'Officer', 'advice', 'note', 'approve', NULL, ?)",
                    (case_id, db.now()))
        con.execute("INSERT INTO safety_assessments VALUES (1, ?, 'snapshot', 'assessment', ?)", (case_id, db.now()))
        con.execute("INSERT INTO approvals VALUES (1, ?, 1, 1, 1, 'payload', 'fingerprint', 'fixture', ?)",
                    (case_id, db.now()))
        con.execute("INSERT INTO audit_events VALUES (1, ?, 'approval', 'officer', '{}', ?)", (case_id, db.now()))
        for table in ("advisory_submissions", "safety_assessments", "approvals", "audit_events"):
            statements = (f"UPDATE {table} SET id=id WHERE id=1",
                          f"DELETE FROM {table} WHERE id=1",
                          f"INSERT OR REPLACE INTO {table} SELECT * FROM {table} WHERE id=1")
            for statement in statements:
                with pytest.raises(sqlite3.IntegrityError, match="immutable evidence"):
                    con.execute(statement)


@pytest.mark.parametrize("route", ["acknowledgement", "delivery"])
def test_reconciliation_exception_is_private_and_rolls_back(route, monkeypatch, caplog):
    from agrireach import approval

    with closing(db.connect()) as con:
        case_id = db.agent_upsert_case(con, status="pending_review", question="Synthetic case")
        officer_token = db.add_officer(con, "Synthetic officer")
        private = f"+233240000001 {officer_token} synthetic-credential"
        with con:
            if route == "acknowledgement":
                con.execute("INSERT INTO acknowledgement_jobs VALUES (1, ?, 'unknown', NULL, 'simulated', ?)",
                            (case_id, db.now()))
            else:
                con.execute("INSERT INTO safety_assessments VALUES (1, ?, 'snapshot', 'assessment', ?)",
                            (case_id, db.now()))
                con.execute("INSERT INTO approvals VALUES (1, ?, 1, NULL, 1, 'payload', 'fingerprint', 'fixture', ?)",
                            (case_id, db.now()))
                con.execute("INSERT INTO delivery_jobs VALUES (1, 1, 'sms', 'hash', 'unknown', NULL, ?)", (db.now(),))

        def fail_audit(*args, **kwargs):
            raise sqlite3.OperationalError(private)

        monkeypatch.setattr(approval, "audit", fail_audit)
        with TestClient(app) as client:
            response = client.post(f"/officer/{route}-jobs/1/reconcile",
                                   headers={"Authorization": f"Bearer {officer_token}"},
                                   json={"accepted": True, "provider_evidence": private})
        assert response.status_code == 500
        assert response.json()["detail"] == "Could not record reconciliation"
        assert con.execute("SELECT count(*) FROM audit_events").fetchone()[0] == 0
        assert con.execute(f"SELECT state FROM {route}_jobs").fetchone()[0] == "unknown"
        assert "Could not record" in caplog.text
        assert all(secret not in response.text + caplog.text for secret in private.split())


@pytest.mark.parametrize("level", [logging.INFO, logging.DEBUG])
def test_transport_logging_is_safe_across_concurrent_worker_threads(monkeypatch, caplog, level):
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote_plus

    from httpcore._trace import Trace

    keys = ("synthetic-ASCII+/= key", "synthetic-é-credential")
    caplog.set_level(level)
    monkeypatch.setenv("MNOTIFY_SMS_MODE", "live")

    def exchange(worker):
        def provider(request):
            wire_key = request.url.params["key"]

            def echo_headers():
                log = logging.getLogger("httpcore.http11")
                with Trace("receive_response_headers", log) as trace:
                    trace.return_value = (b"HTTP/1.1", 401, b"Unauthorized",
                                          [(b"x-raw", wire_key.encode()),
                                           (b"x-escaped", quote_plus(wire_key).encode())])
                try:
                    raise httpx.ReadError(wire_key, request=request)
                except httpx.ReadError:
                    log.log(level, "receive_response_headers.failed %r", wire_key.encode(), exc_info=True)
                    raise

            return worker.submit(echo_headers).result()

        with httpx.Client(transport=httpx.MockTransport(provider)) as client:
            return mnotify.transmit("+233240000001", "Synthetic", client=client)

    # A context-local config enables simultaneous, independent credentials.
    from contextvars import ContextVar

    configured_key = ContextVar("configured_key")
    monkeypatch.setattr(mnotify, "live_config", lambda: mnotify.LiveConfig(configured_key.get(), "AgriReach"))

    def run(key, worker):
        configured_key.set(key)
        return exchange(worker)

    with ThreadPoolExecutor(max_workers=2) as senders, ThreadPoolExecutor(max_workers=2) as transport:
        replies = list(senders.map(lambda key: run(key, transport), keys))
    assert all(result.outcome == "unknown" for result in replies)
    assert "receive_response_headers.failed" in caplog.text
    for key in keys:
        assert all(form not in caplog.text for form in (key, quote_plus(key), repr(key.encode())[2:-1]))


def test_interrupted_backup_is_isolated_and_retry_preserves_it(tmp_path, monkeypatch):
    from test_checkpoint4_migration import _historical_database

    path = tmp_path / "interrupted.sqlite"
    _historical_database(path, 5)
    before = path.read_bytes()
    child = """
import os
import sqlite3
import sys
from agrireach import db

class InterruptedBackup(sqlite3.Connection):
    def backup(self, target):
        super().backup(target)
        os._exit(42)  # Full bytes copied, verification/publication did not run.

connect = sqlite3.connect
def intercept(path, *args, **kwargs):
    if kwargs.get('uri') and str(path).endswith('?mode=ro'):
        kwargs['factory'] = InterruptedBackup
    return connect(path, *args, **kwargs)

sqlite3.connect = intercept
db.connect(sys.argv[1])
"""
    result = subprocess.run([sys.executable, "-c", child, str(path)], env=os.environ)
    assert result.returncode == 42
    assert path.read_bytes() == before
    assert list(tmp_path.glob("*.before-v6-*.sqlite")) == []
    (partial,) = tmp_path.glob(".agrireach-backup-*/*.sqlite.partial")
    interrupted = partial.read_bytes()
    monkeypatch.setattr(sys, "argv", ["migrations", str(partial)])
    with pytest.raises(SystemExit):
        migrations.main()
    with closing(db.connect(str(path))) as con:
        assert migrations.validate_existing_ledger(con)[0] == 6
    (backup,) = tmp_path.glob("*.before-v6-*.sqlite")
    with closing(sqlite3.connect(backup)) as con:
        assert migrations.validate_existing_ledger(con)[0] == 5
    assert partial.read_bytes() == interrupted
