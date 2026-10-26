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
    r = c.post(f"/officer/cases/{cid}/decision", headers=h, json=({
        "decision": "approve", "confirmed": True,
        "farmer_text": "Dispose of the mouldy maize. Do not feed it to animals."}) | {"expected_revision": db.connect().execute("SELECT revision FROM cases WHERE id=?", (cid,)).fetchone()[0]})
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["outcome"] in ("safety_blocked", "review_required")
    assert db.get_case(db.connect(), cid)["status"] == "pending_review"
    assert TestClient(app).get(f"/farmer/cases/{cid}").json()["answer"] is None


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


def test_abbreviation_before_source_name_is_not_split():
    # 6 of 6 window approvals in the live run warned on a split-off "(MoFA)." fragment
    assert fr._sentences("Plant from late June to early Sept. (MoFA). Weed after two weeks.") == [
        "Plant from late June to early Sept. (MoFA).", "Weed after two weeks."]
    assert fr._sentences("Harvest in Oct. Dry the pods first.") == ["Harvest in Oct.", "Dry the pods first."]


def test_saying_i_do_not_know_is_not_an_unsourced_claim():
    p = [{"id": "P1", "text": "Plant soybean from late June to early September in the Northern Region."}]
    for s in ("I do not know.", "I don't know.", "I am not sure."):
        assert fr.sms_claims(s, p) == []
        assert fr.sms_claims(s, []) == []
    assert fr.sms_claims("I do not know, but plant in 2019.", []) != []


F1_OFFICER = (
    '- "It is recommended to have a walk through the maize field at least once a week. When scouting, walk through '
    'the field and look out for unusual patterns such as insect damage on leaves, cobs or stems, presence of insect '
    'larvae or eggs on maize leaves, abnormal leaf colour, and stunted slow growing plants." [APNI-SARI-2023-MAIZE:p18-scouting]\n'
    '- "Rotate maize with non-host plants such as groundnut to help reduce Fall Army worm infestations. Deep ploughing '
    'and burial, or burning of infested maize residues helps to reduce populations in the following season." '
    '[APNI-SARI-2023-MAIZE:p20-faw-prevention]\n'
    '- "Application of recommended pesticides can help to control infestations once they occur. Consult your local AEA '
    'for advice on the recommended fall army worm control pesticide in your area." [APNI-SARI-2023-MAIZE:p20-faw-control]\n'
    "Note: Chemical use: AgriReach does not recommend products or doses. Refer to the label and the officer.")


def test_rule_text_keeps_the_pesticide_line_even_when_space_runs_out():
    # F1 in the live run: the SMS filled up with scouting advice and dropped "Consult your local AEA ..."
    text = fr.rule_rewrite(F1_OFFICER, 400)
    assert "Consult your local AEA" in text and len(text) <= 400


def test_model_text_that_drops_the_pesticide_line_is_rejected():
    text = "Walk through your maize field once a week and look for worms or eggs on the leaves."
    assert any("pesticide" in p for p in fr.check(text, F1_OFFICER))
    assert not any("pesticide" in p or "officer" in p for p in fr.check(
        text + " Ask your local AEA which pesticide to use against fall army worm.", F1_OFFICER))


def test_rainfall_record_is_not_a_source_for_farmer_text():
    # EJ1 live: the SMS judge accepted rainfall figures because the RAINFALL record was among the case's passages,
    # though rainfall figures are officer-only and the SMS dropped the "model estimate" caveat.
    p = [{"id": "RAINFALL-OPEN-METEO:ejura-2026-10", "source_id": "RAINFALL-OPEN-METEO", "kind": "record", "text": "Open-Meteo model estimate, not a gauge reading: 24 of "
          "30 days with at least 1 mm, total 185.5 mm, 2026-09-25 to 2026-10-24."},
         {"id": "MOFA-MAIZE:p11", "source_id": "MOFA-MAIZE", "text": "Plant maize in the major season from mid-March to end of April."}]
    problems = fr.sms_claims("A rainfall record shows 24 of 30 days with at least 1 mm and a total of 185.5 mm.", p)
    assert problems, "rainfall figures must not be backed by the RAINFALL record in a farmer SMS"
