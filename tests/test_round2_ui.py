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
    assert any(item.value == "Ask about your crop" for item in app.title)
    assert not any(item.label == "Officer sign in token" for item in app.text_input)
    assert len(calls) == 1


def _officer_backend(valid):
    calls = []

    def backend(method, url, **kwargs):
        calls.append((method, url, kwargs.get("headers"), kwargs.get("json")))
        if url.endswith("/officer/auth/login"):
            body = kwargs.get("json") or {}
            if body.get("password") != "correct-password-value":
                return httpx.Response(401, json={"detail": "Invalid email or password."})
            return httpx.Response(200, json={
                "session_token": valid, "token_type": "Bearer", "expires_at": "2026-11-17T06:00:00Z",
                "officer": "Ada", "email": body.get("email"),
            })
        if url.endswith("/officer/auth/logout"):
            assert kwargs.get("headers") == auth_headers(valid)
            return httpx.Response(200, json={"revoked": True})
        if kwargs.get("headers") != auth_headers(valid):
            return httpx.Response(401, json={"detail": "officer sign-in required"})
        if url.endswith("/officer/auth/me"):
            return httpx.Response(200, json={
                "officer": "Ada", "email": "ada@example.com", "expires_at": "2026-11-17T06:00:00Z", "kind": "session",
            })
        if url.endswith(("/officer/queue", "/officer/cases")):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "not found"})

    return calls, backend


def _rendered(app):
    parts = [item.value for item in list(app.info) + list(app.caption) + list(app.markdown)
             + list(app.error) + list(app.success) + list(app.warning)]
    return "\n".join(str(part) for part in parts)


