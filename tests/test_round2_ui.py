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
    assert len(app.tabs) == 3
    assert len(calls) == 1
