"""Officer portal email/password sign-in calls the login API and keeps the session server-side. Offline."""
from pathlib import Path

import httpx
from agrireach.ui_feedback import auth_headers


def test_email_signin_stores_session_and_signout_revokes_it(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, 'is_repl', lambda: False)
    session = 'synthetic-session-token'
    calls = []

    def backend(method, url, **kwargs):
        calls.append((method, url.rsplit('/', 3)[-3:], kwargs.get('json')))
        if url.endswith('/officer/auth/login'):
            if kwargs['json'] == {'email': 'ama@example.org', 'password': 'synthetic-Passw0rd'}:
                return httpx.Response(200, json={'session_token': session, 'token_type': 'Bearer',
                                                 'expires_at': '2026-11-17T08:00:00+00:00',
                                                 'officer': 'Ama Mensah', 'email': 'ama@example.org'})
            return httpx.Response(401, json={'detail': 'Invalid email or password.'})
        if url.endswith('/officer/auth/logout'):
            assert kwargs.get('headers') == auth_headers(session)
            return httpx.Response(200, json={'revoked': True})
        if kwargs.get('headers') != auth_headers(session):
            return httpx.Response(401, json={'detail': 'officer sign-in required'})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, 'request', backend)
    app = AppTest.from_string('from agrireach.ui import officer_screen\nofficer_screen()', default_timeout=20).run()
    assert not calls
    app.text_input(key='officer_email_input').set_value('ama@example.org')
    app.text_input(key='officer_password_input').set_value('wrong-password')
    app.button(key='officer_email_submit').click().run()
    assert 'officer_token' not in app.session_state
    assert any('Invalid email or password.' in item.value for item in app.error)
    app.text_input(key='officer_email_input').set_value('ama@example.org')
    app.text_input(key='officer_password_input').set_value('synthetic-Passw0rd')
    app.button(key='officer_email_submit').click().run()
    assert not app.exception
    assert app.session_state['officer_token'] == session
    assert not any(session in str(getattr(item, 'value', '')) for item in app.text_input)
    app.button(key='officer_signout').click().run()
    assert 'officer_token' not in app.session_state
    assert any(url[-2:] == ['auth', 'logout'] for _, url, _ in calls)
