"""Routine auto-release: happy path, exclusions, fail-closed judge, default off, and audit."""
import json

import pytest
from agrireach import auto_release, db, judge
from agrireach.api import app
from fastapi.testclient import TestClient

HARVEST_Q = "When should I harvest soybean in Tamale?"
HARVEST_TEXT = (
    "When you harvest soybean in Tamale, wait until 9 out of 10 pods are mature and brown or dry. "
    "Harvest early in the morning to prevent pod shattering."
)
SOURCE = "APNI-SARI-2023:harvest"


def _seed(question=HARVEST_Q, text=HARVEST_TEXT, mode="llm:test-model", problems=None,
          priority="routine", urgent_reasons=None, language="en", needs_officer_text=False):
    con = db.connect()
    draft = text + f" [{SOURCE}]"
    cid = db.agent_upsert_case(con, status="pending_review", question=question, draft=draft,
                               sources=[SOURCE], priority=priority, urgent_reasons=urgent_reasons)
    db.agent_upsert_case(con, status="pending_review", case_id=cid, draft=draft, sources=[SOURCE],
                         priority=priority, urgent_reasons=urgent_reasons,
                         farmer_draft=json.dumps({
                             "text": text, "mode": mode, "problems": problems or [], "language": language,
                             "needs_officer_text": needs_officer_text, "zone_caveat": None,
                         }))
    return con, cid


def test_default_is_off_and_leaves_cases_in_the_officer_queue():
    assert auto_release.enabled() is False
    con, cid = _seed()
    result = auto_release.consider(cid)
    assert result["released"] is False and result["reason"] == "disabled"
    assert db.get_case(con, cid)["status"] == "pending_review"
    # The usual farmer path still waits for an officer when the setting is off.
    farmer = TestClient(app).get(f"/farmer/cases/{cid}").json()
    assert farmer["answer"] is None and farmer["status"] == "pending_review"


def test_happy_path_releases_and_writes_an_audit_record(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    con, cid = _seed()
    result = auto_release.consider(cid)
    assert result["released"] is True, result
    row = db.get_case(con, cid)
    assert row["status"] == "released"
    assert row["officer"] == auto_release.ACTOR
    assert row["farmer_text"] == HARVEST_TEXT
    events = auto_release.list_audit_events(con, cid)
    recorded = [e for e in events if e["event_name"] == "auto_release_recorded"]
    assert recorded, events
    assert recorded[0]["details"]["farmer_text"] == HARVEST_TEXT
    assert recorded[0]["details"]["judge_status"] == "supported"
    assert recorded[0]["details"]["verdicts"]
    assert all(v["verdict"] == "supported" for v in recorded[0]["details"]["verdicts"])
    audit = auto_release.audit_view(con, cid)
    assert audit and audit["auto_released"] is True and audit["farmer_text"] == HARVEST_TEXT
    farmer = TestClient(app).get(f"/farmer/cases/{cid}").json()
    assert farmer["status"] == "released" and farmer["answer"] == HARVEST_TEXT
    assert farmer["auto_released"] is True and farmer["approved_by"] == "Auto-released"


def test_flagged_safety_hold_stays_in_the_queue(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    # Harvest question (allow-listed) but the proposed text names a pesticide and a dose.
    text = "When you harvest soybean, also apply 50 ml of mancozeb per acre to the pods."
    con, cid = _seed(text=text)
    result = auto_release.consider(cid)
    assert result["released"] is False
    assert result["reason"] in {"topic_excluded", "safety_flags"}
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_high_risk_topic_is_excluded_even_with_clean_text(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    con, cid = _seed(question="What pesticide should I spray on soybean in Tamale?", text=HARVEST_TEXT)
    result = auto_release.consider(cid)
    assert result == {"released": False, "reason": "topic_excluded"} or result["reason"] == "topic_excluded"
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_source_conflict_stays_in_the_queue(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    con, cid = _seed(question="When should I plant soybean in Tamale?",
                     problems=["sources differ on the planting window"])
    result = auto_release.consider(cid)
    assert result["released"] is False and result["reason"] == "source_conflict"
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_judge_error_fails_closed(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")

    def boom(_user):
        raise RuntimeError("judge crashed")

    monkeypatch.setattr(judge, "_call", boom)
    con, cid = _seed()
    result = auto_release.consider(cid)
    assert result["released"] is False
    assert result["reason"] in {"judge_unavailable", "assessment_error"}
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_judge_timeout_fails_closed(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")

    def timeout(_user):
        raise TimeoutError("judge timed out")

    monkeypatch.setattr(judge, "_call", timeout)
    con, cid = _seed()
    result = auto_release.consider(cid)
    assert result["released"] is False
    assert result["reason"] in {"judge_unavailable", "assessment_error"}
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_feature_disabled_even_when_the_case_would_qualify(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "0")
    con, cid = _seed()
    assert auto_release.enabled() is False
    result = auto_release.consider(cid)
    assert result["released"] is False and result["reason"] == "disabled"
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_stub_draft_is_not_auto_released(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    con, cid = _seed(mode="stub")
    result = auto_release.consider(cid)
    assert result["released"] is False and result["reason"] == "not_model_draft"
    assert db.get_case(con, cid)["status"] == "pending_review"


def test_officer_can_retract_an_auto_released_web_case(monkeypatch):
    monkeypatch.setenv(auto_release.SETTING, "1")
    con, cid = _seed()
    assert auto_release.consider(cid)["released"] is True
    revision = db.get_case(con, cid)["revision"]
    row = db.reopen_case(con, cid, officer="Ama Mensah", expected_revision=revision,
                         information="Please have an officer look at this auto-released answer.")
    assert row["status"] == "pending_review"
    farmer = TestClient(app).get(f"/farmer/cases/{cid}").json()
    assert farmer["answer"] is None
    audit = auto_release.audit_view(con, cid)
    assert audit["retracted"] is True
