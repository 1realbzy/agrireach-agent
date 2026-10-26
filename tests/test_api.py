from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

c = TestClient(app)


def test_end_to_end_officer_gate():
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    r = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    cid = r["case_id"]
    assert c.get(f"/farmer/cases/{cid}").json()["answer"] is None
    assert c.post(f"/cases/{cid}/release", headers=h).status_code == 409  # no bypass, even signed in
    assert c.get("/officer/queue").status_code == 401  # the queue needs a signed-in officer
    assert cid in [x["id"] for x in c.get("/officer/queue", headers=h).json()]
    case = c.get(f"/officer/cases/{cid}", headers=h).json()
    proposed = case["farmer_draft"]
    assert proposed["text"] and "[" not in proposed["text"] and "9 out of 10 pods" in proposed["text"]
    # approving requires the exact farmer text, a signed-in officer, and an explicit source-check confirmation
    assert c.post(f"/officer/cases/{cid}/decision", headers=h,
                  json=({"decision": "approve", "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).status_code == 400
    assert c.post(f"/officer/cases/{cid}/decision",
                  json=({"officer": "Ama Mensah", "decision": "approve", "farmer_text": proposed["text"],
                        "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).status_code == 401
    assert c.post(f"/officer/cases/{cid}/decision", headers=h,
                  json=({"decision": "approve", "farmer_text": proposed["text"]}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).status_code == 400
    sent = proposed["text"] + " Officer-checked."
    ok = c.post(f"/officer/cases/{cid}/decision", headers=h,
                json=({"decision": "approve", "farmer_text": sent, "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).json()
    assert ok["status"] == "released"
    f = c.get(f"/farmer/cases/{cid}").json()
    assert f["approved_by"] == "Ama Mensah" and f["answer"] == sent  # the farmer gets exactly the approved text
