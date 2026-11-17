"""Officer sign-in stores neither the password nor the session token in the page."""
import httpx
from streamlit import env_util
from streamlit.testing.v1 import AppTest


def test_failed_sign_in_does_not_keep_the_password_or_call_protected_routes(monkeypatch):
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []

    def backend(method, url, **kwargs):
        seen.append((method, url, kwargs.get("json")))
        assert url.endswith("/officer/auth/login")
        return httpx.Response(401, json={"detail": "Invalid email or password."})

    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_string(
        "from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20
    ).run()
    app.text_input(key="officer_email_input").set_value("officer@example.com")
    app.text_input(key="officer_password_input").set_value("not-a-real-secret")
    app.button(key="officer_email_submit").click().run()
    assert seen and seen[0][0] == "POST"
    assert "officer_token" not in app.session_state
    app.run()
    stored = " ".join(str(value) for value in app.session_state.values())
    rendered = " ".join(item.value for item in list(app.error) + list(app.info) + list(app.caption))
    assert "not-a-real-secret" not in stored
    assert "not-a-real-secret" not in rendered
    assert "Invalid email or password." in rendered


def test_officer_session_is_not_given_to_the_browser_component(monkeypatch):
    from agrireach import ui

    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []

    def bridge(role, **kwargs):
        seen.append((role, kwargs.get("value"), kwargs.get("forget")))
        return {"token": "browser-stored-secret"}

    monkeypatch.setattr(ui, "tab_state", bridge)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no request")))
    app = AppTest.from_string(
        "from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20
    ).run()
    assert not app.exception
    assert "officer_token" not in app.session_state
    assert seen
    assert all(role == "officer" and value is None and forget is True for role, value, forget in seen)
    assert "browser-stored-secret" not in " ".join(str(item.value) for item in app.markdown)
