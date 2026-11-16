"""Public feedback and unauthenticated Streamlit rendering contracts."""
from pathlib import Path
import httpx
import pytest
from agrireach.ui_feedback import auth_headers, feedback


def test_empty_credentials_never_make_a_bearer_header():
    assert auth_headers("") == auth_headers("  ") == {}
    assert auth_headers(" synthetic ") == {"Authorization": "Bearer synthetic"}


@pytest.mark.parametrize("status,outcome", [(422,"review_required"), (422,"safety_blocked"),
    (503,"assessment_unavailable"), (409,"acknowledgement_required"), (409,"conflict")])
def test_public_messages_do_not_echo_internal_exceptions(status, outcome):
    _, message = feedback(status, {"detail": {"outcome": outcome, "reason": "KeyError LLM_BASE_URL", "model": "internal-model"}})
    assert "KeyError" not in message and "LLM_BASE_URL" not in message
    assert "internal-model" not in message


def test_streamlit_signed_out_renders_farmer_page_only(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    # AppTest is not a REPL. Avoid Streamlit's inspect.stack()/Windows path walk
    # for its first-use warning; this test checks the rendered workflow.
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    calls = []
    def backend(method, url, **kwargs):
        calls.append((url, kwargs.get("headers")))
        assert not kwargs.get("headers")
        assert url.endswith("/health")
        return httpx.Response(200, json={"draft_mode": "stub"})
    monkeypatch.setattr(httpx, "request", backend)
    # Cold Streamlit imports on the pilot PC can exceed AppTest's three-second default.
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/agrireach/ui.py"), default_timeout=15).run()
    assert not app.exception
    assert len(app.tabs) == 0
    assert any(item.value == "Advice for your next step" for item in app.title)
    assert not any(item.label == "Officer sign in token" for item in app.text_input)
    assert len(calls) == 1


def test_officer_form_authentication_and_signout_clear_private_review(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, 'is_repl', lambda: False)
    valid = 'synthetic-officer-credential'
    seen = []

    def backend(method, url, **kwargs):
        seen.append(kwargs.get('headers'))
        if kwargs.get('headers') != auth_headers(valid):
            return httpx.Response(401, json={'detail': 'officer sign-in required'})
        assert url.endswith(('/officer/queue', '/officer/cases'))
        return httpx.Response(200, json=[])

    monkeypatch.setattr(httpx, 'request', backend)
    app = AppTest.from_string('from agrireach.ui import officer_screen\nofficer_screen()', default_timeout=20).run()
    assert not seen  # A blank form does not issue an officer request.
    app.text_input(key='officer_token_input').set_value('invalid')
    app.button[0].click().run()
    assert 'officer_token' not in app.session_state
    assert any('valid officer token' in item.value for item in app.info)
    app.text_input(key='officer_token_input').set_value('  ' + valid + '  ')
    app.button[0].click().run()
    assert not app.exception
    assert app.session_state['officer_token'] == valid
    assert any('No cases waiting' in item.value for item in app.info)
    app.session_state['challenge12'] = {'token': 'synthetic-challenge'}
    app.session_state['farmer_case_id'] = 9
    app.button(key='officer_signout').click().run()
    assert not app.exception
    assert 'officer_token' not in app.session_state
    assert 'challenge12' not in app.session_state
    assert app.session_state['farmer_case_id'] == 9
    assert any(item.label == 'Officer sign in token' for item in app.text_input)
