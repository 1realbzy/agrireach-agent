"""SMS length as an officer approval prompt (before approval), not only a send-time refusal. Offline; mocked HTTP.

Texts used, all from the repo, nothing invented:
- TWI_QUESTION: the Twi Ejura question, tests/test_search_variants.py.
- EJURA_SMS: AgriReach's proposed farmer text for "When should I plant maize in Ejura?" (offline pipeline at 4911f96).
The repo has no Twi farmer reply (Twi replies are officer-written; the Twi eval case is a native-speaker placeholder),
so the long Twi-script reply below is the officer quoting the farmer's Twi question above the English answer.
"""
import asyncio
from urllib.parse import parse_qs, urlencode

import httpx
from fastapi.testclient import TestClient

from agrireach import api, db, farmer_reply
from agrireach.channels import service, sms
from tests.test_sms import CFG, FARMER, FakeAT, TWI_QUESTION, callback

EJURA_SMS = ("In the transition zone, plant major-season maize from mid-March to end of April (MoFA). In the transition "
             "zone, plant major-season maize from end of March to end of April (IITA). In the transition zone, plant "
             "minor-season maize from mid July through August to early Sept. (MoFA). In the transition zone, plant "
             "minor-season maize from mid of July to early September (IITA). It is recommended to plant after three "
             "good rains within the planting window to ensure enough soil moisture to support germination and early "
             "growth. Your extension officer will confirm which to follow.")
TWI_REPLY = f"{TWI_QUESTION} {EJURA_SMS}"   # 609 characters, Unicode because of ɛ: 10 parts


def test_prompt_wording_and_numbers_for_a_long_twi_reply():
    assert len(TWI_REPLY) == 609
    assert sms.length_prompt(TWI_REPLY, 4) == (
        "too long for SMS: this text needs 10 parts (Unicode because of ɛ); the limit is 4. "
        "Shorten it to 268 characters or fewer before approving (it is 609 now). Nothing is cut automatically.")


def test_no_prompt_for_short_twi_or_a_4_part_english_reply():
    assert sms.length_prompt(TWI_QUESTION, 4) is None                      # 1 part, Unicode
    assert sms.measure(EJURA_SMS) == sms.Length("GSM-7", 574, 4, ())
    assert sms.length_prompt(EJURA_SMS, 4) is None
    assert sms.length_prompt("a" * 612, 4) is None                          # 4 x 153, exactly at the limit
    assert "needs 5 parts (standard SMS characters)" in sms.length_prompt("a" * 613, 4)
    assert "Shorten it to 160 characters or fewer" in sms.length_prompt("a" * 161, 1)


def test_one_curly_apostrophe_makes_a_4_part_english_reply_too_long():
    p = sms.length_prompt(EJURA_SMS.replace("It is", "It’s"), 4)
    assert p.startswith("too long for SMS: this text needs 9 parts (Unicode because of ’)")


def test_limit_fact_is_plain_and_follows_the_setting(monkeypatch):
    assert sms.limit_fact() == ("SMS limit for this farmer: 4 parts, which is 612 characters of standard text, or 268 "
                                "if the text has any Twi, Ga, Ewe or Dagbani letter (ɛ ɔ ŋ ɣ), curly quote or emoji")
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "2")
    assert sms.max_parts() == 2 and "2 parts, which is 306 characters" in sms.limit_fact()
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "nonsense")
    assert sms.max_parts() == 4


# --- in the officer workflow ------------------------------------------------------------------------------------

def _sms_case(question="When should I plant maize in Ejura?"):
    ch = sms.SmsChannel(CFG, httpx.Client(transport=httpx.MockTransport(FakeAT())))
    res = asyncio.run(sms.process(CFG, [sms.parse(urlencode(callback(question)).encode())], channel=ch))
    return res[0]["case_id"]


def _officer():
    tok = db.add_officer(db.connect(), "Ama Mensah")
    return {"Authorization": f"Bearer {tok}"}


