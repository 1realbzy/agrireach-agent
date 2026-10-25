"""Run 5 (docs/live-eval-2026-10-25-run5-approval.md, criterion 5): F1-b's officer removed the pesticide safety line
with decision 'edit_approve', sending the same text as edited_text and farmer_text. The approval went through with
warnings: [] because the safety check compared the farmer text with the officer's *edited* text (which had no
pesticide line either). The check is against the case's own draft and passages, and the warning is in the decide
response (what the officer sees), not only in the log."""
import pytest
from fastapi.testclient import TestClient

from agrireach import db, farmer_reply as fr
from agrireach.api import app

Q = "Fall armyworm is eating my maize in Kintampo. What pesticide should I use?"


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


@pytest.mark.parametrize("decision", ["approve", "edit_approve"])
def test_officer_removing_the_safety_line_sees_the_warning_in_the_response(decision):
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": Q}).json()["case_id"]
    prop = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]
    assert fr.SAFETY_RE.search(prop)
    edited = " ".join(s for s in fr._sentences(prop) if not fr.SAFETY_RE.search(s))  # as the run 5 driver did
    body = {"decision": decision, "farmer_text": edited, "confirmed": True}
    if decision == "edit_approve":
        body["edited_text"] = edited
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json=body)
    assert r.status_code == 200 and r.json()["status"] == "released"
    assert any("drops the pesticide safety line" in w for w in r.json()["warnings"]), r.json()["warnings"]
    log = c.get(f"/officer/cases/{cid}", headers=h).json()["log"]
    assert any(e["tool"] == "approval_warning" and "pesticide safety line" in e["result_summary"] for e in log)
    assert db.get_case(db.connect(), cid)["farmer_text"] == edited  # warned, never re-inserted


def test_no_safety_warning_when_the_line_is_kept_in_an_edit():
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": Q}).json()["case_id"]
    prop = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "edit_approve", "edited_text": prop, "farmer_text": prop, "confirmed": True}).json()
    assert not any("pesticide safety line" in w for w in r["warnings"]), r["warnings"]
