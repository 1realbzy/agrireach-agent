"""Writer-prompt and retry-feedback corrections for the live citation-check fallbacks (cases 12/13, DIAGNOSIS R1/R2).

The deterministic checks, the judge, the safety gate and the attempt count are unchanged; only what the writer is asked
to produce changes. Old live wording must still be rejected."""
from types import SimpleNamespace

from agrireach import agent, claim_check, llm


def test_attempt_count_unchanged():
    assert agent.MAX_DRAFT_ATTEMPTS == 2


def test_code_built_choice_sentences_are_existing_exempt_shapes():
    for key in ("maize_planting_window", "maize_planting_window_major_season", "planting_window", "planting_depth",
                "plant_spacing", "seed_rate", "something_else"):
        s = llm.choice_sentence(key)
        assert claim_check.not_judged(s), (key, s)
    assert llm.choice_sentence("maize_planting_window") == "The officer should choose which planting window to follow."


def test_old_live_wording_is_still_rejected_by_the_unchanged_checker():
    assert not claim_check.not_judged("Choose the window that best fits your local conditions.")
    assert not claim_check.not_judged("Choose the planting window that best fits your local conditions and variety.")


def test_conflict_block_gives_the_exact_choice_sentence_once():
    g = [{"id": "A:p1", "text": "plant in June"}, {"id": "B:p2", "text": "plant in July"}]
    block = llm._conflict_block({"maize_planting_window": g, "maize_planting_window_major_season": g})
    assert block.count("The officer should choose which planting window to follow.") == 1


def test_prompt_keeps_safety_rules_and_forbids_own_refusals_and_copied_notes():
    s = llm.SYSTEM
    assert "Never prescribe pesticide/herbicide products or doses and never confirm a disease diagnosis." in s
    assert "Do not write your own warnings, refusals" in s and "referral line" in s
    assert "do not copy or restate them" in s
    assert "Say the officer should choose." not in s   # the open-ended instruction that produced case 12's sentence


def _capture(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1"); monkeypatch.setenv("LLM_MODEL", "fake")
    seen = {}
    def create(role, model, client, **kw):
        seen["msg"] = kw["messages"][1]["content"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="x"))])
    monkeypatch.setattr(llm, "create", create)
    return seen


def test_retry_feedback_names_each_rejected_sentence_for_deletion(monkeypatch):
    seen = _capture(monkeypatch)
    fb = ["'Choose the window that best fits your local conditions.' is not supported by its citation according to the judge model: No source",
          "'Do not mix insecticides or use double the label dose.' is not supported by its citation ['A:p1'] (no shared content words)",
          "'Plant early.' has no citation and is not supported by any cited passage (no shared content words)",
          "planting window: draft gives 5 cm but [A] says 3 cm"]
    llm.draft("q", [{"id": "A:p1", "text": "t"}], [], feedback=fb)
    tail = seen["msg"].split("Delete each of these sentences completely", 1)[1]
    for s in ("Choose the window that best fits your local conditions.", "Do not mix insecticides or use double the label dose.",
              "Plant early."):
        assert f"- {s}" in tail
    assert "5 cm" not in tail


def test_first_attempt_has_no_deletion_list(monkeypatch):
    seen = _capture(monkeypatch)
    llm.draft("q", [{"id": "A:p1", "text": "t"}], [])
    assert "Delete each of these sentences" not in seen["msg"]
