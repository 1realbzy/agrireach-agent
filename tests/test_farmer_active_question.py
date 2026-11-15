"""Farmer active-question card: no re-entry of the case number and code within one tab.

The private code stays in Streamlit session state and is sent as a header on every
check, so the API still authorizes each request.
"""
import httpx
from streamlit import env_util
from streamlit.testing.v1 import AppTest

SCRIPT = "from agrireach.ui import farmer_screen\nfarmer_screen()"


def _backend(monkeypatch, views):
    seen = []

    def backend(method, url, **kwargs):
        seen.append((method, url, kwargs.get("headers") or {}, kwargs.get("json")))
        if url.endswith("/ask") and method == "POST":
            return httpx.Response(200, json={"case_id": 8, "access_token": "secret-code-8", "status": "pending_review",
                                             "clarification": "", "message": "Your question has been received."})
        if "/farmer/cases/" in url and method == "GET":
            cid = int(url.rsplit("/", 1)[1])
            token = (kwargs.get("headers") or {}).get("X-Case-Access-Token")
            if (cid, token) in views:
                return httpx.Response(200, json=views[(cid, token)])
            return httpx.Response(404, json={"detail": "Case not found"})
        return httpx.Response(200, json={"draft_mode": "stub"})

    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    monkeypatch.setattr(httpx, "request", backend)
    return seen


def _rendered(app):
    parts = [m.value for m in app.markdown] + [c.value for c in app.caption] + [i.value for i in app.info]
    parts += [s.value for s in app.success] + [e.value for e in app.error]
    return "\n".join(str(p) for p in parts)


def _submit(app):
    app.text_area(key="farmer_question").set_value("When should I harvest soybean in Tamale?")
    app.button(key="farmer_submit_button").click().run()
    return app


def test_check_for_updates_reuses_the_session_code_without_re_entry(monkeypatch):
    views = {(8, "secret-code-8"): {"case_id": 8, "status": "pending_review", "answer": None}}
    seen = _backend(monkeypatch, views)
    app = _submit(AppTest.from_string(SCRIPT, default_timeout=20).run())
    assert "Question 8" in _rendered(app)
    assert "farmer_refresh" in [b.key for b in app.button]
    app.button(key="farmer_refresh").click().run()
    gets = [call for call in seen if call[0] == "GET" and "/farmer/cases/" in call[1]]
    assert gets and gets[-1][1].endswith("/farmer/cases/8")
    assert gets[-1][2] == {"X-Case-Access-Token": "secret-code-8"}
    assert "secret-code-8" not in gets[-1][1]  # never in the URL
    assert any("Waiting for officer review" in item.value for item in app.info)
    assert "secret-code-8" not in _rendered(app)

    views[(8, "secret-code-8")] = {"case_id": 8, "status": "released", "answer": "Harvest when 9 out of 10 pods are mature."}
    app.button(key="farmer_refresh").click().run()
    assert any("9 out of 10 pods" in item.value for item in app.success)


def test_refresh_still_depends_on_server_authorization(monkeypatch):
    seen = _backend(monkeypatch, {})  # the server no longer accepts this code
    app = _submit(AppTest.from_string(SCRIPT, default_timeout=20).run())
    app.button(key="farmer_refresh").click().run()
    assert any("could not find your question" in item.value for item in app.error)
    assert not app.success
    assert any(call[0] == "GET" for call in seen)


def test_forget_clears_the_code_from_the_session(monkeypatch):
    _backend(monkeypatch, {(8, "secret-code-8"): {"case_id": 8, "status": "pending_review", "answer": None}})
    app = _submit(AppTest.from_string(SCRIPT, default_timeout=20).run())
    app.button(key="farmer_forget").click().run()
    assert "farmer_refresh" not in [b.key for b in app.button]
    assert app.session_state["farmer_lookup_token"] == ""
    for key in ("farmer_case_id", "farmer_case_token", "farmer_active_question"):
        assert key not in app.session_state


def test_manual_lookup_becomes_the_active_question(monkeypatch):
    views = {(5, "code-5"): {"case_id": 5, "status": "released", "answer": "Approved text."}}
    _backend(monkeypatch, views)
    app = AppTest.from_string(SCRIPT, default_timeout=20).run()
    assert "farmer_refresh" not in [b.key for b in app.button]
    app.number_input(key="farmer_lookup_id").set_value(5)
    app.text_input(key="farmer_lookup_token").set_value("code-5")
    app.button(key="farmer_check").click().run()
    assert any("Approved text." in item.value for item in app.success)
    app.run()  # the card is drawn above the lookup, so it shows the adopted case on the next run
    assert "Question 5" in _rendered(app)
    app.button(key="farmer_refresh").click().run()
    assert any("Approved text." in item.value for item in app.success)
