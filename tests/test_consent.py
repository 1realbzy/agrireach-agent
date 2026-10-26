"""Consent on first contact, STOP at any time, and the retention purge for stored sender numbers and voice notes."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agrireach import db
from agrireach.channels import retention, service, simulator, stt

CLIP = str(Path(__file__).parent / "fixtures/audio/en_harvest_tamale_piper.wav")
SENDER = "sim:farmer-9"


class Fake:
    def transcribe(self, path):
        return stt.check(stt.Transcript("When should I harvest my soybean? I farm near Tamale.", "en", .99, 3, "fake"))


@pytest.fixture(autouse=True)
def consent_on(monkeypatch):
    monkeypatch.setenv("AGRIREACH_CONSENT", "1")


def send(text=None, audio=False, sender=SENDER):
    return asyncio.run(simulator.ask(sender, text=text, audio=CLIP if audio else None, transcriber=Fake()))


def outbox(sender=SENDER):
    return [m["text"] for m in simulator.SimulatorChannel().messages(sender)]


def test_first_contact_gets_the_consent_prompt_and_the_question_is_held():
    out = send(audio=True)
    assert out["status"] == "awaiting_consent" and out["case_id"] is None
    assert "Reply YES" in outbox()[-1] and "STOP" in outbox()[-1] and "90 days" in outbox()[-1]
    assert db.list_cases(db.connect()) == []
    done = send("yes")
    assert done["case_id"] and done["status"] == "pending_review" and "harvest" in done["question"]
    assert outbox()[-1] == service.ACK
    assert send("When should I plant soybean in Tamale?")["case_id"]  # no prompt the second time


def test_stop_before_consent_deletes_the_held_voice_note():
    send(audio=True)
    con = db.connect()
    held = con.execute("SELECT payload FROM channel_pending").fetchone()["payload"]
    audio = json.loads(held)["audio_path"]
    assert Path(audio).exists()
    out = send("STOP")
    assert out["status"] == "forgotten" and outbox()[-1] == service.STOPPED
    assert not Path(audio).exists()
    assert con.execute("SELECT COUNT(*) FROM channel_pending").fetchone()[0] == 0
    assert db.get_consent(con, "simulator", SENDER) is None and db.list_cases(con) == []


def test_stop_after_an_answer_was_filed_removes_the_number_and_blocks_delivery():
    send("When should I harvest my soybean? I farm near Tamale.")
    cid = send("yes")["case_id"]
    con = db.connect()
    assert db.get_contact(con, cid)["sender_id"] == SENDER
    send("stop")
    assert db.get_contact(con, cid)["sender_id"] == db.OPTED_OUT
    assert SENDER not in {r[0] for r in con.execute("SELECT sender_id FROM channel_consent")}
    r = simulator.officer_approve(cid, officer="Ama Mensah", farmer_text="Harvest at 9 of 10 brown pods.", token=db.add_officer(db.connect(), "Ama Mensah"), expected_revision=db.get_case(db.connect(), cid)["revision"])
    assert r["ok"] is False and "opted out" in r["detail"]
    # The officer's record stays (approved text, officer); the case is 'undeliverable', never 'released'.
    row = db.get_case(con, cid)
    assert row["status"] == "undeliverable" and row["farmer_text"] == "Harvest at 9 of 10 brown pods."


def test_retention_purge_removes_old_numbers_and_audio_but_keeps_case_text(monkeypatch):
    send(audio=True)
    cid = send("yes")["case_id"]
    con = db.connect()
    audio = db.get_contact(con, cid)["audio_path"]
    assert Path(audio).exists()
    later = (datetime.now(timezone.utc) + timedelta(days=31)).isoformat(timespec="seconds")
    assert db.purge_old(con, days=90, now_ts=later)["contacts"] == 0  # not old enough yet
    monkeypatch.setenv("AGRIREACH_RETENTION_DAYS", "30")
    res = db.purge_old(con, now_ts=later)
    assert res["contacts"] == 1 and res["consent"] == 1
    c = db.get_contact(con, cid)
    assert c["sender_id"] == db.PURGED and c["audio_path"] is None and not Path(audio).exists()
    assert "harvest" in db.get_case(con, cid)["question"]


def test_purge_cli(tmp_path, capsys):
    send("hello")
    retention.main(["--days", "0"])
    assert '"held": 1' in capsys.readouterr().out
