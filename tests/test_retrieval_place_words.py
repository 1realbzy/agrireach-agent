"""R3: place words (region, district, compass, zone names) never count as a topical match in knowledge.search.
Topic matches, the zone tool and conflict completeness for real planting questions are unchanged."""
from agrireach import knowledge

W = "APNI-SARI-2023-MAIZE:p5-planting-window"
WINDOWS = {"MOFA-MAIZE:p12-guinea-sudan-major", "IITA-MAIZE-2025:p16-guinea-major"}


def ids(q, crop):
    return [p["id"] for p in knowledge.search(q, crop=crop)]


def test_place_words_are_geo_stems():
    for w in ("region", "northern", "upper", "west", "district", "savannah", "guinea"):
        assert knowledge.stem(w) in knowledge.GEO_STEMS
    for w in ("maize", "plant", "armyworm", "spacing", "fertilizer"):
        assert knowledge.stem(w) not in knowledge.GEO_STEMS


def test_pest_questions_with_a_place_get_no_planting_passages():
    for q in ("Fall armyworm is attacking my maize near Tamale in the Northern Region. What should I do?",
              "Armyworm on my maize in the Upper West Region, the leaves have holes.",
              "My maize leaves have holes in the Upper East Region district of Bawku."):
        got = ids(q, "maize")
        assert W not in got and not WINDOWS & set(got), (q, got)


def test_planting_questions_keep_every_source_window():
    for q in ("When should I plant maize in the Northern Region?", "When do I plant maize in Tamale?",
              "When should I plant maize?"):
        got = set(ids(q, "maize"))
        assert W in got and WINDOWS <= got, (q, got)


def test_place_word_does_not_change_a_topic_question():
    q = "What spacing should I use for soybean in the Upper West Region?"
    assert ids(q, "soybean") == ids("What spacing should I use for soybean?", "soybean")
