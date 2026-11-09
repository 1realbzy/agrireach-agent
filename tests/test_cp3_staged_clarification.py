"""Stage D: a missing crop or place stays a draft the farmer can complete. It is not officer advice."""
import json
import threading

from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

c = TestClient(app)


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def ask(question):
    response = c.post("/ask", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def view(case_id, token):
    return c.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token})


def supplement(case_id, token, text, revision):
    return c.post(
        f"/farmer/cases/{case_id}/supplement",
        headers={"X-Case-Access-Token": token},
        json={"text": text, "expected_revision": revision},
    )


def queued(case_id):
    rows = c.get("/officer/queue", headers=officer()).json()
    return case_id in [row["id"] for row in rows]


def test_missing_region_is_waiting_on_the_farmer_and_can_be_completed():
    opened = ask("When should I plant soybean?")
    assert "district" in opened["clarification"].lower() or "region" in opened["clarification"].lower()
    body = view(opened["case_id"], opened["access_token"]).json()
    assert body["status"] == "draft" and body["answer"] is None
    assert "awaiting your information" in body["message"].lower()
    assert "waiting for an extension officer" not in body["message"].lower()
    assert body["clarification"] == opened["clarification"]
    assert not queued(opened["case_id"])
    row = db.get_case(db.connect(), opened["case_id"])
    assert not (row["draft"] or "").startswith("Which")
    assert row["farmer_text"] is None
    done = supplement(opened["case_id"], opened["access_token"], "Tamale", body["revision"])
    assert done.status_code == 200, done.text
    finished = done.json()
    assert finished["case_id"] == opened["case_id"] and finished["status"] == "pending_review"
    assert finished["answer"] is None and finished.get("clarification") in (None, "")
    assert queued(opened["case_id"])
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["question"] == "When should I plant soybean?"
    assert stored["region"] == "tamale" and stored["crop"] == "soybean"
    assert "Which district" not in (stored["draft"] or "")
    assert view(opened["case_id"], opened["access_token"]).json()["answer"] is None


def test_missing_crop_does_not_invent_one_and_then_accepts_the_farmers_crop():
    opened = ask("When should I plant in Tamale?")
    assert "crop" in opened["clarification"].lower()
    body = view(opened["case_id"], opened["access_token"]).json()
    assert "awaiting your information" in body["message"].lower() and body["answer"] is None
    vague = supplement(opened["case_id"], opened["access_token"], "hello", body["revision"])
    assert vague.status_code == 200, vague.text
    still = vague.json()
    assert still["case_id"] == opened["case_id"] and still["status"] == "draft"
    assert "crop" in still["clarification"].lower()
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["crop"] in ("", None) and stored["region"] == "tamale"
    done = supplement(opened["case_id"], opened["access_token"], "soybean", still["revision"])
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "pending_review" and done.json()["case_id"] == opened["case_id"]
    assert db.get_case(db.connect(), opened["case_id"])["crop"] == "soybean"


def test_both_missing_accepts_repeated_incomplete_replies_then_one_complete_reply():
    opened = ask("Can I grow this crop here?")
    assert "crop" in opened["clarification"].lower()
    body = view(opened["case_id"], opened["access_token"]).json()
    crop_reply = supplement(opened["case_id"], opened["access_token"], "soybean", body["revision"])
    assert crop_reply.status_code == 200, crop_reply.text
    crop_body = crop_reply.json()
    assert crop_body["status"] == "draft" and crop_body["case_id"] == opened["case_id"]
    assert "district" in crop_body["clarification"].lower() or "region" in crop_body["clarification"].lower()
    assert not queued(opened["case_id"])
    vague = supplement(opened["case_id"], opened["access_token"], "no idea", crop_body["revision"])
    assert vague.status_code == 200, vague.text
    assert vague.json()["status"] == "draft"
    assert db.get_case(db.connect(), opened["case_id"])["region"] in ("", None)
    done = supplement(opened["case_id"], opened["access_token"], "Tamale", vague.json()["revision"])
    assert done.status_code == 200, done.text
    assert done.json()["case_id"] == opened["case_id"] and done.json()["status"] == "pending_review"
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["question"] == "Can I grow this crop here?"
    assert stored["crop"] == "soybean" and stored["region"] == "tamale"
    assert stored["status"] == "pending_review" and stored["farmer_text"] is None
    assert "Which " not in (stored["draft"] or "")
    seen = view(opened["case_id"], opened["access_token"]).json()
    assert seen["answer"] is None and seen["status"] == "pending_review"
    assert "LEGACY" not in json.dumps(seen) and "Which crop" not in json.dumps(seen)


