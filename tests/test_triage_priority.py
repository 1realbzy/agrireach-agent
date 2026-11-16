"""Priority ranking must not authorize release or rewrite existing case safety."""

from agrireach import triage
from fastapi.testclient import TestClient
from agrireach import db
from agrireach.api import app


def test_reported_chemical_exposure_is_critical():
    result = triage.assess({"question": "A worker reports pesticide poisoning after spraying."})
    assert result["level"] == "critical"
    assert result["rank"] == 0
    assert result["autonomous_release_permitted"] is False


def test_chemical_advice_is_high_even_without_old_urgent_flag():
    result = triage.assess({"question": "Can I mix both pesticides on soybean?", "priority": "routine"})
    assert result["level"] == "high"
    assert result["reasons"]


def test_reported_spread_is_high_but_not_confirmed_outbreak():
    result = triage.assess({"question": "Several nearby farms are affected by yellowing maize."})
    assert result["level"] == "high"
    assert "reports" in result["reasons"][0].lower()


def test_existing_intake_flag_cannot_become_routine():
    result = triage.assess({"question": "Help with cassava", "priority": "urgent",
                            "urgent_reasons": ["unsupported crop"]})
    assert result["level"] == "medium"


def test_routine_question_does_not_bypass_human_approval():
    result = triage.assess({"question": "When should I harvest soybean in Tamale?", "priority": "routine"})
    assert result["level"] == "routine"
    assert result["autonomous_release_permitted"] is False
    assert result["provisional"] is True


def test_triage_does_not_mutate_case():
    case = {"question": "What fertilizer should I use?", "priority": "urgent", "urgent_reasons": ["uncertain"]}
    snapshot = {**case, "urgent_reasons": list(case["urgent_reasons"])}
    triage.assess(case)
    assert case == snapshot


def test_officer_queue_sorted_by_explainable_priority():
    con = db.connect()
    token = db.add_officer(con, "Priority Test Officer")
    ordinary = db.agent_upsert_case(con, status="pending_review", question="When do I harvest soybean?", priority="routine")
    critical = db.agent_upsert_case(con, status="pending_review", question="Worker reports pesticide poisoning", priority="urgent")
    high = db.agent_upsert_case(con, status="pending_review", question="Can I mix both pesticides?", priority="routine")
    response = TestClient(app).get("/officer/queue", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    cases = response.json()
    ids = [case["id"] for case in cases]
    assert ids.index(critical) < ids.index(high) < ids.index(ordinary)
    assert next(case for case in cases if case["id"] == critical)["triage"]["reasons"]
    assert all(case["triage"]["autonomous_release_permitted"] is False for case in cases)
