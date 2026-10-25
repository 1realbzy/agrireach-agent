from fastapi.testclient import TestClient

from agrireach.api import app

c = TestClient(app)


def test_end_to_end_officer_gate():
    r = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    cid = r["case_id"]
    assert c.get(f"/farmer/cases/{cid}").json()["answer"] is None
    assert c.post(f"/cases/{cid}/release").status_code == 409  # no bypass
    assert cid in [x["id"] for x in c.get("/officer/queue").json()]
    case = c.get(f"/officer/cases/{cid}").json()
    proposed = case["farmer_draft"]
    assert proposed["text"] and "[" not in proposed["text"] and "9 out of 10 pods" in proposed["text"]
    # approving requires the exact farmer text; an empty officer name is still refused
    assert c.post(f"/officer/cases/{cid}/decision",
                  json={"officer": "Ama Mensah", "decision": "approve"}).status_code == 400
    assert c.post(f"/officer/cases/{cid}/decision",
                  json={"officer": "", "decision": "approve", "farmer_text": proposed["text"]}).status_code == 409
    sent = proposed["text"] + " Officer-checked."
    ok = c.post(f"/officer/cases/{cid}/decision",
                json={"officer": "Ama Mensah", "decision": "approve", "farmer_text": sent}).json()
    assert ok["status"] == "released"
    f = c.get(f"/farmer/cases/{cid}").json()
    assert f["approved_by"] == "Ama Mensah" and f["answer"] == sent  # the farmer gets exactly the approved text
