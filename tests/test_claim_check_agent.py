"""The claim check wired into the agent: same regenerate-then-fallback path as the figure check (offline)."""
import asyncio
import json

from agrireach import agent, judge, llm
from tests.test_claim_check import BOTH_AGREE
from tests.test_eval_failures import GOOD_WA as GOOD_TWI  # all three conflicts, each side with its own citation


def fake_llm(monkeypatch, replies):
    calls = []

    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append(feedback)
        return replies[min(len(calls) - 1, len(replies) - 1)], "llm:fake"
    monkeypatch.setattr(llm, "draft", draft)
    return calls




def test_agreement_claim_is_regenerated_with_feedback(monkeypatch):
    calls = fake_llm(monkeypatch, [GOOD_TWI + "\n" + BOTH_AGREE, GOOD_TWI])
    out = asyncio.run(agent.run("Bere ben na menndua soya wo Tamale?", use_fetch=False))
    assert len(calls) == 2 and any("cites only IITA" in f for f in calls[1])
    assert out["draft"].split("\n\n" + agent.OFFICER_FACT)[0] == GOOD_TWI and out["citation_check"]["ok"] and out["status"] == "pending_review"


def test_persistent_unsupported_claim_falls_back_to_verbatim_and_flags_officer(monkeypatch):
    fake_llm(monkeypatch, [GOOD_TWI + "\n" + BOTH_AGREE])
    out = asyncio.run(agent.run("Bere ben na menndua soya wo Tamale?", use_fetch=False))
    assert out["draft"].startswith(llm.STUB_LABEL) and out["priority"] == "urgent"
    assert any(r.startswith("citation check failed") and "cites only IITA" in r for r in out["urgent_reasons"])
    assert out["status"] == "pending_review"


def test_judge_flag_triggers_regeneration(monkeypatch):
    # The "still worth applying" sentence this test used is now caught by code (late-timing layer), so the judge path
    # is exercised with a claim only the judge can catch.
    f5 = ("Top dressing gives the same result at any time after planting. The best time for "
          "top-dressing is at 6 weeks after planting [APNI-SARI-2023-MAIZE:p13-topdress-timing].")
    good = "The best time for top-dressing is at 6 weeks after planting [APNI-SARI-2023-MAIZE:p13-topdress-timing]."
    calls = fake_llm(monkeypatch, [f5, good])
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "fake-judge")

    def fake_judge(user):
        n = user.count("SENTENCE:")
        bad = "any time after planting" in user
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "not_supported" if bad and i == 0 else "supported",
                                         "why": "adds claim"} for i in range(n)]})
    monkeypatch.setattr(judge, "_call", fake_judge)
    out = asyncio.run(agent.run("Subsidised fertiliser arrived when the maize is knee-high, about two months after "
                                "planting. Is it still worth applying?", use_fetch=False))
    assert len(calls) == 2 and any("judge model" in f for f in calls[1])
    assert out["draft"].split("\n\n" + agent.OFFICER_FACT)[0] == good and out["citation_check"]["ok"]
    assert out["citation_check"]["attempts"][0]["judge"]["model"] == "fake-judge"


def test_stub_drafts_are_never_sent_to_the_judge(monkeypatch):
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "fake-judge")
    monkeypatch.setattr(judge, "_call", lambda u: (_ for _ in ()).throw(AssertionError("judge called")))
    out = asyncio.run(agent.run("When should I plant soybean at Wa?", use_fetch=False))
    assert out["citation_check"]["ok"] and "judge" not in out["citation_check"]["attempts"][0]
