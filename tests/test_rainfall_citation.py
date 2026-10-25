"""Ejura planting drafts fell back in live runs (25 Oct 2026): the recorded draft was rejected because
(a) a '**Rainfall**:' heading counted as naming the RAINFALL-OPEN-METEO source, and (b) numbered-list markers
('1.', '2.', '3.') were checked as figures. Neither is a wrong claim. Also: the prompt says what the rainfall
record may be cited for."""
import asyncio
import json
from pathlib import Path

import pytest

from agrireach import agent, citation_check, claim_check, knowledge, llm, rainfall

FIX = Path(__file__).parent / "fixtures" / "rainfall"
RID = "RAINFALL-OPEN-METEO:ejura:2026-10-25"
run = lambda q, **k: asyncio.run(agent.run(q, use_fetch=False, **k))

# First model draft of live run B1 (e12846c, 25 Oct 2026), verbatim.
LIVE_EJURA = f"""To determine the planting time for maize in Ejura, consider the following:

1. **Planting Window**: The major season transition period is either from mid-March to end of April [MOFA-MAIZE:p11-transition-major] or from end of March to end of April [IITA-MAIZE-2025:p16-transition-major]. The minor season transition period is either from mid-July through August to early September [MOFA-MAIZE:p12-transition-minor] or from mid-July to early September [IITA-MAIZE-2025:p16-transition-minor]. The officer should choose which source to follow.

2. **Rainfall**: Plant after three good rains within the planting window to ensure enough soil moisture [IITA-MAIZE-2025:p15-three-good-rains]. A rainfall record is provided for Ejura from 2026-09-25 to 2026-10-24, but the guides do not specify a rainfall amount that marks onset, so the officer must decide if the condition is met [{RID}].

3. **Local Weather**: Planting time should also be informed by local weather information to avoid wilting [MOFA-MAIZE:p10-when-to-plant].

Ejura is near the edge of the transition zone, so the officer should confirm which zone's timing applies."""


@pytest.fixture
def ejura(monkeypatch):
    monkeypatch.setenv("AGRIREACH_RAINFALL_TODAY", "2026-10-25")
    r = rainfall.recent("Ejura", fetch=lambda url: json.loads((FIX / "open_meteo_ejura.json").read_text()))
    ids = ["IITA-MAIZE-2025:p15-three-good-rains", "MOFA-MAIZE:p11-transition-major",
           "IITA-MAIZE-2025:p16-transition-major", "MOFA-MAIZE:p12-transition-minor", "MOFA-MAIZE:p10-when-to-plant",
           "IITA-MAIZE-2025:p16-transition-minor"]
    return [knowledge.reference(i) for i in ids] + [rainfall.as_passage(r, "transition")]


def test_prompt_says_what_the_rainfall_record_may_be_cited_for():
    s = llm.SYSTEM
    assert "RAINFALL" in s and "only" in s.lower()
    for fig in ("mm", "rain days", "period", "missing days"):
        assert fig in s
    # The good/bad example is built from corpus text, not invented agronomy.
    iita = knowledge.reference("IITA-MAIZE-2025:p15-three-good-rains")["text"]
    assert "plant after three good rains within the planting window" in iita.lower()
    assert "plant after three good rains within the planting window" in s.lower()
    assert "Good: " in s and "Bad: " in s and "[IITA-MAIZE-2025:p15-three-good-rains]" in s
    assert "Sow after the rains have stabilized" in knowledge.reference("MOFA-MAIZE:p10-when-to-plant")["text"]
    assert "Sow after the rains have stabilized" in s and "[MOFA-MAIZE:p10-when-to-plant]" in s


def test_rainfall_heading_is_not_naming_the_rainfall_source(ejura):
    s = f"**Rainfall**: Plant after three good rains within the planting window [IITA-MAIZE-2025:p15-three-good-rains]."
    assert claim_check.check_claims(s, ejura, judge=False).problems == []
    # The provider's own name still counts as naming the source.
    named = "Open-Meteo shows good rains, so plant after three good rains [IITA-MAIZE-2025:p15-three-good-rains]."
    assert any("names METEO" in p for p in claim_check.check_claims(named, ejura, judge=False).problems)


def test_list_numbers_are_not_figures_but_real_figures_still_are(ejura):
    ok = "1. Plant after three good rains within the planting window [IITA-MAIZE-2025:p15-three-good-rains]."
    assert citation_check.check_draft(ok, ejura).problems == []
    bad = "2) Plant after 4 good rains within the planting window [IITA-MAIZE-2025:p15-three-good-rains]."
    assert any("'4'" in p for p in citation_check.check_draft(bad, ejura).problems)
    stray = "Apply it 1. 5 times [IITA-MAIZE-2025:p15-three-good-rains]."  # a number mid-line is not a list marker
    assert citation_check.check_draft(stray, ejura).problems


def test_recorded_live_ejura_draft_now_passes_the_checks(ejura):
    assert citation_check.check_draft(LIVE_EJURA, ejura).problems == []
    assert claim_check.check_claims(LIVE_EJURA, ejura, judge=False).problems == []


def test_guide_sentence_cited_to_the_rainfall_record_is_still_rejected(ejura):
    # Design choice: no silent re-attribution. Guide wording cited to the record has no shared support and fails.
    bad = f"Plant after 3 good rains within the planting window [{RID}]."
    probs = citation_check.check_draft(bad, ejura).problems + claim_check.check_claims(bad, ejura, judge=False).problems
    assert probs


def test_agent_keeps_the_live_ejura_draft_without_regenerating(monkeypatch):
    from test_eval_failures import fake_llm
    monkeypatch.setenv("AGRIREACH_RAINFALL", f"fixture:{FIX}")
    monkeypatch.setenv("AGRIREACH_RAINFALL_TODAY", "2026-10-25")
    calls = fake_llm(monkeypatch, [LIVE_EJURA, LIVE_EJURA])
    out = run("When should I plant maize in Ejura?")
    assert RID in out["sources"]
    assert len(calls) == 1 and out["citation_check"]["ok"], out["citation_check"]
    assert out["draft"].startswith(LIVE_EJURA)
