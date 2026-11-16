"""Refreshing may restore a tab credential, but never bypass API authorization."""

import httpx
from streamlit.testing.v1 import AppTest

from agrireach.ui_feedback import auth_headers


def test_officer_refresh_requires_successful_api_authorization(monkeypatch):
    from agrireach import ui

    valid = 'synthetic-officer-tab-token'
    requests = []
    monkeypatch.setattr(ui, 'tab_state', lambda role, **kwargs:
                        {'token': valid} if not kwargs.get('value') and not kwargs.get('forget') else None)

    def backend(method, url, **kwargs):
        requests.append((url, kwargs.get('headers')))
        assert kwargs['headers'] == auth_headers(valid)
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, 'request', backend)
    app = AppTest.from_string('from agrireach.ui import officer_screen\nofficer_screen()').run(timeout=10)
    assert not app.exception
    assert app.session_state['officer_token'] == valid
    assert requests


def test_revoked_officer_token_is_not_restored(monkeypatch):
    from agrireach import ui

    monkeypatch.setattr(ui, 'tab_state', lambda role, **kwargs:
                        {'token': 'revoked'} if not kwargs.get('forget') else None)
    monkeypatch.setattr(httpx, 'request', lambda *args, **kwargs:
                        httpx.Response(401, json={'detail': 'invalid'}))
    app = AppTest.from_string('from agrireach.ui import officer_screen\nofficer_screen()').run()
    assert not app.exception
    assert 'officer_token' not in app.session_state
    assert app.session_state['officer_tab_forgotten'] is True


def test_farmer_refresh_uses_case_header_and_checks_code(monkeypatch):
    from agrireach import ui

    stored = {'case_id': 7, 'token': 'synthetic-farmer-code', 'question': 'When should I harvest soybean?'}
    monkeypatch.setattr(ui, 'tab_state', lambda role, **kwargs:
                        stored if not kwargs.get('value') and not kwargs.get('forget') else None)

    def backend(method, url, **kwargs):
        assert url.endswith('/farmer/cases/7')
        assert kwargs['headers'] == {'X-Case-Access-Token': stored['token']}
        return httpx.Response(200, json={'status': 'pending_review', 'answer': None})

    monkeypatch.setattr(httpx, 'request', backend)
    app = AppTest.from_string('from agrireach.ui import farmer_screen\nfarmer_screen()').run()
    assert not app.exception
    assert app.session_state['farmer_case_id'] == 7
    assert app.session_state['farmer_case_token'] == stored['token']


def test_invalid_farmer_code_cannot_restore_question(monkeypatch):
    from agrireach import ui

    monkeypatch.setattr(ui, 'tab_state', lambda role, **kwargs:
                        {'case_id': 7, 'token': 'invalid'} if not kwargs.get('forget') else None)
    monkeypatch.setattr(httpx, 'request', lambda *args, **kwargs:
                        httpx.Response(404, json={}))
    app = AppTest.from_string('from agrireach.ui import farmer_screen\nfarmer_screen()').run()
    assert not app.exception
    assert 'farmer_case_token' not in app.session_state
    assert app.session_state['farmer_tab_forgotten'] is True
