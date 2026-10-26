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
from agrireach.channels import service, simulator, sms, whatsapp
from agrireach.channels.base import mask_sender

app = FastAPI(title="AgriReach", version="0.1.0")
if whatsapp.enabled():  # off by default; see docs/whatsapp-setup.md
    app.include_router(whatsapp.router(whatsapp.Config.from_env()))
if sms.enabled():  # off by default; see docs/sms-setup.md
    app.include_router(sms.router(sms.Config.from_env()))


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
    approved_voice_script: str | None = None
    acknowledgement: str | None = None
    expected_revision: int | None = None
    confirmed: bool = False


class OfficerText(BaseModel):
    officer_text: str


class ReopenRequest(BaseModel):
    expected_revision: int
    information: str


class ReconcileRequest(BaseModel):
    accepted: bool
    provider_evidence: str


@app.post("/officer/delivery-jobs/{job_id}/reconcile")
def reconcile_delivery(job_id: int, body: ReconcileRequest, officer: str = Depends(current_officer)):
    """Record an officer's verified provider disposition without sending again."""
    from agrireach import delivery
    try:
        delivery.reconcile(db.connect(), job_id, officer=officer,
                           accepted=body.accepted, provider_evidence=body.provider_evidence)
    except db.GateError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"job_id": job_id, "state": "accepted" if body.accepted else "definitely_failed"}


@app.post("/officer/cases/{case_id}/reopen")
def reopen(case_id: int, body: ReopenRequest, officer: str = Depends(current_officer)):
    """Return a clarified needs_info case to review without approving any advice."""
    try:
        return _case(db.reopen_case(db.connect(), case_id, officer=officer,
                     expected_revision=body.expected_revision, information=body.information))
    except db.GateError as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


def _case(row) -> dict:
    d = dict(row)
    d["sources"] = json.loads(d["sources"] or "[]")
    d["urgent_reasons"] = json.loads(d["urgent_reasons"] or "[]")
    d["farmer_draft"] = json.loads(d.get("farmer_draft") or "null")
    if d.get("status") in ("not_delivered", "undeliverable"):  # the send failed or can never happen: say why
        d["delivery_problem"] = db.delivery_problem(db.connect(), d["id"]) or "the send failed"
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
    return [_case(r) for r in db.list_cases(con, ("pending_review", "not_delivered"))]


CASE_STATUSES = ("draft", "pending_review", "approved", "released", "not_delivered", "undeliverable", "rejected",
                 "needs_info")


@app.get("/officer/cases")
def case_list(status: str | None = None, officer: str = Depends(current_officer)):
    """Every case (history), newest status included; filter with ?status=undeliverable etc. Read-only."""
    if status is not None and status not in CASE_STATUSES:
        raise HTTPException(400, f"status must be one of {', '.join(CASE_STATUSES)}")
    return [_case(r) for r in db.list_cases(db.connect(), status)]


@app.get("/officer/cases/{case_id}")
def case_detail(case_id: int, officer: str = Depends(current_officer)):
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    return _case(row) | {"log": db.case_log(con, case_id)}


@app.post("/officer/cases/{case_id}/voice-preview")
def voice_preview(case_id: int, body: OfficerText, officer: str = Depends(current_officer)):
    """Preview the exact optional spoken script without synthesis or dispatch."""
    from agrireach import voice_script
    from agrireach.channels import tts
    row = db.get_case(db.connect(), case_id)
    if not row:
        raise HTTPException(404, "not found")
    script = voice_script.build(body.officer_text, officer, row["crop"] or "")
    return {"enabled": tts.enabled(), "text": script.text, "ok": script.ok,
            "problems": script.problems, "expected_revision": row["revision"]}