def test_supplement_is_token_bound_revision_bound_and_refuses_other_states():
    opened = ask("When should I plant soybean?")
    case_id, token = opened["case_id"], opened["access_token"]
    revision = view(case_id, token).json()["revision"]
    other = ask("When should I harvest soybean in Tamale?")
    assert supplement(case_id, other["access_token"], "Tamale", revision).status_code == 404
    assert c.post(f"/farmer/cases/{case_id}/supplement", json={"text": "Tamale", "expected_revision": revision}).status_code == 404
    assert supplement(case_id, token, "   ", revision).status_code == 422
    assert supplement(case_id, token, "T" * 501, revision).status_code == 422
    before = db.get_case(db.connect(), case_id)
    stale = supplement(case_id, token, "Tamale", revision + 9)
    assert stale.status_code == 409
    assert db.get_case(db.connect(), case_id)["revision"] == before["revision"]
    assert db.get_case(db.connect(), case_id)["status"] == "draft"
    pending = other["case_id"]
    pending_revision = db.get_case(db.connect(), pending)["revision"]
    refused = supplement(pending, other["access_token"], "Tamale", pending_revision)
    assert refused.status_code == 409
    assert db.get_case(db.connect(), pending)["status"] == "pending_review"
    con = db.connect()
    released = db.agent_upsert_case(con, status="draft", question="released question", crop="soybean", region="tamale")
    con.execute("UPDATE cases SET status='released' WHERE id=?", (released,))
    con.commit()
    released_token = db.issue_farmer_case_token(con, released)
    assert supplement(released, released_token, "Tamale", 1).status_code == 409
    con = db.connect()
    rejected = db.agent_upsert_case(con, status="draft", question="rejected question", crop="soybean", region="tamale")
    con.execute("UPDATE cases SET status='rejected' WHERE id=?", (rejected,))
    con.commit()
    rejected_token = db.issue_farmer_case_token(con, rejected)
    assert supplement(rejected, rejected_token, "Tamale", 1).status_code == 409


def test_concurrent_supplements_promote_the_draft_once():
    opened = ask("When should I plant soybean?")
    case_id, token = opened["case_id"], opened["access_token"]
    revision = view(case_id, token).json()["revision"]
    barrier = threading.Barrier(2)
    codes = []

    def send():
        barrier.wait()
        codes.append(supplement(case_id, token, "Tamale", revision).status_code)

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(codes) == [200, 409]
    stored = db.get_case(db.connect(), case_id)
    assert stored["status"] == "pending_review" and stored["region"] == "tamale"
    assert db.connect().execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    assert view(case_id, token).json()["answer"] is None


MARKER = "the field is flooded [synthetic marker]"
NEWER = "the field is dry [newer marker]"


def test_supplement_keeps_the_farmers_words_for_generation_and_the_officer(monkeypatch):
    seen = []
    from agrireach import llm
    real = llm.draft

    def spy(question, passages, notes, conflicts=None, feedback=None):
        seen.append(question)
        return real(question, passages, notes, conflicts=conflicts, feedback=feedback)

    monkeypatch.setattr(llm, "draft", spy)
    opened = ask("When should I plant soybean?")
    body = view(opened["case_id"], opened["access_token"]).json()
    done = supplement(opened["case_id"], opened["access_token"], f"Tamale; {MARKER}", body["revision"])
    assert done.status_code == 200, done.text
    stored = db.get_case(db.connect(), opened["case_id"])
    visible = c.get(f"/officer/cases/{opened['case_id']}", headers=officer()).json()
    assert stored["question"] == "When should I plant soybean?"
    assert stored["crop"] == "soybean" and stored["region"] == "tamale"
    assert seen and MARKER in seen[0] and "When should I plant soybean?" in seen[0]
    assert MARKER in (stored["draft"] or "")
    assert MARKER in json.dumps(visible["farmer_draft"]["replies"])
    assert visible["question"] == "When should I plant soybean?"
    logs = db.connect().execute("SELECT tool, args, result_summary FROM tool_log WHERE tool='model_usage'").fetchall()
    assert all(MARKER not in (row["args"] or "") and MARKER not in (row["result_summary"] or "") for row in logs)


