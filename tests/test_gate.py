import pytest

from agrireach import db


def test_agent_cannot_approve_or_release():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="draft", question="q")
    for bad in ("approved", "released", "rejected"):
        with pytest.raises(db.GateError):
            db.agent_upsert_case(con, status=bad, case_id=cid)
    with pytest.raises(db.GateError):
        db.release_to_farmer(con, cid)
    blocked = [r for r in db.case_log(con, cid) if not r["ok"]]
    assert len(blocked) == 4


def test_release_requires_named_officer_and_records_edit():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="q", draft="agent text")
    with pytest.raises(db.GateError):
        db.officer_decide(con, cid, officer="  ", decision="approve", expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
    row = db.officer_decide(con, cid, officer="Ama Mensah", decision="edit_approve", edited_text="officer text", farmer_text="Do not use unapproved pesticides.", expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
    assert row["status"] == "approved" and row["final_text"] == "officer text" and row["draft"] == "agent text"
    assert row["officer"] == "Ama Mensah" and row["decided_at"]
    assert db.release_to_farmer(con, cid)["status"] == "released"


def test_agent_cannot_modify_officer_owned_case():
    con = db.connect()
    cid = db.agent_upsert_case(con, status="pending_review", question="q", draft="d")
    db.officer_decide(con, cid, officer="Kofi", decision="reject", expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
    with pytest.raises(db.GateError):
        db.agent_upsert_case(con, status="pending_review", case_id=cid, draft="sneaky")
