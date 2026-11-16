"""Officer case view says whether a live model drafted the case and what it cost. Offline (no model calls)."""
from fastapi.testclient import TestClient

from agrireach import db, llm
from agrireach.api import app


def _headers():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def test_offline_case_is_labelled_as_no_model_with_zero_usage():
    client = TestClient(app)
    case = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    detail = client.get(f"/officer/cases/{case['case_id']}", headers=_headers()).json()
    generation = detail["generation"]
    assert generation["live_model"] is False
    assert generation["model_calls"] == 0 and generation["cost_usd"] == 0
    assert generation["label"].startswith("NO ")


def test_logged_model_usage_is_summed_per_case():
    client = TestClient(app)
    case = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    cid = case["case_id"]
    calls = [llm._call_record("drafter", "synthetic/model-a", ok=True, error=None, prompt_tokens=1000,
                              completion_tokens=200, cost_usd=0.0004),
             llm._call_record("judge", "synthetic/model-b", ok=True, error=None, prompt_tokens=500,
                              completion_tokens=50, cost_usd=0.0001)]
    llm.log_usage(cid, calls)
    con = db.connect()
    db.log(con, "agent", "farmer_text_proposal", {"draft_mode": "llm:synthetic/model-a"}, "test", case_id=cid)
    generation = client.get(f"/officer/cases/{cid}", headers=_headers()).json()["generation"]
    assert generation["live_model"] is True and generation["label"] == "LIVE MODEL DRAFT"
    assert generation["model_calls"] == 2
    assert generation["prompt_tokens"] == 1500 and generation["completion_tokens"] == 250
    assert generation["cost_usd"] == 0.0005 and generation["cost_complete"] is True
    assert generation["models"] == ["synthetic/model-a", "synthetic/model-b"]


def test_unknown_provider_cost_is_reported_as_unknown_not_zero():
    client = TestClient(app)
    cid = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()["case_id"]
    llm.log_usage(cid, [llm._call_record("drafter", "synthetic/model-a", ok=True, error=None, prompt_tokens=10,
                                         completion_tokens=5, cost_usd=None)])
    generation = client.get(f"/officer/cases/{cid}", headers=_headers()).json()["generation"]
    assert generation["cost_usd"] is None and generation["cost_complete"] is False


def test_farmer_view_never_shows_generation_details():
    client = TestClient(app)
    case = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    view = client.get(f"/farmer/cases/{case['case_id']}", headers={"X-Case-Access-Token": case["access_token"]}).json()
    assert "generation" not in view