def test_officer_email_sign_in_logout_and_hidden_session(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    valid = "synthetic-officer-session"
    calls, backend = _officer_backend(valid)
    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_string("from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20).run()
    assert not calls  # A blank form does not issue an officer request.
    app.text_input(key="officer_email_input").set_value("ada@example.com")
    app.text_input(key="officer_password_input").set_value("wrong-password-value")
    app.button(key="officer_email_submit").click().run()
    assert "officer_token" not in app.session_state
    assert "Invalid email or password." in _rendered(app)
    assert "wrong-password-value" not in _rendered(app)
    assert "wrong-password-value" not in " ".join(str(value) for value in app.session_state.values())
    app.text_input(key="officer_email_input").set_value("ada@example.com")
    app.text_input(key="officer_password_input").set_value("correct-password-value")
    app.button(key="officer_email_submit").click().run()
    assert not app.exception
    assert app.session_state["officer_token"] == valid
    assert valid not in _rendered(app)
    assert "correct-password-value" not in _rendered(app)
    assert any("No questions are waiting" in item.value for item in app.info)
    app.session_state["challenge12"] = {"token": "synthetic-challenge"}
    app.session_state["farmer_case_id"] = 9
    app.button(key="officer_signout").click().run()
    assert not app.exception
    assert "officer_token" not in app.session_state
    assert "challenge12" not in app.session_state
    assert app.session_state["farmer_case_id"] == 9
    assert any(call[0] == "POST" and call[1].endswith("/officer/auth/logout") for call in calls)
    assert "Signed out" in _rendered(app)
    assert any(item.label == "Email" for item in app.text_input)
    assert not any(item.label == "Officer sign in token" for item in app.text_input)


def test_expired_officer_session_returns_to_sign_in(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    monkeypatch.setattr(httpx, "request", lambda *args, **kwargs: httpx.Response(
        401, json={"detail": "officer sign-in required"}))
    app = AppTest.from_string("from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20)
    app.session_state["officer_token"] = "expired-session"
    app.run()
    assert not app.exception
    assert "officer_token" not in app.session_state
    assert "Your session has ended" in _rendered(app)
    assert "expired-session" not in _rendered(app)


def test_emergency_question_is_labelled_before_it_is_opened(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    emergency = {
        "id": 3, "question": "My child drank gramoxone", "status": "pending_review", "priority": "urgent",
        "urgent_reasons": ["EMERGENCY: chemical swallowed, inhaled or splashed."],
        "created_at": "2026-11-16T12:00:00Z", "revision": 1, "sources": [], "draft": "",
    }

    def backend(method, url, **kwargs):
        if url.endswith("/officer/auth/me"):
            return httpx.Response(200, json={"officer": "Ada", "email": "ada@example.com",
                                              "expires_at": "2026-11-17T06:00:00Z", "kind": "session"})
        if url.endswith("/officer/queue"):
            return httpx.Response(200, json=[emergency])
        if url.endswith("/officer/cases"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={})

    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_string("from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=20)
    app.session_state["officer_token"] = "synthetic-officer-session"
    app.run()
    assert not app.exception
    labels = [button.label for button in app.button]
    assert any(label.startswith("Emergency ·") and "gramoxone" in label for label in labels)
    assert "EMERGENCY: chemical swallowed" in _rendered(app)


def test_opened_case_shows_recorded_tools_and_the_rejected_model_label(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    marker = "[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]"
    detail = {
        "id": 4, "question": "When should I harvest soybean in Tamale?", "status": "pending_review",
        "priority": "routine", "urgent_reasons": [], "created_at": "2026-11-16T12:00:00Z", "revision": 1,
        "sources": ["MOFA-MAIZE:p4", "MOFA-MAIZE:p4"],
        "draft": marker + "\nHarvest when most pods are brown [MOFA-MAIZE:p4].",
        "farmer_text": "", "farmer_draft": None, "crop": "soybean", "region": "Northern",
        "generation": {
            "state": "model_draft_rejected_source_fallback", "model_used": True, "attempted_calls": 2,
            "label": "SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT: verbatim passages shown (2 model calls, cost unknown)",
            "drafting_usage": {"attempted_calls": 2, "prompt_tokens": 80, "completion_tokens": 20,
                               "cost_usd": None, "cost_complete": False},
            "models": ["example-model"],
        },
        "tool_evidence": {"mcp_recorded": True, "timeline": [], "mcp_runs": [{"calls": [
            {"seq": 1, "server": "agrireach", "tool": "search_guidance", "ok": True, "ms": 18},
            {"seq": 2, "server": "fetch", "tool": "fetch", "ok": False, "error": "timeout", "ms": 20000},
        ]}]},
        "log": [],
    }
    queued = {key: value for key, value in detail.items() if key not in {"tool_evidence", "log", "generation"}}

    def backend(method, url, **kwargs):
        if url.endswith("/officer/auth/me"):
            return httpx.Response(200, json={"officer": "Ada", "email": "ada@example.com",
                                              "expires_at": "2026-11-17T06:00:00Z", "kind": "session"})
        if url.endswith("/officer/queue"):
            return httpx.Response(200, json=[queued])
        if url.endswith("/delivery-jobs"):
            return httpx.Response(200, json=[])
        if url.endswith("/acknowledgement"):
            return httpx.Response(200, json={"status": "not_requested", "simulated": False,
                                              "message": "No confirmation SMS was sent.", "phone_masked": None})
        if url.endswith("/voice"):
            return httpx.Response(200, json={"has_audio": False})
        if url.endswith("/voice-preview"):
            return httpx.Response(200, json={"enabled": False})
        if url.rstrip("/").endswith("/officer/cases/4") and method == "GET":
            return httpx.Response(200, json=detail)
        if url.endswith("/officer/cases"):
            return httpx.Response(200, json=[])
        return httpx.Response(404, json={"detail": "not found"})

    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_string("from agrireach.ui import officer_screen\nofficer_screen()", default_timeout=30)
    app.session_state["officer_token"] = "synthetic-officer-session"
    app.run()
    app.button(key="open4").click().run()
    rendered = _rendered(app)
    assert not app.exception
    assert any(getattr(item, "label", None) == "Audit trail" for item in app.expander)
    assert "Source draft from 1 guidance source after an AI draft did not pass checks" in rendered
    assert "Drafted by AI" not in rendered
    assert "Passed safety and citation checks" not in rendered
    assert "SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT" in rendered
    assert "No language model was used" not in rendered
    assert "cost unknown" in rendered
    assert "search_guidance" in rendered
    assert "timeout" in rendered
    assert "20000 ms" in rendered
    assert "example-model" in rendered
    assert rendered.count("Cited source") <= 2 or "MOFA-MAIZE:p4" not in rendered