def test_paused_generation_cannot_overwrite_a_newer_supplement(monkeypatch):
    """A has claimed the draft, B then claims a newer supplement, and A must not file afterwards."""
    from agrireach import agent
    original = agent.Tools.call
    releases = []
    ready = threading.Condition()

    async def pause_after_intake(self, name, args):
        result = await original(self, name, args)
        if name == "create_or_update_case" and args.get("require_draft") and not args.get("draft"):
            event = threading.Event()
            with ready:
                releases.append(event)
                ready.notify_all()
            assert event.wait(15), "paused generation was not released"
        return result

    monkeypatch.setattr(agent.Tools, "call", pause_after_intake)
    opened = ask("When should I plant soybean?")
    case_id, token = opened["case_id"], opened["access_token"]
    revision = view(case_id, token).json()["revision"]
    outcome = {}

    def send(name, text, expected):
        outcome[name] = supplement(case_id, token, text, expected)

    stale = threading.Thread(target=send, args=("stale", f"Tamale; {MARKER}", revision))
    stale.start()
    with ready:
        while len(releases) < 1:
            assert ready.wait(15), "first intake did not pause"
    bumped = db.get_case(db.connect(), case_id)
    newer = threading.Thread(target=send, args=("newer", f"Yendi; {NEWER}", bumped["revision"]))
    newer.start()
    with ready:
        while len(releases) < 2:
            assert ready.wait(15), "second intake did not pause"
    releases[0].set()
    stale.join(20)
    releases[1].set()
    newer.join(20)
    assert outcome["stale"].status_code == 409, outcome["stale"].text
    assert outcome["newer"].status_code == 200, outcome["newer"].text
    stored = db.get_case(db.connect(), case_id)
    visible = c.get(f"/officer/cases/{case_id}", headers=officer()).json()
    assert stored["status"] == "pending_review" and stored["question"] == "When should I plant soybean?"
    assert stored["region"] == "yendi"
    assert NEWER in (stored["draft"] or "") and MARKER not in (stored["draft"] or "")
    assert NEWER in json.dumps(visible) and MARKER not in json.dumps(visible["draft"])
    assert view(case_id, token).json()["answer"] is None


def test_crash_after_intake_retries_on_the_refreshed_revision_not_the_old_one(monkeypatch):
    from agrireach import agent
    original = agent.Tools.call

    async def crash_after_intake(self, name, args):
        result = await original(self, name, args)
        if name == "create_or_update_case" and args.get("require_draft") and not args.get("draft"):
            raise RuntimeError("injected crash after intake")
        return result

    monkeypatch.setattr(agent.Tools, "call", crash_after_intake)
    opened = ask("When should I plant soybean?")
    case_id, token = opened["case_id"], opened["access_token"]
    original_revision = view(case_id, token).json()["revision"]
    quiet = TestClient(app, raise_server_exceptions=False)
    crashed = quiet.post(
        f"/farmer/cases/{case_id}/supplement",
        headers={"X-Case-Access-Token": token},
        json={"text": f"Tamale; {MARKER}", "expected_revision": original_revision},
    )
    assert crashed.status_code >= 500, crashed.text
    mid = db.get_case(db.connect(), case_id)
    assert mid["status"] == "draft" and mid["question"] == "When should I plant soybean?"
    assert mid["revision"] != original_revision
    assert view(case_id, token).json()["answer"] is None
    monkeypatch.setattr(agent.Tools, "call", original)
    stale = supplement(case_id, token, f"Tamale; {MARKER}", original_revision)
    assert stale.status_code == 409
    assert db.get_case(db.connect(), case_id)["status"] == "draft"
    refreshed = view(case_id, token).json()["revision"]
    done = supplement(case_id, token, f"Tamale; {MARKER}", refreshed)
    assert done.status_code == 200, done.text
    stored = db.get_case(db.connect(), case_id)
    assert stored["status"] == "pending_review" and stored["question"] == "When should I plant soybean?"
    assert stored["region"] == "tamale" and MARKER in (stored["draft"] or "")
    assert view(case_id, token).json()["answer"] is None


def test_stored_explicit_crop_is_not_requested_again():
    response = c.post("/ask", json={"question": "When should I plant?", "crop": "soybean"})
    assert response.status_code == 200, response.text
    opened = response.json()
    assert "district" in opened["clarification"].lower() or "region" in opened["clarification"].lower()
    assert "which crop" not in opened["clarification"].lower()
    body = view(opened["case_id"], opened["access_token"]).json()
    done = supplement(opened["case_id"], opened["access_token"], "Tamale", body["revision"])
    assert done.status_code == 200, done.text
    finished = done.json()
    assert finished["status"] == "pending_review" and finished.get("clarification") in (None, "")
    stored = db.get_case(db.connect(), opened["case_id"])
    assert stored["question"] == "When should I plant?"
    assert stored["crop"] == "soybean" and stored["region"] == "tamale"


