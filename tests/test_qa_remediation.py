"""Independent QA regressions: synthetic inputs, no providers or live models."""
import pytest

from agrireach import approval, knowledge, safety_gate


@pytest.mark.parametrize("text", [
    "Use Gramoxone on the weeds.", "Use mancozeb on the maize.",
    "Use Lambda Super on the crop.", "Drench the maize with Karate 5EC.",
    "Drench the maize with Karate.", "Treat the maize with Actellic.",
    "Dust the cobs with Actellic before bagging.", "Apply unfamiliarname to the leaves.",
    "Treat the field using newmaterial.", "Apply it every three days.",
])
def test_c1_product_instructions_cannot_reach_judge(text, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("A deterministic hold must not consult the probabilistic judge")
    from agrireach import claim_check
    monkeypatch.setattr(claim_check, "check_claims", forbidden)
    for sources in ([], [knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")]):
        candidate = "Consult your local AEA before choosing or applying a pesticide. " + text
        ctx = {"case": {"farmer_draft": None}, "sources": sources, "contact": None}
        result = approval.assess_candidate(candidate, ctx)
        assert result["outcome"] == "review_required", result
        assert any(f["rule_id"] == "S3" for f in result["findings"])
