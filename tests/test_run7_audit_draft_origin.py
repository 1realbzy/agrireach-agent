"""Run 7 (docs/live-eval-2026-10-25-run7-final.md, item 2; Scoffer: "no fake runs"): the 'farmer_text_proposal' log
entry did not say whether the officer draft behind it came from the language model or from the code-built offline
stub (no model key, a failed model call, or the citation-check fallback). An auditor reading only the log could not
tell a real model run from a stub. The entry now carries draft_mode and offline_draft, and says so in its summary."""
import asyncio
import json

from agrireach import agent, db, farmer_reply as fr, judge, llm

Q = "When should I plant maize in Tamale?"
F1_Q = "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect."
DRAFT = "Scout the maize field at least once a week [APNI-SARI-2023-MAIZE:p18-scouting]."


def proposal(cid):
    [e] = [e for e in db.case_log(db.connect(), cid) if e["tool"] == "farmer_text_proposal"]
    return json.loads(e["args"]), e["result_summary"]


def test_offline_stub_draft_is_marked_in_the_proposal_log():
    out = asyncio.run(agent.run(Q, use_fetch=False))
    assert out["draft_mode"].startswith("stub")
    args, summary = proposal(out["case_id"])
    assert args["draft_mode"] == out["draft_mode"] and args["offline_draft"] is True
    assert "offline stub draft (no language model)" in summary


def test_failed_model_call_is_marked_as_offline(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("429 rate limited")
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(llm, "draft", boom)
    out = asyncio.run(agent.run(Q, use_fetch=False))
    args, _ = proposal(out["case_id"])
    assert args["draft_mode"] == "stub(llm-error)" and args["offline_draft"] is True


def supported(user):
    items = [l for l in user.splitlines() if ". SENTENCE: " in l]
    return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(len(items))]})


def test_model_draft_is_marked_as_a_model_run(monkeypatch):
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    monkeypatch.setattr(llm, "draft", lambda *a, **k: (DRAFT, "llm:fake"))
    monkeypatch.setattr(fr, "_llm_rewrite", lambda *a, **k: ("Check your maize field every week.", "llm:fake"))
    monkeypatch.setattr(judge, "_call", supported)
    out = asyncio.run(agent.run(F1_Q, use_fetch=False))
    assert out["draft_mode"] == "llm:fake", out["draft_mode"]
    args, summary = proposal(out["case_id"])
    assert args["draft_mode"] == "llm:fake" and args["offline_draft"] is False
    assert "offline" not in summary
