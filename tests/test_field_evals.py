"""The field-evidence eval set: well formed, placeholders not machine-translated, and every runnable eval's
routing expectations hold offline (stub mode). The real-model results are recorded in EVALS.md."""
import asyncio

import pytest

from agrireach import agent, evalset, knowledge

EVALS = evalset.load()


def test_set_has_the_14_research_questions_with_sources():
    assert [e["id"] for e in EVALS] == [f"F{i}" for i in range(1, 15)]
    for e in EVALS:
        assert e["research_expectation"] and e["sources"]
        assert all(url.split()[-1].startswith("https://") for url in e["sources"].values())
        assert e.get("skip") or e.get("kind") == "voice_script" or \
            (e["question"] and e["expect"]["outcome"] in {"pending_review", "clarify"})


def test_language_placeholders_are_skipped_and_have_no_invented_wording():
    for e in EVALS:
        if e["id"] in ("F12", "F13"):
            assert e["question"] is None and "native speaker" in e["skip"]


def test_expected_citations_exist_in_corpus():
    ids = {p["id"] for p in knowledge.load()["passages"]}
    for e in evalset.runnable(EVALS):
        for i in (e["expect"].get("cite_any") or []) + (e["expect"].get("cite_all") or []):
            assert i in ids, (e["id"], i)


@pytest.mark.parametrize("e", evalset.runnable(EVALS), ids=lambda e: e["id"])
def test_routing_expectations_hold_offline(e):
    out = asyncio.run(agent.run(e["question"], use_fetch=False))
    assert evalset.grade(e, out) == []


def test_grader_catches_forbidden_text_and_wrong_routing():
    e = next(x for x in EVALS if x["id"] == "F10")
    bad = {"status": "pending_review", "priority": "routine", "sources": [], "urgent_reasons": [],
           "draft": "Call Mr. Mensah on 024 123 4567."}
    problems = evalset.grade(e, bad)
    assert any("priority" in p for p in problems) and any("forbidden" in p for p in problems)
    assert any("how to reach" in p for p in problems)
