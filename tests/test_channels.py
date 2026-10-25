"""Voice-note channel layer with the local simulator (offline: fake transcriber, stub drafts)."""
import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agrireach import api, db
from agrireach.channels import service, simulator, stt, tts
from agrireach.channels.base import mask_sender

CLIP = str(Path(__file__).parent / "fixtures/audio/en_harvest_tamale_piper.wav")
SENDER = "sim:farmer-1"


class FakeTranscriber:
    def __init__(self, text, language="en", p=0.99, fail=False):
        self.text, self.language, self.p, self.fail = text, language, p, fail

    def transcribe(self, path):
        if self.fail:
            raise RuntimeError("decoder crashed")
        assert Path(path).exists()
        return stt.check(stt.Transcript(self.text, self.language, self.p, 3.2, "fake"))


def ask(**kw):
    return asyncio.run(simulator.ask(SENDER, **kw))


def outbox():
    return simulator.SimulatorChannel().messages(SENDER)


def test_mask_sender_keeps_only_last_two_characters():
    assert mask_sender("+15555550100") == "**********00"
    assert mask_sender("sim:farmer-1") == "**********-1"
    assert mask_sender("abc") == "****"


@pytest.mark.parametrize("bad", ["+233000000000", "0200000000", "sim:", "SIM:Farmer", "sim:a b"])
def test_simulator_refuses_anything_that_is_not_a_sim_id(bad):
    with pytest.raises(ValueError):
        simulator.check_sender(bad)


def test_voice_note_becomes_a_case_and_only_an_acknowledgement_goes_back():
    out = ask(audio=CLIP, transcriber=FakeTranscriber("When should I harvest my soybean? I farm near Tamale."))
    assert out["status"] == "pending_review" and out["transcript"].startswith("When should I harvest")
    con = db.connect()
    row = db.get_case(con, out["case_id"])
    assert row["question"] == out["transcript"] and row["crop"] == "soybean"
    msgs = outbox()
    assert [m["text"] for m in msgs] == [service.ACK]  # no advice before an officer approves
    contact = db.get_contact(con, out["case_id"])
    assert contact["channel"] == "simulator" and Path(contact["audio_path"]).exists()
    assert SENDER not in Path(contact["audio_path"]).name  # stored under a random name
    logs = json.dumps(db.case_log(con, out["case_id"]))
    assert SENDER not in logs and mask_sender(SENDER) in logs  # sender masked in the tool log


def test_answer_is_sent_only_after_officer_approval_and_release():
    out = ask(text="When should I harvest my soybean? I farm near Tamale.")
    con = db.connect()
    chans = {"simulator": simulator.SimulatorChannel()}
    blocked = service.deliver(con, out["case_id"], chans)
    assert blocked == {"ok": False, "detail": "not released after officer approval"}
    assert len(outbox()) == 1  # still only the acknowledgement
    assert any("BLOCKED" in l["result_summary"] for l in db.case_log(con, out["case_id"]))
    db.officer_decide(con, out["case_id"], officer="Ama Mensah", decision="edit_approve",
                      edited_text="Harvest when 9 out of 10 pods are brown.")
    assert service.deliver(con, out["case_id"], chans)["ok"] is False  # approved but not released yet
    db.release_to_farmer(con, out["case_id"], actor="officer:Ama Mensah")
    assert service.deliver(con, out["case_id"], chans)["ok"] is True
    assert outbox()[-1]["text"] == "Harvest when 9 out of 10 pods are brown."
    assert service.deliver(con, out["case_id"], chans)["detail"] == "already delivered"
    assert len(outbox()) == 2  # no duplicate send


def test_rejected_case_is_never_sent():
    out = ask(text="When should I harvest my soybean? I farm near Tamale.")
    con = db.connect()
    db.officer_decide(con, out["case_id"], officer="Ama Mensah", decision="reject")
    with pytest.raises(db.GateError):
        db.release_to_farmer(con, out["case_id"])
    assert service.deliver(con, out["case_id"], {"simulator": simulator.SimulatorChannel()})["ok"] is False
    assert [m["text"] for m in outbox()] == [service.ACK]


