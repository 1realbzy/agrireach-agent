"""FastAPI backend. Farmer endpoints only ever see officer-approved text."""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agrireach import agent, db, llm

app = FastAPI(title="AgriReach", version="0.1.0")


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
        if row["status"] == "approved":
            row = db.release_to_farmer(con, case_id, actor=f"officer:{d.officer}")
    except db.GateError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _case(row)


@app.post("/cases/{case_id}/release")
def release(case_id: int):
    """Explicit release endpoint; refuses anything without officer approval."""
    con = db.connect()
    try:
        return _case(db.release_to_farmer(con, case_id, actor="api"))
    except db.GateError as e:
        raise HTTPException(409, str(e))


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
