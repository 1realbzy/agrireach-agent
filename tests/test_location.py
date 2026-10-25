"""Place names after speech-to-text: gazetteer-backed suggestions, confirm-back, never a silent correction."""
import asyncio
import json
from pathlib import Path

import pytest

from agrireach import agent, db
from agrireach.channels import location, simulator, stt

CLIP = str(Path(__file__).parent / "fixtures/audio/en_harvest_tamale_piper.wav")
SENDER = "sim:farmer-5"


class Fake:
    def __init__(self, text):
        self.text = text

    def transcribe(self, path):
        return stt.check(stt.Transcript(self.text, "en", 0.99, 3.0, "fake"))


def voice(text):
    return asyncio.run(simulator.ask(SENDER, audio=CLIP, transcriber=Fake(text)))


def reply(text):
    return asyncio.run(simulator.ask(SENDER, text=text))


def outbox():
    return [m["text"] for m in simulator.SimulatorChannel().messages(SENDER)]


@pytest.mark.parametrize("text,heard,name", [
    ("When should I plant soybean? I farm near war.", "war", "Wa"),
    ("I farm near Tamali, when do I harvest?", "Tamali", "Tamale"),
    ("When do I plant soybean in Yandi district?", "Yandi", "Yendi"),
])
def test_suggests_a_gazetteer_place_only_in_a_location_slot(text, heard, name):
    s = location.suggest(text)
    assert s and s.heard == heard and s.place["name"] == name and name in s.question()


@pytest.mark.parametrize("text", [
    "When should I plant soybean at Wa?",          # already a known place
    "Should I spray in the morning?",              # common word after 'in'
    "When do I harvest in June?",
    "What happens to soybean during the war?",     # 'war' not in a location slot
    "How many seeds in rows of 75 cm?",
])
def test_no_suggestion_without_a_plausible_misheard_place(text):
    assert location.suggest(text) is None


def test_gazetteer_regions_feed_intake():
    assert agent._detect_region("when do i plant soybean in lawra?") == "lawra" and agent._is_northern("lawra")
    assert agent._detect_region("when do i plant soybean in techiman?") == "techiman"
    assert not agent._is_northern("techiman")


def test_voice_note_with_misheard_place_asks_first_then_uses_the_confirmed_place():
    out = voice("When should I plant soybean? I farm near war.")
    assert out["status"] == "awaiting_location" and out["case_id"] is None
    assert outbox()[-1].startswith('I heard "war". Did you mean Wa (Upper West Region)?')
    assert db.list_cases(db.connect()) == []  # nothing filed, nothing guessed
    done = reply("Yes")
    assert done["question"] == "When should I plant soybean? I farm near Wa."
    stt_info = json.loads(db.get_contact(db.connect(), done["case_id"])["stt"])
    assert stt_info["location_check"] == {"heard": "war", "asked": "Wa", "reply": "yes"}
    row = db.get_case(db.connect(), done["case_id"])
    assert row["region"] and row["region"].lower() == "wa"
    assert db.get_contact(db.connect(), done["case_id"])["transcript"].endswith("near war.")  # machine text kept


def test_farmer_can_name_a_different_place():
    voice("When should I plant soybean? I farm near war.")
    done = reply("No, I am in Lawra")
    assert done["question"].endswith("near Lawra.")


def test_unclear_reply_files_the_original_with_an_urgent_reason():
    voice("When should I plant soybean? I farm near war.")
    done = reply("hmm")
    assert done["question"].endswith("near war.")
    assert any("location unconfirmed" in r and "Wa" in r for r in done["urgent_reasons"])


def test_typed_text_is_not_corrected():
    out = reply("When should I plant soybean? I farm near war.")
    assert out["status"] != "awaiting_location" and out["case_id"]
