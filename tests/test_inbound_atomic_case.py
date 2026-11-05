"""Crash boundaries use committed SQLite evidence; all farmers are synthetic."""
import asyncio
import sqlite3

import pytest

from agrireach import agent, db


def claimed(con):
    db.enqueue_inbound(con, 'sms', 'atomic-1', {'text': 'maize'}, sender_id='+233000000001')
    lease, _ = db.claim_inbound(con, 'sms', 'atomic-1')
    return dict(channel='sms', message_id='atomic-1', lease_id=lease)


def test_case_and_link_survive_worker_restart_without_replay():
    con = db.connect()
    claim = claimed(con)
    cid = db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    con.close()  # crash before worker completion
    con = db.connect()
    db.reconcile_interrupted_inbound(con, older_than='9999')
    row = con.execute('SELECT * FROM channel_inbox').fetchone()
    assert (row['state'], row['case_id']) == ('uncertain', cid)
    assert db.claim_inbound(con, 'sms', 'atomic-1') is None
    assert con.execute('SELECT count(*) FROM cases').fetchone()[0] == 1


def test_link_database_failure_rolls_back_case():
    con = db.connect()
    claim = claimed(con)
    con.execute("CREATE TRIGGER fail_link BEFORE UPDATE OF case_id ON channel_inbox BEGIN SELECT RAISE(ABORT,'injected disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match='injected'):
        db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    assert con.execute('SELECT count(*) FROM cases').fetchone()[0] == 0
    assert con.execute('SELECT case_id FROM channel_inbox').fetchone()[0] is None


def test_duplicate_create_and_late_stop_cannot_recreate_contact():
    con = db.connect()
    claim = claimed(con)
    cid = db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    with pytest.raises(db.GateError, match='already has a case'):
        db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    other = db.connect()
    db.forget_sender(other, 'sms', '+233000000001')
    for save in (db.save_contact, db.queue_with_contact):
        with pytest.raises(db.GateError, match='revoked'):
            save(con, cid, channel='sms', sender_id='+233000000001', inbound_claim=claim)
    assert db.get_contact(con, cid) is None
    with pytest.raises(db.GateError, match='revoked'):
        db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)


def test_failure_completion_preserves_atomic_case_evidence():
    con = db.connect()
    claim = claimed(con)
    cid = db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    assert db.finish_inbound(con, 'sms', 'atomic-1', claim['lease_id'], 'uncertain', reason='crash')
    assert con.execute('SELECT case_id FROM channel_inbox').fetchone()[0] == cid


def test_real_langgraph_mcp_creation_links_claim():
    con = db.connect()
    claim = claimed(con)
    result = asyncio.run(agent.run('maize', use_fetch=False, queue=False, inbound_claim=claim))
    assert con.execute('SELECT case_id FROM channel_inbox').fetchone()[0] == result['case_id']
    assert db.get_case(con, result['case_id'])['status'] == 'draft'
