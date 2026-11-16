"""Live cases 12 and 13 (Nairobi AWS, 16 Nov 2026): deterministic reproduction of the live cases 12 and 13 citation-check fallbacks (no model calls).

The fake drafter returns the kind of draft Mistral-Small 3.2 wrote (the rejected sentences are copied from the live
urgent reasons). The fake judge returns the verdict Llama-3.3-70B gave live for the same sentence class
("Adds local conditions" / "No source"; docs/eval-run-2026-10-25-claims.txt) and 'supported' for everything else.
"""
import asyncio
import json

from agrireach import agent, claim_check, judge, knowledge, llm

QA = "Fall armyworm is attacking my maize near Tamale in the Northern Region. The plants are 5 weeks old. What should I do?"
QB = "Can I mix two insecticides together and use double the label dose to kill fall armyworm on my maize in Tamale faster?"
S, P, C, W = ("APNI-SARI-2023-MAIZE:p18-scouting", "APNI-SARI-2023-MAIZE:p20-faw-prevention",
              "APNI-SARI-2023-MAIZE:p20-faw-control", "APNI-SARI-2023-MAIZE:p5-planting-window")
CHOOSE_LIVE = "Choose the window that best fits your local conditions."
D12_BODY = (f"Walk through the maize field at least once a week and look for insect larvae and damage on leaves [{S}]. "
            f"Rotate maize with groundnut and weed the field properly to reduce Fall Army worm infestations [{P}]. "
            f"Consult your local AEA for advice on the recommended fall army worm control pesticide in your area [{C}].\n"
            f"Maize planting in the northern region should be done between early June and July 10th [{W}]. "
            "Major season in the Guinea/Sudan savannah is End of May-early July [MOFA-MAIZE:p12-guinea-sudan-major]. "
            "Major cropping season in the Guinea savannah is End of May - End of July [IITA-MAIZE-2025:p16-guinea-major]. ")
D12 = D12_BODY + CHOOSE_LIVE
REFUSAL_LIVE = "Do not mix insecticides or use double the label dose."
D13_BODY = (f"Rotate maize with groundnut and weed the field properly to reduce Fall Army worm infestations [{P}]. "
            f"Walk through the maize field at least once a week to look for larvae [{S}].\n")
D13 = D13_BODY + f"{REFUSAL_LIVE} [{C}]"


def fake_drafter(monkeypatch, replies):
    calls = []
    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append({"feedback": feedback, "conflicts": sorted(conflicts or {})})
        return replies[min(len(calls) - 1, len(replies) - 1)], "llm:mistralai/mistral-small-3.2-24b-instruct"
    monkeypatch.setattr(llm, "draft", draft)
    return calls


def llama_like_judge(monkeypatch):
    sent = []
    def call(user):
        items = [l for l in user.splitlines() if "SENTENCE:" in l]
        sent.extend(items)
        return json.dumps({"verdicts": [
            {"n": i + 1, "verdict": "not_supported" if "best fits your local conditions" in l else "supported",
             "why": "No source" if "best fits" in l else "Direct quote"} for i, l in enumerate(items)]})
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "fake-llama")
    monkeypatch.setattr(judge, "_call", call)
    return sent


QW = "When should I plant maize in the Northern Region?"
D12W_BODY = (f"Maize planting in the northern region should be done between early June and July 10th [{W}]. "
             "Major season in the Guinea/Sudan savannah is End of May-early July [MOFA-MAIZE:p12-guinea-sudan-major]. "
             "Major cropping season in the Guinea savannah is End of May - End of July [IITA-MAIZE-2025:p16-guinea-major]. ")
LIVE12_IDS = (S, P, C, W, "MOFA-MAIZE:p12-guinea-sudan-major", "IITA-MAIZE-2025:p16-guinea-major")


def test_case12_trigger_reproduced_with_the_baseline_scoring(monkeypatch):
    """d33ab46 scoring (place words counted): 'northern region' pulls the planting window into the pest question."""
    monkeypatch.setattr(knowledge, "GEO_STEMS", frozenset())
    with_region = [p["id"] for p in knowledge.search(QA, crop="maize")]
    without = [p["id"] for p in knowledge.search(QA.replace(" in the Northern Region", ""), crop="maize")]
    assert W in with_region and "MOFA-MAIZE:p12-guinea-sudan-major" in with_region   # overlap + conflict completeness
    assert W not in without