def test_non_english_or_failed_transcription_is_urgent_for_the_officer():
    out = ask(audio=CLIP, transcriber=FakeTranscriber("Bere ben na menndua soya", language="yo", p=0.41))
    assert out["priority"] == "urgent" and any("not English" in r for r in out["urgent_reasons"])
    out = ask(audio=CLIP, transcriber=FakeTranscriber("", fail=True))
    assert out["priority"] == "urgent" and any("could not be transcribed" in r for r in out["urgent_reasons"])
    assert out["status"] == "pending_review"


def test_stt_off_still_files_the_voice_note_for_the_officer():
    out = asyncio.run(simulator.ask(SENDER, audio=CLIP))  # conftest sets AGRIREACH_STT=none
    assert any("speech-to-text is off" in r for r in out["urgent_reasons"])


def test_clarifying_question_goes_back_through_the_channel():
    out = ask(text="When should I plant soybean?")
    assert out["status"] == "draft" and out["sent"] == {"kind": "clarification", "ok": True}
    assert outbox()[-1]["text"].startswith("Which district or region")


def test_api_simulator_flow_and_officer_decision_delivers(monkeypatch):
    monkeypatch.setattr(stt, "default", lambda: FakeTranscriber("When should I harvest my soybean? I farm near Tamale."))
    c = TestClient(api.app)
    h = {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}
    assert c.post("/channels/simulator/inbound", data={"sender": "+233000000000", "text": "hi"}).status_code == 400
    with open(CLIP, "rb") as f:
        r = c.post("/channels/simulator/inbound", data={"sender": SENDER}, files={"audio": ("q.wav", f, "audio/wav")})
    assert r.status_code == 200
    cid = r.json()["case_id"]
    assert c.get(f"/officer/cases/{cid}/voice").status_code == 401
    assert c.get(f"/officer/cases/{cid}/audio").status_code == 401  # farmer audio is officer-only
    v = c.get(f"/officer/cases/{cid}/voice", headers=h).json()
    assert v["sender"] == mask_sender(SENDER) and v["has_audio"] and "soybean" in v["transcript"]
    assert c.get(f"/officer/cases/{cid}/audio", headers=h).status_code == 200
    assert c.post(f"/cases/{cid}/release", headers=h).status_code == 409  # gate unchanged
    d = c.post(f"/officer/cases/{cid}/decision", headers=h,
               json={"decision": "approve", "confirmed": True,
                     "farmer_text": "Harvest when 9 of 10 pods are brown."}).json()
    assert d["status"] == "released" and d["delivery"]["ok"]
    out = [m["text"] for m in c.get("/channels/simulator/outbox", params={"sender": SENDER}).json()]
    assert out[-1] == "Harvest when 9 of 10 pods are brown." != d["final_text"]  # officer view keeps citations


def test_optional_tts_attaches_audio_to_the_approved_answer(monkeypatch, tmp_path):
    monkeypatch.setenv("AGRIREACH_TTS", "piper")
    spoken = {}

    def fake_synth(text, out_path):
        spoken["text"] = text
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"RIFF")
        return out_path
    monkeypatch.setattr(tts, "synthesize", fake_synth)
    out = ask(text="When should I harvest my soybean? I farm near Tamale.")
    con = db.connect()
    db.officer_decide(con, out["case_id"], officer="Ama Mensah", decision="edit_approve",
                      edited_text="Harvest when 9 out of 10 pods are mature [APNI-SARI-2023:harvest].")
    db.release_to_farmer(con, out["case_id"])
    res = service.deliver(con, out["case_id"], {"simulator": simulator.SimulatorChannel()})
    assert res["ok"] and res["audio"] and outbox()[-1]["audio"]
    assert spoken["text"].startswith("Hello. This is AgriReach") and "Ama Mensah" in spoken["text"]
    assert "[APNI" not in spoken["text"] and "9 out of 10" in spoken["text"]
    assert outbox()[-1]["text"].endswith("[APNI-SARI-2023:harvest].")  # the text goes out exactly as approved
