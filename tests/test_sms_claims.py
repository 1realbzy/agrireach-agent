"""Review item (F7/F9/F4/F11, QA's mouldy-maize approval): every sentence of the farmer SMS is checked against the
case's sources. A model-written SMS that fails fails closed (rule-based version instead); an officer who approves
such a text is warned and it is logged, not blocked (the officer is the human authority)."""
import json

from fastapi.testclient import TestClient

from agrireach import db, farmer_reply as fr, judge, knowledge, llm
from agrireach.api import app

PS = [knowledge.reference("IITA-SSPING-2022:p18-moisture")]


def judge_rejecting(word):
    seen = []

    def call(user):
        items = [l for l in user.splitlines() if ". SENTENCE: " in l]
        seen.extend(items)
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "not_supported" if word in l else "supported",
                                         "why": "not in the passage"} for i, l in enumerate(items)]})
    return seen, call


def test_unsupported_sms_sentence_is_a_problem():
    seen, call = judge_rejecting("Dispose")
    p = fr.sms_claims("Dispose of the mouldy maize. Plant when the rains are well established.", PS, judge_call=call)
    assert len(p) == 1 and "Dispose" in p[0]  # the lexical layer or the judge


def test_code_built_sentences_are_not_judged():
    seen, call = judge_rejecting("zzz")
    cav = fr.zone_caveat("Kumasi")
    text = f"{cav['sentence']} Plant when the rains are well established. {fr.CONFIRM}"
    assert fr.sms_claims(text, PS, judge_call=call, caveat=cav) == [] and len(seen) == 1


def test_judge_outage_fails_closed():
    def boom(_):
        raise TimeoutError("provider down")
    p = fr.sms_claims("Plant when the rains are well established.", PS, judge_call=boom)
    assert p and "couldn't run" in p[0]


def test_no_sources_means_every_sms_sentence_is_unsourced():
    assert fr.sms_claims("Contact your extension officer.", []) != []


def test_model_sms_with_an_unsupported_sentence_falls_back_to_rule_text(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: ("Dispose of the mouldy maize.", "llm:fake"))
    _seen, call = judge_rejecting("Dispose")
    monkeypatch.setattr(judge, "_call", call)
    officer = "Plant when the rains are well established [IITA-SSPING-2022:p18-moisture]."
    fd = fr.propose(officer, "When do I plant soybean?", passages=PS)
    assert fd.mode == "rule" and "Dispose" not in fd.text
    assert any("model rewrite rejected" in n and "Dispose" in n for n in fd.problems)


def test_model_sms_keeps_the_sources_differ_sentence(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: ("Plant when the rains are well established.", "llm:fake"))
    officer = "Plant when the rains are well established [IITA-SSPING-2022:p18-moisture]."
    fd = fr.propose(officer, "When do I plant soybean?", conflicts=True, passages=PS)
    assert fd.mode == "llm:fake" and fd.text.endswith(fr.CONFIRM)


def test_officer_approving_an_unsourced_sms_is_warned_and_logged_not_blocked(monkeypatch):
    _seen, call = judge_rejecting("Dispose")
    monkeypatch.setattr(judge, "_call", call)
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    c = TestClient(app)
    cid = c.post("/ask", json={"question": "My maize is mouldy, can I feed it to my animals in Tamale?"}).json()["case_id"]
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json={
        "decision": "approve", "confirmed": True,
        "farmer_text": "Dispose of the mouldy maize. Do not feed it to animals."})
    assert r.status_code == 200 and r.json()["status"] == "released"
    assert any("Dispose" in w for w in r.json()["warnings"])
    log = c.get(f"/officer/cases/{cid}", headers=h).json()["log"]
    assert any(e.get("tool") == "approval_warning" and "Dispose" in str(e) for e in log)


def test_unconfigured_judge_reads_plainly(monkeypatch):
    monkeypatch.setattr(judge, "_call", lambda _u: {}["LLM_BASE_URL"])
    p = fr.sms_claims("Plant when the rains are well established.", PS)
    assert p == ["source check couldn't run: no judge model is configured (set LLM_BASE_URL and LLM_API_KEY)"]


def test_mouldy_maize_sms_never_quotes_aflatoxin_limits_and_the_officer_writes_it():
    # GRER: a farmer can't measure ppb, and the offline text began mid-sentence ("aflatoxin limits imposed by...").
    import asyncio
    from agrireach import agent
    out = asyncio.run(agent.run("My maize is mouldy, can I feed it to my animals in Tamale?", use_fetch=False))
    assert "ppb" in out["draft"]  # the limit stays for the officer
    fd = out["farmer_draft"]
    assert "ppb" not in fd["text"] and not fd["text"][:1].islower()
    assert fd["needs_officer_text"] and fd["text"] == ""


def test_model_sms_quoting_a_limit_is_rejected():
    assert any("regulatory limit" in p for p in fr.check("Do not eat maize above 15 ppb of aflatoxin.",
                                                       "maize limit 15 ppb [AGBETIAMEH-2018:aflatoxin-limits]"))


def test_proposed_text_uses_plain_punctuation_so_sms_stays_gsm7(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: (
        "Plant when the rains are well established \u2014 that\u2019s when the soil is moist\u2026", "llm:fake"))
    officer = "Plant when the rains are well established [IITA-SSPING-2022:p18-moisture]."
    fd = fr.propose(officer, "When do I plant soybean?", passages=PS)
    assert fd.mode == "llm:fake" and fd.text == "Plant when the rains are well established - that's when the soil is moist..."
    assert all(ord(ch) < 128 for ch in fd.text)
