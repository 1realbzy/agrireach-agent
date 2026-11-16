"""Yellow maize leaves in Wa: no curated evidence must not become treatment advice.

The live run drafted "I do not know.", then a rewrite invented fertiliser and
spray instructions. Citation checks removed them and an officer could approve
the leftover uncertainty as if it were a completed advisory.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from agrireach import agent, approval, db, farmer_reply, llm
from agrireach.api import app

QUESTION = "My maize leaves are turning yellow in Wa. What should I do?"
GAP = "An extension officer needs to answer this case."
FARMER_STATUS = (
    "AgriReach has no sourced guidance for this question. An extension officer will investigate it. "
    "No treatment advice has been approved."
)
TREATMENT = "Apply NPK fertiliser and spray a pesticide on the yellow leaves every week."


def _officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def test_no_evidence_does_not_call_the_treatment_rewrite(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "local-test-key")
    calls = {"draft": 0, "rewrite": 0}

    def draft(*_args, **_kwargs):
        calls["draft"] += 1
        return "I do not know.", "llm:test-model"

    def rewrite(*_args, **_kwargs):
        calls["rewrite"] += 1
        return TREATMENT, "llm:test-model"

    monkeypatch.setattr(llm, "draft", draft)
    monkeypatch.setattr(farmer_reply, "_llm_rewrite", rewrite)
    out = __import__("asyncio").run(agent.run(QUESTION, use_fetch=False))
    assert calls == {"draft": 0, "rewrite": 0}
    assert out["sources"] == []
    assert out["status"] == "pending_review"
    assert out["clarification"] in (None, "")
    assert out["draft_mode"] == "stub(no-evidence)"
    assert "npk" not in out["draft"].casefold()
    assert "pesticide" not in out["draft"].casefold()
    assert "spray" not in out["draft"].casefold()
    proposal = out["farmer_draft"]["text"]
    assert proposal == GAP
    assert "i do not know" not in proposal.casefold()
    assert out["farmer_draft"]["audit"].get("skipped_rewrite") == "no_supporting_evidence"


def test_uncertainty_without_sources_is_not_a_supported_advisory():
    client = TestClient(app)
    opened = client.post("/ask", json={"question": QUESTION}).json()
    assert opened["status"] == "pending_review"
    assert opened.get("answer") is None
    assert opened["evidence_gap"] is True
    assert opened["message"] == FARMER_STATUS
    assert "treatment" in opened["message"].casefold()
    token = opened["access_token"]
    case_id = opened["case_id"]
    farmer = client.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token}).json()
    assert farmer["answer"] is None
    assert farmer["evidence_gap"] is True
    assert farmer["message"] == FARMER_STATUS
    assert "i do not know" not in json.dumps(farmer).casefold()
    headers = _officer()
    row = db.get_case(db.connect(), case_id)
    body = {"decision": "approve", "confirmed": True, "expected_revision": row["revision"]}
    for text in ("I do not know.", GAP):
        blocked = client.post(
            f"/officer/cases/{case_id}/decision", headers=headers, json=body | {"farmer_text": text})
        assert blocked.status_code == 422, blocked.text
        detail = blocked.json()["detail"]
        assert detail["outcome"] == "review_required"
        assert detail["judge_status"] == "insufficient_evidence"
        assert detail["judge_status"] != "supported"
        assert any(finding["rule_id"] == "EVIDENCE_GAP" for finding in detail["findings"])
    stored = db.get_case(db.connect(), case_id)
    assert stored["status"] == "pending_review"
    assert stored["farmer_text"] is None
    assessed = approval.assess_candidate("I do not know.", approval.context(db.connect(), stored))
    assert assessed["judge_status"] != "supported"
    spray = client.post(
        f"/officer/cases/{case_id}/decision", headers=headers,
        json=body | {"farmer_text": "Mix two pesticides and spray the yellow leaves every week."})
    assert spray.status_code == 422
    assert any(finding["rule_id"] == "S3" for finding in spray.json()["detail"]["findings"])
    seen = client.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token}).json()
    assert seen["answer"] is None
    assert "spray" not in seen["message"].casefold()


def test_evidence_gap_reaches_the_farmer_screen(monkeypatch):
    import httpx
    from streamlit import env_util
    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    client = TestClient(app)
    opened = client.post("/ask", json={"question": QUESTION}).json()

    def backend(method, url, **kwargs):
        path = url[url.find("/"):] if "://" in url else url
        response = client.request(method, path, headers=kwargs.get("headers"))
        return httpx.Response(response.status_code, content=response.content)

    monkeypatch.setattr(httpx, "request", backend)
    screen = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    screen.number_input(key="farmer_lookup_id").set_value(opened["case_id"])
    screen.text_input(key="farmer_lookup_token").set_value(opened["access_token"])
    screen.button(key="farmer_check").click().run()
    visible = " ".join(item.value for item in list(screen.info) + list(screen.success) + list(screen.warning))
    assert FARMER_STATUS in visible
    assert "I do not know" not in visible
    assert not any("npk" in item.value.casefold() or "pesticide" in item.value.casefold() for item in screen.success)
