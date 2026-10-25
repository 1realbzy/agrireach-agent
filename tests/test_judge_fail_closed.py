"""Review item 2: the model judge runs on every model draft, fails closed, and sees officer-addressed and uncited
sentences too. Offline: the judge's network call is replaced."""
import asyncio
import json

from agrireach import agent, claim_check, judge, knowledge, llm

TOP = knowledge.reference("APNI-SARI-2023-MAIZE:p13-topdress-timing")
MOIST = knowledge.reference("IITA-SSPING-2022:p18-moisture")
GOOD = "The best time for top-dressing is at 6 weeks after planting [APNI-SARI-2023-MAIZE:p13-topdress-timing]."


def recording_judge(verdict="supported"):
    seen = []

    def call(user):
        seen.append(user)
        n = user.count(". SENTENCE: ")
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": verdict, "why": "x"} for i in range(n)]})
    return seen, call


def test_judge_is_on_by_default_with_a_named_model(monkeypatch):
    monkeypatch.delenv("AGRIREACH_JUDGE_MODEL", raising=False)
    assert judge.enabled() and judge.model() == judge.DEFAULT_MODEL
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "other/model")
    assert judge.model() == "other/model"


def test_parse_takes_the_first_json_object_even_with_trailing_text():
    items = [("a", [MOIST])]
    raw = '{"verdicts": [{"n": 1, "verdict": "not_supported", "why": "x"}]}\nNote: {"also": 1}'
    assert judge.parse(raw, items)[0]["verdict"] == "not_supported"
    assert judge.parse('Here you go: ```json\n{"verdicts": [{"n": 1, "verdict": "supported"}]}\n```', items)


def test_judge_error_fails_the_check():
    def boom(_):
        raise TimeoutError("provider down")
    r = claim_check.check_claims(GOOD, [TOP], judge=True, judge_call=boom)
    assert not r.ok and r.judge_failed and "provider down" in r.judge["error"]
    assert any("source check couldn't run" in p for p in r.problems)


def test_unparseable_judge_reply_fails_the_check():
    r = claim_check.check_claims(GOOD, [TOP], judge=True, judge_call=lambda _u: "I think it's fine.")
    assert not r.ok and any("source check couldn't run" in p for p in r.problems)


def test_officer_addressed_sentence_is_sent_to_the_judge():
    seen, call = recording_judge("not_supported")
    d = ("The officer should tell the farmer the maize is safe to sell and needs no further fertilizer. "
         + GOOD)
    r = claim_check.check_claims(d, [TOP], judge=True, judge_call=call)
    assert "safe to sell" in seen[0] and not r.ok


def test_uncited_trailing_sentence_is_checked_against_the_cited_passages():
    # Lexical layer: shares nothing with any cited passage.
    d = GOOD + " This guarantees a bumper harvest."
    r = claim_check.check_claims(d, [TOP], judge=False)
    assert not r.ok and any("bumper harvest" in p for p in r.problems)
    # Judge layer: shares words, so only the judge can tell it adds a claim.
    seen, call = recording_judge("not_supported")
    d2 = GOOD + " Top-dressing later than 6 weeks after planting does no harm."
    r2 = claim_check.check_claims(d2, [TOP], judge=True, judge_call=call)
    assert "does no harm" in seen[0] and not r2.ok


def fake_llm(monkeypatch, reply):
    calls = []

    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append(feedback)
        return reply, "llm:fake"
    monkeypatch.setattr(llm, "draft", draft)
    return calls


def test_agent_falls_back_to_verbatim_and_flags_urgent_when_the_judge_cannot_run(monkeypatch):
    calls = fake_llm(monkeypatch, GOOD)
    monkeypatch.setattr(judge, "_call", lambda _u: (_ for _ in ()).throw(ConnectionError("no route")))
    out = asyncio.run(agent.run("When should I top dress my maize in Tamale?", use_fetch=False))
    assert out["draft"].startswith(llm.STUB_LABEL) and out["priority"] == "urgent"
    assert any("source check couldn't run" in r for r in out["urgent_reasons"])
    assert len(calls) == 1  # no point regenerating when the check itself is down


def test_agent_accepts_a_model_draft_the_judge_supports(monkeypatch):
    fake_llm(monkeypatch, GOOD)
    seen, call = recording_judge("supported")
    monkeypatch.setattr(judge, "_call", call)
    out = asyncio.run(agent.run("When should I top dress my maize in Tamale?", use_fetch=False))
    assert out["citation_check"]["ok"] and out["draft"].split("\n\n" + agent.OFFICER_FACT)[0] == GOOD and seen
