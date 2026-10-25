"""Run 5 item 5c: the zone caveat is about all the advice (pest control as well as planting dates), so it ends "so
check this advice with your local extension agent", not "check the timing"."""
from agrireach import farmer_reply as fr


def test_caveat_asks_the_farmer_to_check_the_advice():
    c = fr.zone_caveat("Kintampo")
    assert c["sentence"] == ("This advice comes from guides for Northern Ghana and may not suit Kintampo, so check this "
                             "advice with your local extension agent.")
    assert "timing" not in fr.zone_caveat("Adaklu", "the forest")["sentence"]