def _widget_keys(app, kind):
    return [widget.key for widget in getattr(app, kind)]


def test_farmer_screen_drops_a_stale_supplement_target(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []

    def backend(method, url, **kwargs):
        seen.append((method, url, kwargs.get("json")))
        if url.endswith("/health"):
            return __import__("httpx").Response(200, json={"draft_mode": "stub"})
        if url.endswith("/farmer/cases/7") and method == "GET":
            return __import__("httpx").Response(200, json={
                "case_id": 7, "status": "draft", "answer": None, "revision": 2,
                "clarification": "Which district or region is your farm in? Planting guidance differs by region.",
                "message": "Awaiting your information before an officer can review this."})
        if url.endswith("/farmer/cases/9") and method == "GET":
            return __import__("httpx").Response(404, json={"detail": "not found"})
        if url.endswith("/ask") and method == "POST":
            return __import__("httpx").Response(200, json={
                "case_id": 8, "access_token": "new-token", "status": "pending_review",
                "clarification": None, "message": "Your question was sent to an extension officer for review."})
        if url.endswith("/supplement"):
            return __import__("httpx").Response(500, json={"detail": "stale target"})
        return __import__("httpx").Response(200, json={"draft_mode": "stub"})

    monkeypatch.setattr(__import__("httpx"), "request", backend)

    def open_clarification():
        screen = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
        screen.number_input(key="farmer_lookup_id").set_value(7)
        screen.text_input(key="farmer_lookup_token").set_value("farmer-token")
        screen.button(key="farmer_check").click().run()
        assert "farmer_supplement_button" in _widget_keys(screen, "button")
        return screen

    invalid = open_clarification()
    invalid.number_input(key="farmer_lookup_id").set_value(9)
    invalid.text_input(key="farmer_lookup_token").set_value("wrong-token")
    invalid.button(key="farmer_check").click().run()
    assert "farmer_supplement_button" not in _widget_keys(invalid, "button")
    submitted = open_clarification()
    submitted.text_area(key="farmer_question").set_value("When should I harvest soybean in Tamale?")
    submitted.button(key="farmer_submit_button").click().run()
    assert "farmer_supplement_button" not in _widget_keys(submitted, "button")
    assert not any(call[0] == "POST" and str(call[1]).endswith("/supplement") for call in seen)


def test_farmer_screen_shows_the_clarification_and_sends_the_reply(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from streamlit import env_util
    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    seen = []

    def backend(method, url, **kwargs):
        seen.append((method, url, kwargs.get("json")))
        if url.endswith("/farmer/cases/7") and method == "GET":
            return __import__("httpx").Response(200, json={
                "case_id": 7, "status": "draft", "answer": None, "revision": 2,
                "clarification": "Which district or region is your farm in? Planting guidance differs by region.",
                "message": "Awaiting your information before an officer can review this."})
        if url.endswith("/supplement") and method == "POST":
            assert kwargs["json"] == {"text": "Tamale", "expected_revision": 2}
            assert kwargs["headers"]["X-Case-Access-Token"] == "farmer-token"
            return __import__("httpx").Response(200, json={
                "case_id": 7, "status": "pending_review", "answer": None, "clarification": None,
                "message": "Your question was sent to an extension officer for review."})
        return __import__("httpx").Response(200, json={"draft_mode": "stub"})

    monkeypatch.setattr(__import__("httpx"), "request", backend)
    app = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    app.number_input(key="farmer_lookup_id").set_value(7)
    app.text_input(key="farmer_lookup_token").set_value("farmer-token")
    app.button(key="farmer_check").click().run()
    assert any("Awaiting your information" in item.value for item in app.info)
    assert not any("being prepared for review" in item.value for item in app.info)
    assert not any("Waiting for officer review" in item.value for item in app.info)
    app.text_input(key="farmer_supplement_text").set_value("Tamale")
    app.button(key="farmer_supplement_button").click().run()
    assert ("POST", "http://127.0.0.1:8000/farmer/cases/7/supplement", {"text": "Tamale", "expected_revision": 2}) in seen
    assert any("extension officer for review" in item.value for item in list(app.info) + list(app.success))