def test_sms_case_shows_the_limit_and_no_prompt_when_the_proposal_fits():
    cid = _sms_case()
    fd = api._case(db.get_case(db.connect(), cid))["farmer_draft"]
    assert fd["text"] == EJURA_SMS and fd["sms_limit"] == sms.limit_fact()
    assert not any(p.startswith("too long for SMS") for p in fd["problems"])
    assert any(p.startswith("season check") for p in fd["problems"])     # existing prompts kept


def test_sms_case_proposal_already_fits_a_lower_part_limit(monkeypatch):
    # Since fix/sms-safety-guarantee-2 (QA): the proposal uses the approval endpoint's own limit
    # (farmer_reply.sms_length_problem), so a proposed text can never be refused for length at approval. Whole
    # sentences are dropped from the end and named for the officer; nothing is cut mid-sentence. Officer edits are
    # still only prompted, never cut (test_officer_edit_is_checked_...).
    monkeypatch.setenv("SMS_MAX_SEGMENTS", "3")
    cid = _sms_case()
    fd = api._case(db.get_case(db.connect(), cid))["farmer_draft"]
    assert sms.length_prompt(fd["text"]) is None and sms.measure(fd["text"]).segments <= 3
    assert not any("too long" in p for p in fd["problems"])
    note = next(p for p in fd["problems"] if "dropped to fit" in p)
    assert fd["text"].endswith("Your extension officer will confirm which to follow.")  # never dropped
    kept = farmer_reply._sentences(fd["text"])
    for s in farmer_reply._sentences(EJURA_SMS):
        assert s in kept or f"'{s}'" in note, s  # each sentence is sent whole or named as dropped
    # Re-propose gives the same fitted text, and the officer still sees the limit.
    c = TestClient(api.app)
    r = c.post(f"/officer/cases/{cid}/farmer-draft", json={"officer_text": db.get_case(db.connect(), cid)["draft"]},
               headers=_officer()).json()
    assert r["text"] == fd["text"] and not any("too long" in p for p in r["problems"])
    assert r["sms_limit"].startswith("SMS limit for this farmer: 3 parts, which is 459 characters")


def test_non_sms_cases_get_no_sms_prompt():
    out = asyncio.run(service.handle_inbound(service.InboundMessage("simulator", "sim:farmer-1",
                                                                    text="When should I plant maize in Ejura?")))
    fd = api._case(db.get_case(db.connect(), out["case_id"]))["farmer_draft"]
    assert "sms_limit" not in fd and not any("SMS" in p for p in fd["problems"])
    r = TestClient(api.app).post(f"/officer/cases/{out['case_id']}/sms-check", json={"farmer_text": TWI_REPLY},
                                 headers=_officer()).json()
    assert r == {"channel": "simulator", "prompt": None}


def test_officer_edit_is_checked_and_an_overlong_approval_is_refused_before_anything_is_saved():
    cid = _sms_case("Me te Ejura, mɛdua aburo bere bɛn?")
    h, c = _officer(), TestClient(api.app)
    chk = c.post(f"/officer/cases/{cid}/sms-check", json={"farmer_text": TWI_REPLY}, headers=h).json()
    assert chk["prompt"] == sms.length_prompt(TWI_REPLY, 4) and chk["parts"] == 10 and chk["limit"] == 4
    assert chk["encoding"] == "Unicode"
    ok = c.post(f"/officer/cases/{cid}/sms-check", json={"farmer_text": TWI_QUESTION}, headers=h).json()
    assert ok["prompt"] is None and ok["parts"] == 1
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json=({"decision": "approve", "farmer_text": TWI_REPLY, "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    assert r.status_code == 422 and r.json()["detail"]["reason"] == sms.length_prompt(TWI_REPLY, 4)
    row = db.get_case(db.connect(), cid)
    assert row["status"] == "pending_review" and not row["farmer_text"]          # not approved, still editable
    r = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json=({"decision": "approve", "farmer_text": TWI_QUESTION, "confirmed": True}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    # Length fitting does not establish language safety: Twi remains held for review.
    assert r.status_code == 422 and r.json()["detail"]["outcome"] == "review_required"
    assert db.get_case(db.connect(), cid)["farmer_text"] is None
