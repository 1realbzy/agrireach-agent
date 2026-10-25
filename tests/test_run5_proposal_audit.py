"""Run 5 criterion 4: the audit log (tool_log) had no entry for the farmer SMS proposal, so the reasons a model SMS
was replaced by the rule text (F1-b "Adds severity condition", EJ's rainfall figures) were only on the case's
farmer_draft. Every proposal now logs a 'farmer_text_proposal' entry: the path (model, rule or officer), the model
SMS rejection reasons or error, the sentences dropped to fit, and the safety line's source."""
import asyncio
import json

from fastapi.testclient import TestClient

from agrireach import agent, db, farmer_reply as fr, judge, knowledge, llm
from agrireach.api import app

F1_Q = "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect."
DRAFT = "Scout the maize field at least once a week [APNI-SARI-2023-MAIZE:p18-scouting]."
# A model SMS sentence the judge rejects for an added severity condition (as F1-b's was in run 5; that sentence itself
# is now removed as a repeat of the source's AEA referral, tests/test_run6_safety_dedupe.py, so another one is used)
SEVERE = "If the infestation is severe, check the field every day and remove the larvae by hand."


def severity_judge(user):
    items = [l for l in user.splitlines() if ". SENTENCE: " in l]
    return json.dumps({"verdicts": [
        {"n": i + 1, "verdict": "not_supported" if "severe" in l else "supported",
         "why": "Adds severity condition" if "severe" in l else "ok"} for i, l in enumerate(items)]})


def proposals(cid):
    return [e for e in db.case_log(db.connect(), cid) if e["tool"] == "farmer_text_proposal"]


def test_agent_logs_the_proposal_with_the_model_rejection_reason(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(llm, "draft", lambda *a, **k: (DRAFT, "llm:fake"))
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (f"Check your maize field every week. {SEVERE}", "llm:fake"))
    monkeypatch.setattr(judge, "_call", severity_judge)
    out = asyncio.run(agent.run(F1_Q, use_fetch=False))
    [e] = proposals(out["case_id"])
    args = json.loads(e["args"])
    assert args["path"] == "rule" and args["mode"] == "rule"
    assert any("Adds severity condition" in r for r in args["model_rejected"]), args
    assert "Adds severity condition" in e["result_summary"] and e["actor"] == "agent"


def test_ejura_rainfall_figure_rejection_is_audited_and_dropped_sentences_listed(monkeypatch):
    ids = ["IITA-MAIZE-2025:p15-three-good-rains", "MOFA-MAIZE:p10-when-to-plant"]
    ps = [knowledge.reference(i) for i in ids]
    officer_text = ("Plant after three good rains within the planting window to ensure enough soil moisture "
                    "[IITA-MAIZE-2025:p15-three-good-rains]. Sow after the rains have stabilized to avoid wilting "
                    "[MOFA-MAIZE:p10-when-to-plant].")
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (
        "From 2026-09-25 to 2026-10-24, there were 24 of 30 days with at least 1 mm of rain, totaling 185.5 mm.",
        "llm:fake"))
    monkeypatch.setattr(fr, "MAX_CHARS", 100)
    fd = fr.propose(officer_text, "When should I plant maize in Ejura?", passages=ps)
    assert fd.mode == "rule"
    assert any("185.5 mm" in r for r in fd.audit["model_rejected"]), fd.audit
    assert fd.audit["dropped"] == ["Sow after the rains have stabilized to avoid wilting."], fd.audit
    assert fd.audit["path"] == "rule"


def test_model_error_and_officer_path_are_audited(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")

    def boom(*a, **k):
        raise TimeoutError("model timed out")
    monkeypatch.setattr(fr, "_llm_rewrite", boom)
    fd = fr.propose("Weed well.", "q", passages=[])
    assert fd.audit["model_error"].startswith("TimeoutError") and fd.audit["path"] == "rule"
    assert fr.propose("Weed well.", "q", language="twi").audit["path"] == "officer"
    assert fr.propose("Note: officer only.", "q").audit["path"] == "officer"


def test_accepted_model_sms_is_audited_as_model_path(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: ("Weed your maize field well.", "llm:fake"))
    fd = fr.propose("Weed the maize field well.", "q")
    assert fd.audit["path"] == "model" and fd.audit["model_rejected"] == [] and fd.audit["dropped"] == []


def test_officer_re_proposal_is_audited_with_the_officer_as_actor():
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "Fall armyworm is eating my maize in Kintampo. What pesticide?"}).json()[
        "case_id"]
    assert len(proposals(cid)) == 1 and proposals(cid)[0]["actor"] == "agent"
    draft = db.get_case(db.connect(), cid)["draft"]
    c.post(f"/officer/cases/{cid}/farmer-draft", headers=h, json={"officer_text": draft})
    second = proposals(cid)[-1]
    assert len(proposals(cid)) == 2 and second["actor"] == "officer:Ama Mensah"
    assert json.loads(second["args"])["safety_line"] == "APNI"
