"""Corpus scoping: a crop's search never returns another crop's passages, and every passage is well formed."""
from agrireach import knowledge


def test_every_passage_has_a_known_source_and_required_fields():
    kb = knowledge.load()
    ids = [p["id"] for p in kb["passages"]]
    assert len(ids) == len(set(ids))
    for p in kb["passages"]:
        assert p["source_id"] in kb["sources"] and p["id"].startswith(p["source_id"] + ":")
        assert p["text"].strip() and p["crop"] and p["claim_key"] and p["topic"]
    for s in kb["sources"].values():
        assert s["url"].startswith("https://") and s["licence"]


def test_maize_search_is_scoped_to_maize():
    hits = knowledge.search("When should I plant maize? planting", crop="maize")
    assert hits and all(h["crop"] == "maize" for h in hits)
    assert "APNI-SARI-2023-MAIZE:p5-planting-window" in {h["id"] for h in hits}


def test_soybean_search_never_returns_maize_passages():
    hits = knowledge.search("When should I plant soybean? planting", crop="soybean")
    assert hits and all(h["crop"] == "soybean" for h in hits)


def test_crops_covered_lists_corpus_crops():
    assert knowledge.crops_covered() == ["maize", "soybean"]
