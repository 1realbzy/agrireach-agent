"""FastAPI backend. Farmer endpoints only ever see officer-approved text."""
from __future__ import annotations

import json

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agrireach import agent, db, llm
from agrireach.channels import service, simulator, whatsapp
from agrireach.channels.base import mask_sender

app = FastAPI(title="AgriReach", version="0.1.0")
if whatsapp.enabled():  # off by default; see docs/whatsapp-setup.md
    app.include_router(whatsapp.router(whatsapp.Config.from_env()))


class Ask(BaseModel):
    question: str
    crop: str = ""
    region: str = ""


class Decision(BaseModel):
    officer: str
    decision: str  # approve | edit_approve | reject | request_info
    edited_text: str | None = None
    note: str | None = None


def _case(row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d["sources"] or "[]")
    d["urgent_reasons"] = json.loads(d["urgent_reasons"] or "[]")
    return d


@app.get("/health")
def health():
    return {"ok": True, "draft_mode": llm.mode()}


@app.post("/ask")
async def ask(a: Ask):
    out = await agent.run(a.question, a.crop, a.region)
    # The farmer gets only an acknowledgement or a clarifying question, never the draft.
    return {"case_id": out["case_id"], "status": out["status"], "clarification": out["clarification"],
            "message": out["clarification"] or "Your question was sent to an extension officer for review."}


@app.get("/officer/queue")
def queue():
    con = db.connect()
    return [_case(r) for r in db.list_cases(con, "pending_review")]


@app.get("/officer/cases/{case_id}")
def case_detail(case_id: int):
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    return _case(row) | {"log": db.case_log(con, case_id)}


@app.post("/officer/cases/{case_id}/decision")
def decide(case_id: int, d: Decision):
    con = db.connect()
    try:
        row = db.officer_decide(con, case_id, officer=d.officer, decision=d.decision, edited_text=d.edited_text,
                                note=d.note)
        delivery = None
        if row["status"] == "approved":
            row = db.release_to_farmer(con, case_id, actor=f"officer:{d.officer}")
            delivery = service.deliver(con, case_id, service.configured_channels())
    except db.GateError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _case(row) | {"delivery": delivery}


@app.post("/cases/{case_id}/release")
def release(case_id: int):
    """Explicit release endpoint; refuses anything without officer approval."""
    con = db.connect()
    try:
        row = db.release_to_farmer(con, case_id, actor="api")
    except db.GateError as e:
        raise HTTPException(409, str(e))
    return _case(row) | {"delivery": service.deliver(con, case_id, service.configured_channels())}


@app.get("/farmer/cases/{case_id}")
def farmer_view(case_id: int):
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    if row["status"] != "released":
        return {"case_id": case_id, "status": row["status"], "answer": None,
                "message": "Waiting for an extension officer to review your question."}
    return {"case_id": case_id, "status": "released", "answer": row["final_text"], "approved_by": row["officer"],
            "approved_at": row["decided_at"]}


# --- Voice notes and channels (local simulator; WhatsApp only if enabled) ------------------------------------

@app.post("/channels/simulator/inbound")
async def simulator_inbound(sender: str = Form(...), text: str = Form(""), audio: UploadFile | None = File(None)):
    """A simulated farmer phone sends a text and/or a voice note. Sender ids must look like 'sim:farmer-1'."""
    try:
        simulator.check_sender(sender)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audio_path = None
    if audio is not None and audio.filename:
        data = await audio.read()
        if len(data) > 16_000_000:
            raise HTTPException(413, "voice note over 16 MB")
        audio_path = service.save_audio(data, Path(audio.filename).suffix or ".wav")
    if not text.strip() and not audio_path:
        raise HTTPException(400, "send a text or a voice note")
    return await service.handle_inbound(service.InboundMessage("simulator", sender, text=text or None,
                                                               audio_path=audio_path),
                                        channel=simulator.SimulatorChannel())


@app.get("/channels/simulator/outbox")
def simulator_outbox(sender: str | None = None):
    return simulator.SimulatorChannel().messages(sender)


@app.get("/officer/cases/{case_id}/voice")
def case_voice(case_id: int):
    """How the question arrived. The sender id is masked; the officer replies through the channel, not by number."""
    c = db.get_contact(db.connect(), case_id)
    if not c:
        raise HTTPException(404, "case did not come through a channel")
    return {"channel": c["channel"], "sender": mask_sender(c["sender_id"]), "transcript": c["transcript"],
            "stt": json.loads(c["stt"] or "{}"), "has_audio": bool(c["audio_path"])}


@app.get("/officer/cases/{case_id}/audio")
def case_audio(case_id: int):
    c = db.get_contact(db.connect(), case_id)
    if not c or not c["audio_path"] or not Path(c["audio_path"]).exists():
        raise HTTPException(404, "no voice note")
    return FileResponse(c["audio_path"])
