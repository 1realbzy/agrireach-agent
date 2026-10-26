"""Officer sign-in: only a registered, signed-in officer can see the queue, decide or release, and the officer name on
the record comes from the sign-in, never from the request body. Two decisions on one case cannot both win."""
import threading

from fastapi.testclient import TestClient

from agrireach import db
from agrireach.api import app

c = TestClient(app)


def _officer(name="Ama Mensah"):
    return db.add_officer(db.connect(), name)  # returns the one-time token


def _case():
    r = c.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    return r["case_id"]


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_officer_endpoints_refuse_without_sign_in():
    cid = _case()
    assert c.get("/officer/queue").status_code == 401
    assert c.get(f"/officer/cases/{cid}").status_code == 401
    assert c.post(f"/officer/cases/{cid}/decision",
                  json=({"decision": "approve", "farmer_text": "x", "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).status_code == 401
    assert c.post(f"/cases/{cid}/release").status_code == 401


def test_wrong_token_is_refused():
    _officer()
    assert c.get("/officer/queue", headers=_auth("not-a-real-token")).status_code == 401


def test_officer_name_comes_from_the_sign_in_not_the_body():
    tok = _officer("Ama Mensah")
    cid = _case()
    r = c.post(f"/officer/cases/{cid}/decision", headers=_auth(tok),
               json=({"officer": "not-a-real-officer", "decision": "approve", "farmer_text": "Harvest at 9 of 10 pods.",
                     "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    assert r.status_code == 200, r.text
    f = c.get(f"/farmer/cases/{cid}").json()
    assert f["approved_by"] == "Ama Mensah"


def test_tokens_are_not_stored_in_clear():
    tok = _officer()
    con = db.connect()
    dump = "\n".join(con.iterdump())
    assert tok not in dump


def test_concurrent_approvals_only_one_wins():
    tok = _officer()
    cid = _case()
    texts = ["Answer A: harvest at 9 of 10 pods.", "Answer B: harvest at 9 of 10 pods."]
    codes = {}
    barrier = threading.Barrier(2)

    def go(t):
        con = db.connect()
        barrier.wait()
        try:
            db.officer_decide(con, cid, officer="Ama Mensah", decision="approve", farmer_text=t, expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
            codes[t] = "ok"
        except db.GateError:
            codes[t] = "refused"

    ths = [threading.Thread(target=go, args=(t,)) for t in texts]
    [t.start() for t in ths]
    [t.join() for t in ths]
    assert sorted(codes.values()) == ["ok", "refused"]
    winner = [t for t, v in codes.items() if v == "ok"][0]
    assert db.get_case(db.connect(), cid)["farmer_text"] == winner


def test_stale_decision_after_another_officer_decided_is_refused():
    """The check-then-write race: officer_decide must only write if the case is still pending_review."""
    con = db.connect()
    cid = _case()
    real_get = db.get_case
    # Simulate the other officer deciding between this call's status check and its write.
    calls = {"n": 0}

    def get_then_race(con_, case_id):
        row = real_get(con_, case_id)
        calls["n"] += 1
        if calls["n"] == 1:
            db.connect().execute("UPDATE cases SET status='rejected', officer='Kofi' WHERE id=?", (case_id,)).connection.commit()
        return row

    import pytest
    db.get_case = get_then_race
    try:
        with pytest.raises(db.GateError):
            db.officer_decide(con, cid, officer="Ama Mensah", decision="approve", farmer_text="late answer", expected_revision=con.execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0])
    finally:
        db.get_case = real_get
    assert db.get_case(con, cid)["status"] == "rejected"
