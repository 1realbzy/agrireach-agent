"""Email sign-in is a layout only until the officer authentication API exists."""
import httpx
from streamlit import env_util
from streamlit.testing.v1 import AppTest


def test_email_sign_in_does_not_call_the_api_or_keep_the_password(monkeypatch):
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: seen.append(args) or httpx.Response(500))
    app = AppTest.from_string(
        "from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20
    ).run()
    app.text_input(key="officer_email_pending").set_value("officer@example.com")
    app.text_input(key="officer_password_pending_input").set_value("not-a-real-secret")
    app.button(key="officer_password_pending_submit").click().run()
    assert not seen
    assert "officer_token" not in app.session_state
    assert any("not available yet" in item.value and "No password was stored" in item.value for item in app.info)
    app.run()
    stored = " ".join(str(value) for value in app.session_state.values())
    assert "not-a-real-secret" not in stored
    assert "officer@example.com" not in stored
