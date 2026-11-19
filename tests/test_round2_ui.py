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


def test_streamlit_signed_out_renders_all_tabs(monkeypatch):
    from streamlit.testing.v1 import AppTest
    calls = []
    def backend(method, url, **kwargs):
        calls.append((url, kwargs.get("headers")))
        assert not kwargs.get("headers")
        assert url.endswith("/health")
        return httpx.Response(200, json={"draft_mode": "stub"})
    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/agrireach/ui.py")).run()
    assert not app.exception
    assert len(app.tabs) == 3
    assert len(calls) == 1


def _ui_text(app):
    parts = []
    for collection in (app.markdown, app.info, app.success, app.warning, app.error, app.caption, app.text, app.title):
        for widget in collection:
            value = getattr(widget, "value", None)
            if value:
                parts.append(str(value))
    for collection in (app.button, app.text_input, app.text_area, app.number_input):
        for widget in collection:
            label = getattr(widget, "label", None)
            if label:
                parts.append(str(label))
    return "\n".join(parts)


def test_farmer_tab_has_no_case_number_flow(monkeypatch):
    from streamlit.testing.v1 import AppTest
    def backend(method, url, **kwargs):
        assert url.endswith("/health")
        return httpx.Response(200, json={"draft_mode": "stub"})
    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/agrireach/ui.py")).run()
    assert not app.exception
    text = _ui_text(app)
    assert "Check case number" not in text
    assert "Check answer" not in text
    labels = [w.label for w in app.number_input]
    assert "Check case number" not in labels
    buttons = [w.label for w in app.button]
    assert "Check answer" not in buttons
    assert "Officer email" in [w.label for w in app.text_input]
    assert "Officer password" in [w.label for w in app.text_input]
    assert "Officer sign in token" not in text


def test_farmer_pending_state_updates_without_showing_a_case_number(monkeypatch):
    from streamlit.testing.v1 import AppTest
    pending = {"case_id": 7, "status": "pending_review", "answer": None, "message": "An officer is reviewing this."}
    released = {"case_id": 7, "status": "released", "answer": "Harvest soybean when 9 out of 10 pods are brown.", "auto_released": False}
    state = {"pending": True}

    def backend(method, url, **kwargs):
        if url.endswith("/health"):
            return httpx.Response(200, json={"draft_mode": "stub"})
        if url.endswith("/ask"):
            return httpx.Response(200, json=pending)
        if url.endswith("/farmer/cases/7"):
            return httpx.Response(200, json=pending if state["pending"] else released)
        raise AssertionError(url)

    monkeypatch.setattr(httpx, "request", backend)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "src/agrireach/ui.py")).run()
    assert not app.exception
    next(b for b in app.button if b.label == "Send").click().run()
    assert not app.exception
    text = _ui_text(app)
    assert "An officer is reviewing this." in text
    assert "Case 7" not in text
    assert "Check case number" not in text
    state["pending"] = False
    app.run()
    text = _ui_text(app)
    assert "Harvest soybean when 9 out of 10 pods are brown." in text
    assert "Case 7" not in text


def test_farmer_rejected_and_needs_info_messages():
    from agrireach.ui import FARMER_NEEDS_INFO, FARMER_REJECTED, farmer_waiting_message
    assert "case" not in farmer_waiting_message({"status": "rejected"}).lower()
    assert farmer_waiting_message({"status": "rejected"}) == FARMER_REJECTED
    assert farmer_waiting_message({"status": "needs_info"}) == FARMER_NEEDS_INFO
