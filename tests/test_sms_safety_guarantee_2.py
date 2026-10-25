"""Reviewer follow-ups on the pesticide safety guarantee (farmer_reply.ensure_safety_line):
1. a model SMS is never trimmed: if it doesn't fit with the source's line it falls to the rule path;
2. "fits" means the SMS limit the approval endpoint enforces (sms.length_prompt: 4 parts, so 612 GSM-7 characters
   or 268 when one character needs Unicode) as well as MAX_CHARS, so a proposal can't get a 400 at approval;
3. the line is added when the proposal is made, never at approval or send: what the officer approves is sent byte for
   byte, and an officer who removes the line is warned (logged), not overridden;
4. order is zone caveat, safety line, advice: only advice is dropped to fit;
5. every dropped sentence is named in the officer note, so the officer can judge whether the reply still makes sense.
Offline: stub drafts, the conftest judge, the local phone simulator."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from agrireach import agent, db, farmer_reply as fr, knowledge, llm
from agrireach.api import app
from agrireach.channels import simulator, sms

FAW_IDS = ["APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
           "APNI-SARI-2023-MAIZE:p20-faw-control"]
PS = [knowledge.reference(i) for i in FAW_IDS]
LINE = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area (APNI)."
KINTAMPO = "Fall armyworm is eating my maize in Kintampo. What pesticide should I use?"
ASHANTI = "Armyworms are attacking my maize farm in Ashanti Region. What pesticide should I spray?"
SENDER = "sim:farmer-7"

run = lambda q: asyncio.run(agent.run(q, use_fetch=False))  # noqa: E731


def fits_approval(text):
    return sms.length_prompt(text) is None and len(text) <= fr.MAX_CHARS


def dropped_notes(fd_problems):
    return [p for p in fd_problems if "dropped to fit" in p]


# --- 1. model text is never trimmed ---

def test_model_sms_that_fits_alone_but_not_with_the_line_goes_to_the_rule_path(monkeypatch):
    caveat = fr.zone_caveat("Kintampo")
    model = ("You should walk through your maize field at least once a week and look for insect damage on leaves, "
             "cobs or stems, larvae or eggs on the leaves, odd leaf colour and slow growing plants. Rotate maize with "
             "groundnut to reduce armyworm. Deep ploughing and burying or burning infested maize residues reduces "
             "armyworm the next season. Proper weeding also helps. Check your field every week after that too.")
    draft = "\n".join(llm.stub_draft(KINTAMPO, PS, []).splitlines()[1:])  # a stub-labelled draft skips the model
    assert len(f"{caveat['sentence']} {model}") <= fr.MAX_CHARS < len(f"{caveat['sentence']} {LINE} {model}")
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (model, "llm:fake"))
    fd = fr.propose(draft, KINTAMPO, zone_caveat=caveat, passages=PS)
    assert fd.mode == "rule" and any(p.startswith("model rewrite rejected") for p in fd.problems), fd.problems
    assert fd.text.startswith(f"{caveat['sentence']} {LINE}") and fits_approval(fd.text)
    assert "You should walk through" not in fd.text


def test_ensure_never_drops_model_sentences():
    long = " ".join(f"Weed the field well, round {i}." for i in range(40))
    text, notes = fr.ensure_safety_line(long, PS)
    assert text == f"{LINE} {long}" and not dropped_notes(notes)  # too long, but left whole for check() to reject
    assert any("over" in p for p in fr.check(text, llm.stub_draft("q", PS, [])))


# --- 2. the approval endpoint's SMS limit ---

def test_unicode_text_uses_the_268_character_sms_limit_on_the_rule_path():
    # One Twi letter (ɔ) makes the whole SMS Unicode: 4 parts is 268 characters, not 612.
    # Since fix/run5-findings (run 6 bug 1) an advice sentence with the ɔ is dropped when the GSM-7 text keeps more
    # advice, so the ɔ is in the zone caveat here (always kept), which makes the Unicode limit unavoidable.
    draft = llm.stub_draft(KINTAMPO, PS, []).replace("once they occur.", "once they occur in Kɔforidua.")
    fd = fr.propose(draft, KINTAMPO, zone_caveat=fr.zone_caveat("Kɔforidua"), passages=PS)
    m = sms.measure(fd.text)
    assert m.encoding == "UCS-2" and m.units <= 268 < 600, (m, fd.text)
    assert sms.length_prompt(fd.text) is None
    assert LINE in fd.text and dropped_notes(fd.problems)


def test_unicode_model_sms_over_268_is_rejected_not_proposed(monkeypatch):
    model = ("Walk through your maize field in Kɔforidua at least once a week and look for insect damage on leaves, "
             "cobs or stems. Rotate maize with groundnut to reduce armyworm.")
    text = f"{LINE} {model}"
    assert sms.measure(text).encoding == "UCS-2" and 268 < len(text) <= fr.MAX_CHARS
    assert any("too long for SMS" in p for p in fr.check(text, llm.stub_draft("q", PS, [])))
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (model, "llm:fake"))
    fd = fr.propose("\n".join(llm.stub_draft("q", PS, []).splitlines()[1:]), "q", passages=PS)
    assert any(p.startswith("model rewrite rejected") and "too long for SMS" in p for p in fd.problems), fd.problems
    assert fd.mode == "rule" and fd.text.startswith(LINE) and fits_approval(fd.text)


def test_every_proposal_fits_the_approval_limit_with_fewer_parts(monkeypatch):
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "2")  # 306 GSM-7 characters
    fd = fr.propose(llm.stub_draft(KINTAMPO, PS, []), KINTAMPO, zone_caveat=fr.zone_caveat("Kintampo"), passages=PS)
    assert fd.text.startswith(fr.zone_caveat("Kintampo")["sentence"] + " " + LINE)
    assert sms.measure(fd.text).segments <= 2 and sms.length_prompt(fd.text) is None


# --- 4 and 5. caveat, then the line, then advice; dropped advice is named ---

@pytest.mark.parametrize("q,place", [(KINTAMPO, "Kintampo"), (ASHANTI, "Ashanti")])
@pytest.mark.parametrize("limit", [None, 340])
def test_southern_pesticide_question_caveat_then_line_then_advice(monkeypatch, q, place, limit):
    if limit:
        monkeypatch.setattr(fr, "MAX_CHARS", limit)  # forces advice to be dropped
    out = run(q)
    fd = out["farmer_draft"]
    caveat = fd["zone_caveat"]["sentence"]
    assert out["zone_mismatch"] and place in caveat
    assert fd["text"].startswith(f"{caveat} {LINE}"), fd["text"]
    assert fits_approval(fd["text"])
    rest = fd["text"][len(f"{caveat} {LINE}"):].strip()
    assert rest, "some advice is kept"
    for note in dropped_notes(fd["problems"]):
        assert caveat not in note and LINE not in note  # only advice is ever dropped
    if limit:
        assert dropped_notes(fd["problems"])


def test_officer_note_names_every_dropped_sentence():
    out = run(KINTAMPO)
    fd = out["farmer_draft"]
    notes = dropped_notes(fd["problems"])
    assert len(notes) == 1, fd["problems"]
    dropped = "Proper weeding of maize fields also helps to reduce infestations."
    assert dropped not in fd["text"] and f"'{dropped}'" in notes[0], notes


def test_rule_rewrite_cut_is_also_named(monkeypatch):
    # Without a safety passage too: any sentence left out to fit is named, never cut mid-sentence.
    ids = ["APNI-SARI-2023-MAIZE:p22-sacks", "APNI-SARI-2023-MAIZE:p22-drying", "APNI-SARI-2023-MAIZE:p22-shelling"]
    ps = [knowledge.reference(i) for i in ids]
    monkeypatch.setattr(fr, "MAX_CHARS", 200)
    fd = fr.propose(llm.stub_draft("q", ps, []), "q", passages=ps)
    kept = fr._sentences(fd.text)
    note = " ".join(dropped_notes(fd.problems))
    assert fd.text and len(fd.text) <= 200 and note
    for p in ps:
        for s in fr._sentences(p["text"]):
            assert s in kept or f"'{s}'" in note, s  # each sentence is either sent whole or named as dropped


# --- 3. claim 1: added at proposal time only; what is approved is what is sent ---

def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def sms_case(c):
    r = c.post("/channels/simulator/inbound", data={"sender": SENDER, "text": KINTAMPO})
    assert r.status_code == 200
    return r.json()["case_id"]


def test_proposed_sms_in_the_officer_queue_already_has_the_line():
    c, h = TestClient(app), officer()
    cid = sms_case(c)
    case = next(x for x in c.get("/officer/queue", headers=h).json() if x["id"] == cid)
    assert case["farmer_draft"]["text"].count(LINE) == 1
    assert case["farmer_draft"]["text"] == c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]


def test_approved_text_is_sent_byte_for_byte_and_never_re_proposed(monkeypatch):
    c, h = TestClient(app), officer()
    cid = sms_case(c)
    text = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]

    def must_not_run(*a, **k):
        raise AssertionError("ensure_safety_line ran at approval/send time")
    monkeypatch.setattr(fr, "ensure_safety_line", must_not_run)
    monkeypatch.setattr(fr, "propose", must_not_run)
    d = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "confirmed": True, "farmer_text": text}).json()
    assert d["status"] == "released" and d["delivery"]["ok"], d
    assert not any("safety line" in w for w in d["warnings"]), d["warnings"]
    phone = simulator.SimulatorChannel().messages(SENDER)[-1]["text"]
    view = c.get(f"/farmer/cases/{cid}").json()["answer"]
    record = db.get_case(db.connect(), cid)["farmer_text"]
    assert phone.encode() == view.encode() == record.encode() == text.encode()


def test_officer_who_removes_the_line_is_warned_and_it_is_not_put_back(monkeypatch):
    c, h = TestClient(app), officer()
    cid = sms_case(c)
    text = c.get(f"/officer/cases/{cid}", headers=h).json()["farmer_draft"]["text"]
    edited = " ".join(s for s in fr._sentences(text) if not fr.SAFETY_RE.search(s))
    assert not fr.SAFETY_RE.search(edited)
    monkeypatch.setattr(fr, "ensure_safety_line", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    d = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "confirmed": True, "farmer_text": edited}).json()
    assert d["status"] == "released"
    assert any("drops the pesticide safety line" in w for w in d["warnings"]), d["warnings"]
    log = c.get(f"/officer/cases/{cid}", headers=h).json()["log"]
    assert any("drops the pesticide safety line" in str(e) for e in log)
    phone = simulator.SimulatorChannel().messages(SENDER)[-1]["text"]
    assert phone == edited and LINE not in phone and c.get(f"/farmer/cases/{cid}").json()["answer"] == edited
