"""The out-of-zone caveat (review item 3): it must survive offline mode, reach the farmer, name the right zone, and
the officer must be warned when an approved farmer text drops it."""
import asyncio

from fastapi.testclient import TestClient

from agrireach import agent, db, farmer_reply as fr, llm
from agrireach.api import app

run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))


def test_offline_stub_draft_still_carries_the_caution():
    out = run("When should I plant soybean in Kumasi?")  # soybean guides are Northern Ghana only
    assert out["draft_mode"].startswith("stub") and out["zone_mismatch"] is True
    lines = out["draft"].splitlines()
    assert lines[0] == llm.STUB_LABEL  # still recognisably the offline, verbatim draft
    assert lines[1].startswith("Caution:") and "Kumasi" in lines[1] and "Northern Ghana" in lines[1]


def test_farmer_text_carries_a_caveat_sentence_when_zones_mismatch():
    out = run("When should I harvest soybean in Kumasi?")
    fd = out["farmer_draft"]
    assert out["zone_mismatch"] and fd["text"] and fd["zone_caveat"]
    assert fd["text"].startswith(fd["zone_caveat"]["sentence"])
    assert "Northern Ghana" in fd["text"] and "Kumasi" in fd["text"] and "officer" not in fd["text"].lower()
    assert any("Northern Ghana" in p for p in fd["problems"])  # officer told the caveat was added and why
    assert fr.check(fd["text"], out["draft"]) == []


def test_no_caveat_for_a_northern_question():
    out = run("When should I harvest soybean in Tamale?")
    assert not out["zone_mismatch"] and not out["farmer_draft"].get("zone_caveat")
    assert "may not suit" not in out["farmer_draft"]["text"]


def test_caveat_names_the_zone_the_passages_are_for_not_always_northern_ghana():
    c = fr.zone_caveat("Kumasi", "transition")
    assert "transition" in c["sentence"] and "Northern Ghana" not in c["sentence"] and "Kumasi" in c["sentence"]


def test_officer_is_warned_when_the_approved_farmer_text_drops_the_caveat():
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "When should I harvest soybean in Kumasi?"}).json()["case_id"]
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json=({
        "decision": "approve", "confirmed": True, "farmer_text": "Harvest when 9 out of 10 pods are brown."}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).json()
    assert r["status"] == "released"
    assert any("caveat" in w for w in r["warnings"])
    log = c.get(f"/officer/cases/{cid}", headers=h).json()["log"]
    assert any("caveat" in str(e) for e in log)


def test_no_warning_when_the_caveat_is_kept():
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "When should I harvest soybean in Kumasi?"}).json()["case_id"]
    text = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json=({"decision": "approve", "confirmed": True, "farmer_text": text}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]}).json()
    assert r["status"] == "released" and r["warnings"] == []
