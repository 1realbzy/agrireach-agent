"""Offline reproductions of the EVALS.md task 10/11/12 failure modes (no network, no real model)."""
import asyncio

from agrireach import agent, db, llm
from tests.test_citation_check import TASK10_DRAFT, TASK11_DRAFT

run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))
GOOD_WA = ("APNI-SARI gives mid-June to late July [APNI-SARI-2023:p11-planting-window]. "
           "IITA gives mid-June to mid-July [IITA-SSPING-2022:p18-planting-window]. The officer should choose. "
           "Planting depth: about 5 cm deep with 15 cm between holes [APNI-SARI-2023:p11-depth]; "
           "or 3 cm, not deeper than 5 cm [IITA-SSPING-2022:p18-depth]. "
           "Spacing within rows: 15 cm [APNI-SARI-2023:p11-spacing] or 10 cm [IITA-SSPING-2022:p17-spacing].")


def fake_llm(monkeypatch, replies):
    calls = []

    def draft(question, passages, notes, conflicts=None, feedback=None):
        calls.append({"feedback": feedback, "conflicts": sorted(conflicts or {})})
        return replies[min(len(calls) - 1, len(replies) - 1)], "llm:fake"
    monkeypatch.setattr(llm, "draft", draft)
    return calls


def test_wa_retrieval_includes_every_side_of_each_conflict():
    out = run("When should I plant soybean at Wa?")
    assert {"APNI-SARI-2023:p11-planting-window", "IITA-SSPING-2022:p18-planting-window",
            "APNI-SARI-2023:p11-depth", "IITA-SSPING-2022:p18-depth"} <= set(out["sources"])
    assert any("planting window" in r for r in out["urgent_reasons"])
    assert any("planting depth" in r for r in out["urgent_reasons"])
    assert out["citation_check"]["ok"]  # stub draft quotes passages verbatim


def test_task11_bad_draft_is_regenerated_with_feedback(monkeypatch):
    calls = fake_llm(monkeypatch, [TASK11_DRAFT, GOOD_WA])
    out = run("When should I plant soybean at Wa?")
    assert len(calls) == 2 and calls[1]["feedback"]
    assert "planting_window" in calls[0]["conflicts"]
    assert out["draft"] == GOOD_WA and out["citation_check"]["ok"]
    assert out["citation_check"]["attempts"][0]["ok"] is False
    assert out["status"] == "pending_review"  # still needs the officer


def test_task11_persistent_failure_falls_back_and_flags_officer(monkeypatch):
    fake_llm(monkeypatch, [TASK11_DRAFT])
    out = run("When should I plant soybean at Wa?")
    assert out["priority"] == "urgent" and out["status"] == "pending_review"
    assert any(r.startswith("citation check failed") for r in out["urgent_reasons"])
    assert out["draft"].startswith(llm.STUB_LABEL) and "mid-June and late July" in out["draft"]
    assert out["citation_check"]["rejected_draft"] == TASK11_DRAFT
    assert out["draft_mode"].startswith("stub(citation-check-fallback")
    con = db.connect()
    row = db.get_case(con, out["case_id"])
    assert "citation check failed" in row["urgent_reasons"] and row["status"] == "pending_review"


def test_task10_miscount_draft_rejected(monkeypatch):
    fake_llm(monkeypatch, [TASK10_DRAFT])
    out = run("When should I plant soybean in Kumasi?")
    assert any("corpus covers Northern Ghana only" in r for r in out["urgent_reasons"])
    assert any(r.startswith("citation check failed") for r in out["urgent_reasons"])
    assert TASK10_DRAFT not in out["draft"]


def test_task12_twi_question_routed_to_officer_not_english_clarification():
    out = run("Bere ben na menndua soya wo Tamale?")
    assert out["language"] == "twi" and out["crop"] == "soybean" and out["region"] == "tamale"
    assert not out["clarification"] and out["status"] == "pending_review" and out["priority"] == "urgent"
    assert any("Twi" in r for r in out["urgent_reasons"])
    assert "APNI-SARI-2023:p11-planting-window" in out["sources"]
    assert "must reply in Twi" in out["draft"]


def test_twi_without_region_still_goes_to_officer():
    out = run("Bere ben na menndua soya?")
    assert out["status"] == "pending_review" and not out["clarification"]
    assert any("officer should ask" in r for r in out["urgent_reasons"])


def test_english_question_not_detected_as_twi():
    out = run("When should I harvest my soybean? I farm near Tamale.")
    assert out["language"] == "en" and out["priority"] == "routine"


def test_task10_out_of_corpus_region_caveat_added_by_code(monkeypatch):
    fake_llm(monkeypatch, [GOOD_WA])
    out = run("When should I plant soybean in Kumasi?")
    assert out["citation_check"]["ok"]
    assert out["draft"].startswith("Caution: the curated sources cover Northern Ghana only")
    assert "Kumasi" in out["draft"].splitlines()[0]
