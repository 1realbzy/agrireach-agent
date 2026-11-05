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


def test_stop_serialized_after_contact_removes_it():
    con = db.connect()
    claim = claimed(con)
    cid = db.agent_upsert_case(con, status='draft', question='maize', inbound_claim=claim)
    db.queue_with_contact(con, cid, channel='sms', sender_id='+233000000001', inbound_claim=claim)
    db.forget_sender(db.connect(), 'sms', '+233000000001')
    assert db.get_contact(con, cid)['sender_id'] == db.OPTED_OUT
    with pytest.raises(db.GateError, match='revoked'):
        db.queue_with_contact(con, cid, channel='sms', sender_id='+233000000001', inbound_claim=claim)


def test_worker_crash_after_mcp_commit_keeps_link_and_duplicate_does_not_replay(monkeypatch):
    from agrireach.channels import sms
    from agrireach.channels.base import SendResult
    con = db.connect()
    item = {'message_id': 'crash-mcp', 'from': '+233000000001', 'text': 'maize'}
    db.enqueue_inbound(con, 'sms', item['message_id'], item, sender_id=item['from'])
    original = agent.Tools.call
    async def crash_after_create(self, name, args):
        result = await original(self, name, args)
        if name == 'create_or_update_case' and not args.get('case_id'):
            raise TimeoutError('injected crash after MCP commit')
        return result
    monkeypatch.setattr(agent.Tools, 'call', crash_after_create)
    monkeypatch.setattr(sms.SmsChannel, 'send', lambda *args: SendResult(True, 'synthetic'))
    cfg = sms.Config('sandbox', 'unused', 'x' * 24)
    with pytest.raises(Exception):
        asyncio.run(sms.process_durable(cfg, item))
    row = con.execute("SELECT * FROM channel_inbox WHERE message_id='crash-mcp'").fetchone()
    assert row['state'] == 'uncertain' and row['case_id'] is not None
    assert db.get_case(con, row['case_id'])['status'] == 'draft'
    asyncio.run(sms.process_durable(cfg, item))
    assert con.execute('SELECT count(*) FROM cases').fetchone()[0] == 1
    assert con.execute('SELECT count(*) FROM channel_contacts').fetchone()[0] == 0
