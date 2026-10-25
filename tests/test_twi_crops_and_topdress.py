import pytest

from agrireach import knowledge, language


@pytest.mark.parametrize("q,crop", [
    ("Bere ben na me dua aburo?", "maize"),
    ("When do I plant aburoo near Tamale?", "maize"),
    ("Mɛdua bankye", "cassava"),
    ("bayerɛ ho nsɛm", "yam"),
    ("bayere", "yam"),
    ("ɛmo dua bere", "rice"),
    ("borɔdeɛ", "plantain"),
])
def test_verified_twi_crop_names_are_recognised(q, crop):
    assert language.detect_crop(q) == crop


def test_adua_is_not_read_as_cowpea():
    assert language.detect_crop("adua") != "cowpea"


@pytest.mark.parametrize("q", ["When should I top dress my maize?", "When should I top-dress my maize?",
                               "When is top dressing done for maize?", "When should I topdress my maize?"])
def test_top_dress_wordings_find_the_dry_soil_passage(q):
    hits = knowledge.search(q, crop="maize")
    assert any("delay the topdress fertilizer application" in h["text"] for h in hits), [h["id"] for h in hits]
