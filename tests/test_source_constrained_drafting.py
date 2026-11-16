"""t44: source-constrained drafting and retry, from the t43 live aflatoxin failure (no model calls).

Live (t43 case 1, Mistral Small 3.2 + Llama 3.3 judge): the writer wrote 'Store shelled grain in jute sacks lined with
polythene bags [p22-sacks].', dropping 'Well dried and shelled ... treated with recommended storage chemicals'. The
judge answered not_supported, 'Adds no condition'; the retry repeated the sentence; the case fell back to sources.
The fake judge returns that recorded verdict for a jute-sacks sentence without the storage-chemicals condition."""
import asyncio
import json

from agrireach import agent, claim_check, judge, knowledge, llm, safety_gate

Q = "How should I dry and store my maize in Tamale to avoid aflatoxin?"
D, SH, SA = "APNI-SARI-2023-MAIZE:p22-drying", "APNI-SARI-2023-MAIZE:p22-shelling", "APNI-SARI-2023-MAIZE:p22-sacks"
SACKS = "Well dried and shelled maize should be treated with recommended storage chemicals and stored in jute sacks lined with polythene bags."
REJECTED = "Store shelled grain in jute sacks lined with polythene bags"
HEAD = (f"Immediately after harvesting, cobs should be dried so as to reduce the grain moisture content to about 10 to 12% "
        f"in readiness for storage [{D}]. Maize should be stored after removal of maize husks and shelling [{SH}]. ")
LIVE = HEAD + f"{REJECTED} [{SA}]."
FIXED = HEAD + f"{SACKS[:-1]} [{SA}]."


def writer(monkeypatch, replies):
    calls = []
    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append(feedback)
        return replies[min(len(calls) - 1, len(replies) - 1)], "llm:mistralai/mistral-small-3.2-24b-instruct"
    monkeypatch.setattr(llm, "draft", draft)
    return calls


def recorded_judge(monkeypatch):
    def call(user):
        items = [l for l in user.splitlines() if "SENTENCE:" in l]
        bad = lambda l: "jute sacks" in l and "storage chemicals" not in l
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "not_supported" if bad(l) else "supported",
                                         "why": "Adds no condition" if bad(l) else "Matches passage"} for i, l in enumerate(items)]})
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "meta-llama/llama-3.3-70b-instruct")
    monkeypatch.setattr(judge, "_call", call)


def test_passage_text_is_the_one_the_live_writer_shortened():
    assert next(p["text"] for p in knowledge.load()["passages"] if p["id"] == SA) == SACKS


def test_live_failure_reproduced_rejected_twice_then_source_fallback(monkeypatch):
    calls = writer(monkeypatch, [LIVE, LIVE])
    recorded_judge(monkeypatch)
    out = asyncio.run(agent.run(Q, use_fetch=False))
    assert len(calls) == 2 and out["draft_mode"].startswith("stub(citation-check-fallback")
    assert [a["ok"] for a in out["citation_check"]["attempts"]] == [False, False]
    assert out["citation_check"]["attempts"][-1]["problems"] == [
        f"'{REJECTED} .' is not supported by its citation according to the judge model: Adds no condition"]


def test_retry_offers_the_complete_source_statement_as_the_only_replacement():
    ps = [p for p in knowledge.load()["passages"] if p["id"] in (D, SH, SA)]
    text = llm.retry_instructions([f"{REJECTED} ."], ps)
    assert f"Rejected: '{REJECTED}.'" in text and f'"{SACKS}" [{SA}]' in text
    assert "Keep every other statement exactly" in text and "referral line" in text and "choice sentence" in text
    assert llm.retry_instructions(["Use neem leaves in the store."], ps).endswith("No passage states it: delete it; do not reword it.")


def test_closest_statement_needs_half_the_content_words():
    ps = [{"id": "X:p1", "text": "Weed the field at 3 weeks. Apply fertilizer after weeding."}]
    assert llm.closest_source_statement("Weed the field early", ps) == ("X:p1", "Weed the field at 3 weeks.")
    assert llm.closest_source_statement("Spray the crop with a strong chemical now", ps) is None


def test_writer_that_follows_the_retry_is_accepted_with_the_condition_kept(monkeypatch):
    calls = writer(monkeypatch, [LIVE, FIXED])
    recorded_judge(monkeypatch)
    out = asyncio.run(agent.run(Q, use_fetch=False))
    assert out["draft_mode"].startswith("llm:") and out["citation_check"]["ok"]
    assert "treated with recommended storage chemicals" in out["draft"] and "Well dried and shelled" in out["draft"]
    assert any(REJECTED in f for f in calls[1])


def test_verbatim_statement_still_goes_through_every_layer_of_the_unchanged_check():
    sent = []
    def call(user):
        items = [l for l in user.splitlines() if "SENTENCE:" in l]
        sent.extend(items)
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(len(items))]})
    ps = [p for p in knowledge.load()["passages"] if p["id"] in (D, SH, SA)]
    res = claim_check.check_claims(FIXED, ps, judge=True, judge_call=call)
    assert res.ok and len(sent) == 3          # verbatim copies are still judged: no new exemption


def test_prompt_is_source_constrained_and_keeps_every_safety_rule():
    s = llm.SYSTEM
    for must in ("Copy each statement word for word", "do not paraphrase", "Keep every condition and qualification",
                 "treated with recommended storage chemicals", "never add a product, dose, timing or method",
                 "Never prescribe pesticide/herbicide products or doses", "never confirm a disease diagnosis",
                 "Do not write your own warnings, refusals", "copy the exact choice sentence", "do not pick one"):
        assert must in s, must
    assert "Plain language, at most 150 words" not in s
    assert agent.MAX_DRAFT_ATTEMPTS == 2


def test_copied_storage_chemicals_line_still_needs_the_officer_safeguard_at_approval():
    ps = [p for p in knowledge.load()["passages"] if p["id"] in (D, SH, SA)]
    r = safety_gate.assess(SACKS, ps, language="en", question=Q).to_dict()
    assert r["outcome"] != "pass" and any(f["rule_id"] == "S1" for f in r["findings"])
