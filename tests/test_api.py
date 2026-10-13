from fastapi.testclient import TestClient

from agrireach.api import app

c = TestClient(app)


def test_end_to_end_officer_gate():
    r = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    cid = r["case_id"]
    assert c.get(f"/farmer/cases/{cid}").json()["answer"] is None
    assert c.post(f"/cases/{cid}/release").status_code == 409  # no bypass
    assert cid in [x["id"] for x in c.get("/officer/queue").json()]
    assert c.post(f"/officer/cases/{cid}/decision", json={"officer": "", "decision": "approve"}).status_code == 409
    ok = c.post(f"/officer/cases/{cid}/decision", json={"officer": "Ama Mensah", "decision": "approve"}).json()
    assert ok["status"] == "released"
    f = c.get(f"/farmer/cases/{cid}").json()
    assert f["approved_by"] == "Ama Mensah" and "9 out of 10 pods" in f["answer"]