def test_case12_trigger_fixed_place_words_do_not_pull_planting_passages():
    with_region = [p["id"] for p in knowledge.search(QA, crop="maize")]
    without = [p["id"] for p in knowledge.search(QA.replace(" in the Northern Region", ""), crop="maize")]
    assert with_region == without == [S, P, C]


def test_case12_reproduced_exact_live_judge_rejection_on_the_live_passage_set(monkeypatch):
    """The live drafter saw these 6 passages; the choose sentence is judged and rejected with the live reason."""
    sent = llama_like_judge(monkeypatch)
    by_id = {p["id"]: p for p in knowledge.load()["passages"]}
    res = claim_check.check_claims(D12, [by_id[i] for i in LIVE12_IDS])
    assert not res.ok
    assert any(r.startswith("'Choose the window that best fits your local conditions.' is not supported by its "
                            "citation according to the judge model: No source") for r in res.problems)
    assert sum("best fits" in s for s in sent) == 1


def test_case12_choose_sentence_rejected_twice_in_the_agent_loop(monkeypatch):
    """A real planting-window conflict question still gets the conflict, and the invented choice line still fails
    both attempts (fallback to sources); the retry feedback quotes it so llm.draft can list it for deletion."""
    calls = fake_drafter(monkeypatch, [D12W_BODY + CHOOSE_LIVE] * 2)
    llama_like_judge(monkeypatch)
    out = asyncio.run(agent.run(QW, use_fetch=False))
    assert calls[0]["conflicts"] == ["maize_planting_window"]
    assert len(calls) == 2 and calls[0]["feedback"] is None
    assert any(f.startswith(f"'{CHOOSE_LIVE}' ") for f in calls[1]["feedback"])
    assert out["draft_mode"] == "stub(citation-check-fallback after llm:mistralai/mistral-small-3.2-24b-instruct)"
    assert [a["ok"] for a in out["citation_check"]["attempts"]] == [False, False]


def test_case12_only_the_choose_sentence_fails():
    assert not claim_check.not_judged(CHOOSE_LIVE)
    for exempt in ("The officer should choose which planting window to follow.",
                   "Choose the appropriate window based on local conditions.",
                   "Sources disagree on the planting window."):
        assert claim_check.not_judged(exempt), exempt


def test_case12_same_draft_with_an_exempt_choice_line_passes(monkeypatch):
    fake_drafter(monkeypatch, [D12W_BODY + llm.choice_sentence("maize_planting_window")])
    llama_like_judge(monkeypatch)
    out = asyncio.run(agent.run(QW, use_fetch=False))
    assert out["citation_check"]["ok"] and out["draft_mode"].startswith("llm:")


def test_case13_reproduced_refusal_fails_the_lexical_layer_before_the_judge(monkeypatch):
    calls = fake_drafter(monkeypatch, [D13, D13])
    llama_like_judge(monkeypatch)
    out = asyncio.run(agent.run(QB, use_fetch=False))
    assert len(calls) == 2 and any("no shared content words" in f for f in calls[1]["feedback"])
    assert out["draft_mode"].startswith("stub(citation-check-fallback")
    assert any(f"'{REFUSAL_LIVE}' is not supported by its citation ['{C}'] (no shared content words)" in r
               for r in out["urgent_reasons"])


def test_case13_moving_the_refusal_out_of_the_citation_still_fails(monkeypatch):
    fake_drafter(monkeypatch, [D13_BODY + REFUSAL_LIVE])
    llama_like_judge(monkeypatch)
    out = asyncio.run(agent.run(QB, use_fetch=False))
    assert any("has no citation and is not supported by any cited passage" in r for r in out["urgent_reasons"])


def test_case13_source_referral_instead_of_own_refusal_passes(monkeypatch):
    fake_drafter(monkeypatch, [D13_BODY + f"Consult your local AEA for advice on the recommended fall army worm "
                                          f"control pesticide in your area [{C}]."])
    llama_like_judge(monkeypatch)
    out = asyncio.run(agent.run(QB, use_fetch=False))
    assert out["citation_check"]["ok"] and out["draft_mode"].startswith("llm:")
