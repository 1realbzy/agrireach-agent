"""FastAPI backend. Farmer endpoints only ever see officer-approved text."""
from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agrireach import agent, db, farmer_reply, knowledge, llm
from agrireach.channels import service, simulator, whatsapp
from agrireach.channels.base import mask_sender

app = FastAPI(title="AgriReach", version="0.1.0")
if whatsapp.enabled():  # off by default; see docs/whatsapp-setup.md
    app.include_router(whatsapp.router(whatsapp.Config.from_env()))


class Ask(BaseModel):
    question: str
    crop: str = ""
    region: str = ""


def current_officer(authorization: str | None = Header(None)) -> str:
    """The signed-in officer's name, from their sign-in token (Authorization: Bearer <token>; tokens are issued by
    scripts/add_officer.py). Every officer route and release depends on this; the name on the record comes from here."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    name = db.officer_for_token(db.connect(), token)
    if not name:
        raise HTTPException(401, "officer sign-in required", headers={"WWW-Authenticate": "Bearer"})
    return name


class Decision(BaseModel):
    officer: str | None = None  # ignored: the officer is whoever is signed in
    decision: str  # approve | edit_approve | reject | request_info
    edited_text: str | None = None
    note: str | None = None
    # The exact farmer-facing text being approved (required to approve): this, and only this, is delivered.
    farmer_text: str | None = None
    # Approving requires the officer to confirm they checked the farmer text against the cited sources.
    confirmed: bool = False


class OfficerText(BaseModel):
    officer_text: str


def _case(row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d["sources"] or "[]")
    d["urgent_reasons"] = json.loads(d["urgent_reasons"] or "[]")
    d["farmer_draft"] = json.loads(d.get("farmer_draft") or "null")
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
def queue(officer: str = Depends(current_officer)):
    con = db.connect()
    return [_case(r) for r in db.list_cases(con, "pending_review")]


@app.get("/officer/cases/{case_id}")
def case_detail(case_id: int, officer: str = Depends(current_officer)):
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    return _case(row) | {"log": db.case_log(con, case_id)}


@app.post("/officer/cases/{case_id}/decision")
def decide(case_id: int, d: Decision, officer: str = Depends(current_officer)):
    con = db.connect()
    if d.decision in ("approve", "edit_approve") and not (d.farmer_text or "").strip():
        raise HTTPException(400, "farmer_text required: approve the exact text the farmer will receive")
    if d.decision in ("approve", "edit_approve") and not d.confirmed:
        raise HTTPException(400, "confirm that you checked the farmer text against the cited sources before approving")
    warnings = []
    if d.decision in ("approve", "edit_approve"):
        current = db.get_case(con, case_id)
        caveat = (json.loads(current["farmer_draft"] or "null") or {}).get("zone_caveat") if current else None
        if not farmer_reply.caveat_kept(d.farmer_text, caveat):
            warnings.append(f"the approved farmer text has no zone caveat: the guidance is from sources for "
                            f"{caveat['sources_for']} and the farmer is in {caveat['region']}")
        # Officer-written or kept text is warned about and logged, never blocked: the officer is the authority.
        if current:
            ps = [knowledge.reference(i) for i in json.loads(current["sources"] or "[]")]
            warnings += [f"farmer text not backed by the case's sources: {p}"
                         for p in farmer_reply.sms_claims(d.farmer_text, ps, caveat=caveat)]
    try:
        row = db.officer_decide(con, case_id, officer=officer, decision=d.decision, edited_text=d.edited_text,
                                note=d.note, farmer_text=d.farmer_text)
        delivery = None
        if row["status"] == "approved":
            row = db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
            delivery = service.deliver(con, case_id, service.configured_channels())
    except db.GateError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    for w in warnings:
        db.log(con, f"officer:{officer}", "approval_warning", {"decision": d.decision}, w, ok=False, case_id=case_id)
    return _case(row) | {"delivery": delivery, "warnings": warnings}


@app.post("/officer/cases/{case_id}/farmer-draft")
def farmer_draft(case_id: int, body: OfficerText, officer: str = Depends(current_officer)):
    """Re-propose the farmer-facing text from the officer's (edited) text. A proposal only; nothing is saved or sent."""
    row = db.get_case(db.connect(), case_id)
    if not row:
        raise HTTPException(404, "not found")
    stored = json.loads(row["farmer_draft"] or "null") or {}
    conflicts = any(str(n).startswith("sources differ") for n in stored.get("problems", []))
    ps = [knowledge.reference(i) for i in json.loads(row["sources"] or "[]")]
    fd = asdict(farmer_reply.propose(body.officer_text, row["question"], stored.get("language", "en"),
                                     conflicts=conflicts, zone_caveat=stored.get("zone_caveat"), passages=ps))
    if stored.get("season_prompt"):  # received date outside every cited window: keep prompting the officer
        fd["problems"] = fd["problems"] + [stored["season_prompt"]]
    return fd


@app.post("/cases/{case_id}/release")
def release(case_id: int, officer: str = Depends(current_officer)):
    """Explicit release endpoint (signed-in officers only); refuses anything without officer approval."""
    con = db.connect()
    try:
        row = db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
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
    return {"case_id": case_id, "status": "released", "answer": row["farmer_text"] or row["final_text"],
            "approved_by": row["officer"],
            "approved_at": row["decided_at"]}


# --- Voice notes and channels (local simulator; WhatsApp only if enabled) ------------------------------------

def _simulator_enabled() -> None:
    """The simulator is a local demo of a farmer's phone: its outbox lists every farmer's messages with no sign-in.
    Off unless AGRIREACH_SIMULATOR=1; never enable it on a deployed server."""
    if os.getenv("AGRIREACH_SIMULATOR") != "1":
        raise HTTPException(404, "not found")


@app.post("/channels/simulator/inbound", dependencies=[Depends(_simulator_enabled)])
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


@app.get("/channels/simulator/outbox", dependencies=[Depends(_simulator_enabled)])
def simulator_outbox(sender: str | None = None):
    return simulator.SimulatorChannel().messages(sender)


@app.get("/officer/cases/{case_id}/voice")
def case_voice(case_id: int, officer: str = Depends(current_officer)):
    """How the question arrived. The sender id is masked; the officer replies through the channel, not by number."""
    c = db.get_contact(db.connect(), case_id)
    if not c:
        raise HTTPException(404, "case did not come through a channel")
    return {"channel": c["channel"], "sender": mask_sender(c["sender_id"]), "transcript": c["transcript"],
            "stt": json.loads(c["stt"] or "{}"), "has_audio": bool(c["audio_path"])}


@app.get("/officer/cases/{case_id}/audio")
def case_audio(case_id: int, officer: str = Depends(current_officer)):
    c = db.get_contact(db.connect(), case_id)
    if not c or not c["audio_path"] or not Path(c["audio_path"]).exists():
        raise HTTPException(404, "no voice note")
    return FileResponse(c["audio_path"])
