"""Run 6 (docs/live-eval-2026-10-25-run6-approval.md, criterion 5, F1-b): whether the approved farmer text needs the
pesticide safety line is decided from the case itself, the retrieved passages (a source pesticide sentence, the one
ensure_safety_line inserts) and the original proposal, never from the officer's draft, which the officer can edit."""
import pytest
from fastapi.testclient import TestClient

from agrireach import db, farmer_reply as fr, knowledge
from agrireach.api import app

Q = "Fall armyworm is eating my maize in Kintampo. What pesticide should I use?"
PS = [knowledge.reference(i) for i in ["APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p18-scouting"]]


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def strip_safety(t):
    return " ".join(s for s in fr._sentences(t) if not fr.SAFETY_RE.search(s))


@pytest.mark.parametrize("decision", ["approve", "edit_approve"])
def test_warns_even_when_the_stored_draft_has_no_pesticide_sentence(decision):
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": Q}).json()["case_id"]
    case = c.get(f"/officer/cases/{cid}", headers=h).json()
    prop = case["farmer_draft"]["text"]
    con = db.connect()
    with con:  # the officer's draft has lost every pesticide sentence (F1-b removed it from both texts)
        con.execute("UPDATE cases SET draft=? WHERE id=?", (strip_safety(case["draft"]), cid))
    edited = strip_safety(prop)
    body = {"decision": decision, "farmer_text": edited, "confirmed": True}
    if decision == "edit_approve":
        body["edited_text"] = edited
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json=body)
    assert r.status_code == 200, r.text
    assert any("drops the pesticide safety line" in w for w in r.json()["warnings"]), r.json()["warnings"]
    assert db.get_case(db.connect(), cid)["farmer_text"] == edited  # warned, never re-inserted


def test_needed_from_passages_or_original_proposal_not_from_the_draft():
    no_line = "Check your maize at least once a week."
    assert fr.drops_safety_line(no_line, PS, proposal="")
    assert fr.drops_safety_line(no_line, [], proposal="Consult your local AEA before you spray (APNI).")
    assert not fr.drops_safety_line(no_line, [], proposal="Plant after three good rains.")
    assert not fr.drops_safety_line("Consult your local AEA on pesticides.", PS, proposal="")
    # a passage pesticide mention the guarantee would never insert (a regulatory limit) does not make a line needed
    limit = [{"id": "X:p1", "text": "Pesticide residues must stay below 10 ppb."}]
    assert not fr.drops_safety_line(no_line, limit, proposal="")


def test_the_officer_draft_alone_never_decides_it():
    # Ejura planting: no source pesticide sentence and none in the proposal. A pesticide sentence the officer adds to
    # the draft does not make the line "needed" at approval (the draft is the officer's own, editable text).
    c, h = TestClient(app), officer()
    cid = c.post("/ask", json={"question": "When should I plant maize in Ejura?"}).json()["case_id"]
    case = c.get(f"/officer/cases/{cid}", headers=h).json()
    prop = case["farmer_draft"]["text"]
    assert prop and not fr.SAFETY_RE.search(prop)
    con = db.connect()
    with con:
        con.execute("UPDATE cases SET draft=? WHERE id=?", (case["draft"] + "\nDo not spray herbicide near the seedlings.", cid))
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "farmer_text": prop, "confirmed": True})
    assert r.status_code == 200, r.text
    assert not any("pesticide safety line" in w for w in r.json()["warnings"]), r.json()["warnings"]


@pytest.mark.parametrize("swap", ["Spray pesticide every week.", "Use any pesticide you have.",
                                  "Spray any pesticide you have twice a day.", "Use pesticide.",
                                  "No pesticide is needed, just spray water."])  # Scoffer, then QA, on d37b84b
def test_a_different_pesticide_sentence_does_not_count_as_the_safety_line(swap):
    # Scoffer's and QA's reviews of d37b84b: the warning only checked that some pesticide word was left, so swapping the AEA
    # referral for unsafe pesticide advice raised no warning. The source's own sentence (or the same referral
    # reworded, _repeats) must still be there.
    advice = "Check your maize at least once a week."
    assert fr.drops_safety_line(f"{swap} {advice}", PS, proposal="")
    assert fr.drops_safety_line(f"{advice} {swap}", [], proposal="Consult your local AEA before you spray (APNI).")
    kept = fr.source_safety_line(PS)[0]
    assert not fr.drops_safety_line(f"{kept} {swap} {advice}", PS, proposal="")
