"""Offline two-participant scenario through FastAPI, real LangGraph/MCP and SQLite."""
from fastapi.testclient import TestClient
from agrireach import api, db
from agrireach.channels import service, simulator

TEXT = 'Consult your local AEA before choosing or applying a pesticide.'


def test_offline_pilot_approval_and_negative_paths(monkeypatch):
    monkeypatch.setenv('AGRIREACH_CONSENT', '1')
    client = TestClient(api.app)
    con = db.connect()
    token = db.add_officer(con, 'Synthetic Pilot Officer')
    auth = {'Authorization': 'Bearer ' + token}
    sender = 'sim:pilot-1'
    def submit(text):
        response = client.post('/channels/simulator/inbound', data={'sender': sender, 'text': text})
        assert response.status_code == 200
        return response.json()
    assert submit('How do I reach an extension officer about maize in Tamale?')['status'] == 'awaiting_consent'
    cid = submit('YES')['case_id']
    assert client.get('/officer/queue').status_code == 401
    assert client.get('/officer/queue', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    assert len(simulator.SimulatorChannel().messages(sender)) == 2
    def decision(text):
        return client.post(f'/officer/cases/{cid}/decision', headers=auth, json={
            'decision': 'approve', 'farmer_text': text, 'confirmed': True,
            'expected_revision': db.get_case(con, cid)['revision']})
    assert decision('Spray pesticide twice every week.').status_code == 422
    assert len(simulator.SimulatorChannel().messages(sender)) == 2
    response = decision(TEXT)
    assert response.status_code == 200, response.json()
    assert response.json()['delivery']['ok']
    assert simulator.SimulatorChannel().messages(sender)[-1]['text'] == TEXT
    assert service.deliver(con, cid, {'simulator': simulator.SimulatorChannel()})['ok']
    assert len(simulator.SimulatorChannel().messages(sender)) == 3
    assert con.execute('SELECT count(*) FROM approvals WHERE case_id=?', (cid,)).fetchone()[0] == 1
    # Another case can be rejected; no advisory delivery follows.
    cid2 = submit('How do I reach an extension officer about maize?')['case_id']
    rejected = client.post(f'/officer/cases/{cid2}/decision', headers=auth, json={
        'decision': 'reject', 'note': 'Synthetic pilot rejection',
        'expected_revision': db.get_case(con, cid2)['revision']})
    assert rejected.status_code == 200
    assert not con.execute("SELECT 1 FROM channel_deliveries WHERE case_id=? AND kind='answer'", (cid2,)).fetchone()
    assert submit('STOP')['status'] == 'forgotten'
    assert db.get_contact(con, cid)['sender_id'] == db.OPTED_OUT
    assert not service.deliver(con, cid, {'simulator': simulator.SimulatorChannel()})['ok']
