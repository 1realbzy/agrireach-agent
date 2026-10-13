import asyncio

from agrireach import agent, db

run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))


def test_routine_case_cited_and_pending():
    out = run("When should I harvest my soybean? I farm near Tamale.")
    assert out["status"] == "pending_review" and out["priority"] == "routine"
    assert "APNI-SARI-2023:harvest" in out["sources"]
    assert out["draft"].startswith("[OFFLINE STUB DRAFT")


def test_missing_region_asks_clarification():
    out = run("When should I plant soybean?")
    assert out["status"] == "draft" and "region" in out["clarification"]


def test_no_evidence_states_uncertainty_and_urgent():
    out = run("What price will soybean sell for in Tamale market next month?")
    assert out["sources"] == [] and out["priority"] == "urgent"
    assert "cannot give a grounded answer" in out["draft"]


def test_conflicting_sources_flagged():
    out = run("What spacing between soybean plants in Tamale?")
    assert out["priority"] == "urgent"
    assert any("plant spacing" in r for r in out["urgent_reasons"])
    assert {"APNI-SARI-2023:p11-spacing", "IITA-SSPING-2022:p17-spacing"} <= set(out["sources"])


def test_chemical_disease_request_urgent_no_prescription():
    out = run("My soybean leaves have yellow spots, what chemical should I spray in Tamale and what dose?")
    assert out["priority"] == "urgent"
    assert "not a diagnosis" in out["draft"] and "does not recommend products or doses" in out["draft"]


def test_tool_failure_is_graceful(monkeypatch):
    monkeypatch.setenv("AGRIREACH_KNOWLEDGE", "/nonexistent/knowledge.json")
    from agrireach import knowledge
    knowledge.load.cache_clear()
    out = run("When should I harvest soybean in Tamale?")
    knowledge.load.cache_clear()
    assert out["errors"] and out["sources"] == [] and out["priority"] == "urgent"
    assert "tool failed" in out["draft"]


def test_tool_calls_logged():
    out = run("When should I harvest soybean in Tamale?")
    tools = [r["tool"] for r in db.case_log(db.connect(), out["case_id"])]
    assert tools.count("create_or_update_case") == 2


def test_wa_recognised_without_clarification():
    out = run("When should I plant soybean at Wa?")
    assert out["status"] == "pending_review"
    assert out["region"] == "wa"
    assert not out.get("clarification")


def test_water_does_not_match_wa():
    out = run("When should I plant soybean near water?")
    assert out["status"] == "draft"
    assert "region" in (out.get("clarification") or "")