@app.post("/officer/cases/{case_id}/decision")
def decide(case_id: int, d: Decision, officer: str = Depends(current_officer)):
    con = db.connect()
    if d.decision in ("approve", "edit_approve") and not (d.farmer_text or "").strip():
        raise HTTPException(400, "farmer_text required: approve the exact text the farmer will receive")
    if d.decision in ("approve", "edit_approve") and not d.confirmed:
        raise HTTPException(400, "confirm that you checked the farmer text against the cited sources before approving")
    warnings = []
    try:
        row = db.officer_decide(con, case_id, officer=officer, decision=d.decision, edited_text=d.edited_text,
                                note=d.note, farmer_text=d.farmer_text, expected_revision=d.expected_revision, acknowledgement=d.acknowledgement, approved_voice_script=d.approved_voice_script)
        latest_assessment = con.execute("SELECT assessment FROM safety_assessments WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        warnings = json.loads(latest_assessment[0]).get("informational", []) if latest_assessment else []
        delivery = None
        if row["status"] == "approved":
            row = db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
            delivery = service.deliver(con, case_id, service.configured_channels()) if row["status"] == "released" else {"ok": False, "outcome": "undeliverable"}
            row = db.get_case(con, case_id)  # 'not_delivered' if the channel send failed
    except db.SafetyError as e:
        raise HTTPException({"acknowledgement_required": 409, "assessment_unavailable": 503}.get(e.assessment["outcome"], 422), e.assessment)
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
    with llm.usage_logged(case_id, f"officer:{officer}", "farmer_draft"):
        proposal = farmer_reply.propose(body.officer_text, row["question"], stored.get("language", "en"),
                                        conflicts=conflicts, zone_caveat=stored.get("zone_caveat"), passages=ps)
    db.log(db.connect(), f"officer:{officer}", "farmer_text_proposal", *farmer_reply.audit_entry(proposal),
           case_id=case_id)
    fd = asdict(proposal)
    if stored.get("season_prompt"):  # received date outside every cited window: keep prompting the officer
        fd["problems"] = fd["problems"] + [stored["season_prompt"]]
    contact = db.get_contact(db.connect(), case_id)
    if contact is not None and contact["channel"] == "sms":
        fd = service.sms_review(fd)
    return fd


class FarmerText(BaseModel):
    farmer_text: str


@app.post("/officer/cases/{case_id}/sms-check")
def sms_check(case_id: int, body: FarmerText, officer: str = Depends(current_officer)):
    """Length check of the officer's current farmer text, for SMS cases. Read-only; nothing is changed or sent."""
    con = db.connect()
    if not db.get_case(con, case_id):
        raise HTTPException(404, "not found")
    contact = db.get_contact(con, case_id)
    if contact is None or contact["channel"] != "sms":
        return {"channel": contact["channel"] if contact else None, "prompt": None}
    return {"channel": "sms", **sms.check(body.farmer_text)}


@app.post("/cases/{case_id}/release")
def release(case_id: int, officer: str = Depends(current_officer)):
    """Explicit release endpoint (signed-in officers only); refuses anything without officer approval. On a
    'not_delivered' case it retries sending the same approved text."""
    con = db.connect()
    try:
        db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
    except db.SafetyError as e:
        raise HTTPException({"acknowledgement_required": 409, "assessment_unavailable": 503}.get(e.assessment["outcome"], 422), e.assessment)
    except db.GateError as e:
        raise HTTPException(409, str(e))
    delivery = service.deliver(con, case_id, service.configured_channels())
    return _case(db.get_case(con, case_id)) | {"delivery": delivery}


@app.get("/farmer/cases/{case_id}")
def farmer_view(case_id: int):
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    if row["status"] == "undeliverable":  # approved, but the number was removed (STOP or retention purge)
        return {"case_id": case_id, "status": "undeliverable", "answer": None,
                "message": "No answer was sent: this number was removed from AgriReach."}
    if row["status"] == "not_delivered":  # approved, but the channel send failed: no answer has reached the farmer
        return {"case_id": case_id, "status": "not_delivered", "answer": None,
                "message": "Your answer has not been sent yet. An extension officer is working on it."}
    if row["status"] != "released":
        return {"case_id": case_id, "status": row["status"], "answer": None,
                "message": "Waiting for an extension officer to review your question."}
    contact = db.get_contact(con, case_id)
    job = con.execute("SELECT j.state FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? ORDER BY j.id DESC LIMIT 1", (case_id,)).fetchone()
    if contact and job and job["state"] != "accepted":
        return {"case_id": case_id, "status": row["status"], "delivery_status": job["state"], "answer": None,
                "message": "Delivery acceptance has not been confirmed."}
    from agrireach.approval import validated_approval
    try:
        _approval, payload = validated_approval(con, case_id)
    except db.GateError:
        # Grandfather only already published historical text; never enqueue it.
        legacy = con.execute("SELECT payload FROM approvals WHERE case_id=? AND provenance='legacy_unvalidated' ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        historic = json.loads(legacy[0]) if legacy else {}
        if historic.get("status") == "released":
            return {"case_id": case_id, "status": "released", "answer": historic.get("farmer_text") or historic.get("final_text"),
                    "assessment_status": "legacy_unvalidated", "approved_by": historic.get("officer")}
        return {"case_id": case_id, "status": "review_required", "answer": None}
    return {"case_id": case_id, "status": "released", "answer": payload["farmer_text"],
            "approved_by": row["officer"],
            "approved_at": row["decided_at"]}


# --- Voice notes and channels (local simulator; WhatsApp and SMS only if enabled) -----------------------------

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
