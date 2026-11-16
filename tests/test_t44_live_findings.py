"""t44 live comparison findings, replayed offline with the exact live draft texts (no model calls).

1. GPT-4o-mini added 'The officer should choose which planting window to follow.' to answers with no source conflict
   (3/3). That sentence is an exempt no-advice shape, so the unchanged claim check passed it. A deterministic check now
   rejects a choice sentence when code found no conflict; the retry says delete it.
2. Mistral prefixed the storage-chemicals statement with 'Finally,'; the copied farmer text was then not the source
   wording and the approval gate blocked it (S3, plus S1). The prompt now forbids connectors before chemical,
   treatment or referral statements; the gate is unchanged."""
import asyncio
import json

from agrireach import agent, judge, knowledge, llm, safety_gate

T, B, M = ("APNI-SARI-2023-MAIZE:p13-topdress-timing", "APNI-SARI-2023-MAIZE:p13-basal-timing",
           "APNI-SARI-2023-MAIZE:p13-topdress-moisture")
QF = "When and how should I apply fertilizer to my maize in Tamale?"
GPT_C1 = (f"The first fertilizer application (basal application) should be applied shortly after germination at about two "
          f"weeks after planting [{B}]. Also, the right time for application of top-dressing fertilizer is at 6 weeks after "
          f"planting [{T}]. Top dressing should be done when the soil is moist, to enhance the dissolving of applied "
          f"nutrients in the soil as this allows for faster uptake of nutrients [{M}]. If at 6 weeks after planting maize "
          f"the soil is very dry, delay the topdress fertilizer application until some rains are received [{M}]. "
          "The officer should choose which planting window to follow.")
STRAY = "The officer should choose which planting window to follow."


def writer(monkeypatch, replies):
    calls = []
    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append(feedback)
        return replies[min(len(calls) - 1, len(replies) - 1)], "llm:openai/gpt-4o-mini"
    monkeypatch.setattr(llm, "draft", draft)
    return calls


def supported_judge(monkeypatch):
    def call(user):
        n = sum("SENTENCE:" in l for l in user.splitlines())
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(n)]})
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "meta-llama/llama-3.3-70b-instruct")
    monkeypatch.setattr(judge, "_call", call)


def test_live_gpt_draft_with_a_stray_choice_sentence_is_now_rejected_then_fixed(monkeypatch):
    calls = writer(monkeypatch, [GPT_C1, GPT_C1.replace(" " + STRAY, "")])
    supported_judge(monkeypatch)
    out = asyncio.run(agent.run(QF, use_fetch=False))
    first = out["citation_check"]["attempts"][0]
    assert not first["ok"] and first["problems"] == [
        f"'{STRAY}' names a choice between sources, but no source conflict was found for this question"]
    assert out["citation_check"]["ok"] and out["draft_mode"].startswith("llm:") and STRAY not in out["draft"]
    assert len(calls) == 2 and calls[1] == first["problems"]


def test_retry_says_delete_for_a_stray_choice_sentence():
    ps = [p for p in knowledge.load()["passages"] if "planting" in p["topic"]]
    assert llm.retry_instructions([STRAY], ps).endswith(f"- Rejected: '{STRAY}'. No passage states it: delete it; do not reword it.")


def test_choice_sentence_is_still_allowed_when_code_found_a_conflict():
    assert llm.stray_choice_problems(STRAY, {"maize_planting_window": [{}]}) == []
    assert llm.stray_choice_problems("Plant after three good rains.", None) == []


def test_connector_before_a_chemical_statement_breaks_the_source_wording_the_gate_needs():
    ps = [p for p in knowledge.load()["passages"] if p["id"].startswith("APNI-SARI-2023-MAIZE:p22")]
    exact = "Well dried and shelled maize should be treated with recommended storage chemicals and stored in jute sacks lined with polythene bags."
    with_connector = "Finally, well dried and shelled maize should be treated with recommended storage chemicals and stored in jute sacks lined with polythene bags."
    rules = lambda t: {f["rule_id"] for f in safety_gate.assess(t, ps, language="en", question="store maize").to_dict()["findings"]}
    assert "S3" in rules(with_connector) and "S3" not in rules(exact)     # gate unchanged; the prompt avoids the connector
    assert "never before a statement about chemicals, pesticides, treatment or referral" in llm.SYSTEM
    assert "With no CONFLICTS section, write no sentence about choosing." in llm.SYSTEM
