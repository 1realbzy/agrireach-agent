"""FastAPI backend. Farmer endpoints only ever see officer-approved text."""
from __future__ import annotations

import json
import logging
from contextlib import closing
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator
from pydantic_core import PydanticCustomError

from agrireach import (acknowledgement, approval, agent, db, emergency, farmer_reply, knowledge, llm, officer_auth,
                       ratelimit, safe_logging)
from agrireach.phone import PhoneError, normalize as normalize_phone
from agrireach.channels import service, simulator, sms, whatsapp
from agrireach.channels.base import mask_sender

logger = logging.getLogger(__name__)
safe_logging.protect_uvicorn_access()
app = FastAPI(title="AgriReach", version="0.1.0")
if whatsapp.enabled():  # off by default; see docs/whatsapp-setup.md
    app.include_router(whatsapp.router(whatsapp.Config.from_env()))
if sms.enabled():  # off by default; see docs/sms-setup.md
    app.include_router(sms.router(sms.Config.from_env()))


VALIDATION_MESSAGES = {
    "json_invalid": "Invalid JSON body",
    "model_attributes_type": "Expected a JSON object",
    "model_type": "Expected a JSON object",
    "missing": "Field required",
    "string_type": "Expected text",
    "string_too_short": "Text is too short",
    "string_too_long": "Text is too long",
    "bool_type": "Expected a boolean",
    "bool_parsing": "Expected a boolean",
    "int_type": "Expected an integer",
    "int_parsing": "Expected an integer",
    "int_from_float": "Expected an integer",
    "greater_than_equal": "Value is below the minimum",
    "blank_question": "Question must contain text",
    "blank_supplement": "Text must contain text",
}


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request: Request, exc: RequestValidationError):
    # FastAPI's default response includes input and validator context. Messages
    # from validators can also interpolate private data, so use fixed messages.
    errors = []
    for error in exc.errors():
        kind = error["type"]
        # The first two components identify the request source and declared field
        # in these models. Deeper locations can contain user-supplied map keys.
        location = error["loc"][:2]
        if kind not in VALIDATION_MESSAGES:
            kind = "invalid_request"
            location = location[:1]
        errors.append({"loc": location, "type": kind, "msg": VALIDATION_MESSAGES.get(kind, "Invalid input")})
    return JSONResponse(status_code=422, content={"detail": errors})


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    crop: str = Field(default="", max_length=100)
    region: str = Field(default="", max_length=100)
    phone: str = ""
    sms_consent: bool = False

    @field_validator("question")
    @classmethod
    def question_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise PydanticCustomError("blank_question", "Question must contain text")
        return value


class Supplement(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    expected_revision: int = Field(ge=1)

    @field_validator("text")
    @classmethod
    def text_is_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise PydanticCustomError("blank_supplement", "Text must contain text")
        return value


AWAITING_FARMER = "Awaiting your information before an officer can review this."


def _revision_conflict(exc: BaseException) -> bool:
    """True when a supplement lost the race or the draft was no longer open. Walks ExceptionGroups from the MCP client."""
    if isinstance(exc, BaseExceptionGroup):
        return any(_revision_conflict(item) for item in exc.exceptions)
    text = str(exc)
    return "stale_revision" in text or "not waiting for farmer information" in text


def _bearer(authorization: str | None) -> str:
    return (authorization or "").removeprefix("Bearer ").strip()


def current_officer(authorization: str | None = Header(None)) -> str:
    """The signed-in officer's name (Authorization: Bearer <token>). The token is an expiring session from
    POST /officer/auth/login, or (unless AGRIREACH_LEGACY_OFFICER_TOKENS=0) a legacy token from
    scripts/add_officer.py. Every officer route and release depends on this; the name on the record comes from here."""
    token = _bearer(authorization)
    con = db.connect()
    session = officer_auth.session_for_token(con, token)
    name = session["officer"] if session else None
    if not name and officer_auth.legacy_tokens_enabled():
        name = db.officer_for_token(con, token)
    if not name:
        raise HTTPException(401, "officer sign-in required", headers={"WWW-Authenticate": "Bearer"})
    return name


class Login(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _client_id(request: Request) -> str:
    """The caller's address; behind the portals, their X-AgriReach-Client digest when explicitly trusted."""
    client = request.client.host if request.client else "unknown"
    marker = (request.headers.get("x-agrireach-client") or "").strip()
    if marker and os.getenv("AGRIREACH_TRUST_PORTAL_CLIENT_HEADER") == "1":
        client = "portal:" + marker[:128]
    return client


@app.post("/officer/auth/login")
def officer_login(body: Login, request: Request):
    """Email and password to an expiring session token. Wrong email and wrong password get the same answer."""
    con = db.connect()
    try:
        session = officer_auth.login(con, body.email, body.password, _client_id(request))
    except officer_auth.LoginLocked as exc:
        raise HTTPException(429, officer_auth.LOCKED, headers={"Retry-After": str(exc.wait)}) from None
    if not session:
        raise HTTPException(401, officer_auth.INVALID_LOGIN)
    return session


@app.post("/officer/auth/logout")
def officer_logout(authorization: str | None = Header(None)):
    """Revoke this session. Idempotent; a legacy token is not revoked here (re-run scripts/add_officer.py)."""
    return {"revoked": officer_auth.logout(db.connect(), _bearer(authorization))}


@app.get("/officer/auth/me")
def officer_me(authorization: str | None = Header(None), officer: str = Depends(current_officer)):
    session = officer_auth.session_for_token(db.connect(), _bearer(authorization))
    if session:
        return {"officer": officer, "email": session["email"], "expires_at": session["expires_at"], "kind": "session"}
    return {"officer": officer, "email": None, "expires_at": None, "kind": "legacy_token"}


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


@app.get("/officer/cases/{case_id}/delivery-jobs")
def delivery_jobs(case_id: int, officer: str = Depends(current_officer)):
    """Expose dispositions and IDs to officers without recipient or claim secrets."""
    rows = db.connect().execute(
        "SELECT j.id,j.channel,j.state,j.updated_at FROM delivery_jobs j "
        "JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? ORDER BY j.id DESC",
        (case_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/officer/delivery-jobs/{job_id}/reconcile")
def reconcile_delivery(job_id: int, body: ReconcileRequest, officer: str = Depends(current_officer)):
    """Record an officer's verified provider disposition without sending again."""
    from agrireach import delivery
    try:
        with closing(db.connect()) as con:
            delivery.reconcile(con, job_id, officer=officer, accepted=body.accepted,
                               provider_evidence=body.provider_evidence)
    except db.GateError:
        raise HTTPException(409, "Only an unknown delivery job can be reconciled") from None
    except ValueError:
        raise HTTPException(400, "Named officer and verified provider evidence reference required") from None
    except Exception:
        logger.error("Could not record delivery reconciliation")
        raise HTTPException(500, "Could not record reconciliation") from None
    return {"job_id": job_id, "state": "accepted" if body.accepted else "definitely_failed"}


@app.get("/officer/cases/{case_id}/acknowledgement")
def acknowledgement_status(case_id: int, officer: str = Depends(current_officer)):
    """Acknowledgement disposition for an officer. The phone is masked."""
    con = db.connect()
    if not db.get_case(con, case_id):
        raise HTTPException(404, "not found")
    view = acknowledgement.operator_status(con, case_id)
    if view is None:
        raise HTTPException(404, "no acknowledgement")
    return view


@app.post("/officer/acknowledgement-jobs/{job_id}/reconcile")
def reconcile_acknowledgement(job_id: int, body: ReconcileRequest, officer: str = Depends(current_officer)):
    """Record provider evidence for an unknown acknowledgement. Nothing is sent."""
    try:
        with closing(db.connect()) as con:
            acknowledgement.reconcile(con, job_id, officer=officer, accepted=body.accepted,
                               provider_evidence=body.provider_evidence)
    except db.GateError:
        raise HTTPException(409, "Only an unknown acknowledgement job can be reconciled") from None
    except ValueError:
        raise HTTPException(400, "Named officer and verified provider evidence reference required") from None
    except Exception:
        logger.error("Could not record acknowledgement reconciliation")
        raise HTTPException(500, "Could not record reconciliation") from None
    return {"job_id": job_id, "state": "accepted" if body.accepted else "definitely_failed", "handset_delivered": False}


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
    d["generation"] = _generation(db.connect(), d["id"])
    return d


DECIDED_STATUSES = ("approved", "released", "not_delivered", "undeliverable")


def _usage_rows(con, case_id: int) -> list[tuple[str, str | None, dict | None]]:
    """(actor, path, usage) per model_usage row; usage None when the row can't be read (cost then incomplete)."""
    rows = []
    for row in con.execute("SELECT actor, args FROM tool_log WHERE case_id=? AND tool='model_usage' ORDER BY id", (case_id,)):
        try:
            usage = json.loads(row["args"] or "{}")
        except ValueError:
            usage = None
        rows.append((row["actor"], (usage or {}).get("path"), usage))
    return rows


def _usage_totals(rows) -> dict:
    attempted = calls = prompt = completion = 0
    cost, cost_complete, models = 0.0, True, set()
    for _actor, _path, usage in rows:
        if usage is None:
            cost_complete = False
            continue
        calls += usage.get("calls") or 0
        attempted += usage.get("attempted", usage.get("calls")) or 0
        for role in (usage.get("by_role") or {}).values():
            prompt += role.get("prompt_tokens") or 0
            completion += role.get("completion_tokens") or 0
        for entry in usage.get("entries") or []:
            if entry.get("model") and entry.get("ok") is not False:
                models.add(entry["model"])
        if isinstance(usage.get("cost_usd"), (int, float)) and usage.get("cost_complete", True):
            cost += usage["cost_usd"]
        elif usage.get("calls"):
            cost_complete = False
    return {"model_calls": calls, "attempted_calls": attempted, "prompt_tokens": prompt, "completion_tokens": completion,
            "models": sorted(models), "cost_usd": round(cost, 6) if cost_complete else None, "cost_complete": cost_complete}


def _money(cost) -> str:
    return "cost unknown" if cost is None else f"${cost:.6f}"


def _generation(con, case_id: int) -> dict:
    """How the draft and the response were made, from recorded rows only (tool_log, cases).

    state: live_model_draft (a model draft passed every check), model_draft_rejected_source_fallback (the model drafted,
    failed the checks, verbatim passages shown instead; paid calls were made), model_error_source_fallback (the model
    call failed), offline_source_draft (no model call), officer_written (the officer wrote or edited the response that
    was approved), or no_draft. Paid calls are always counted and named: a label never says 'no model' when the case's
    draft run made a model call. Officer-side calls (approval check, farmer-text re-propose) are reported separately."""
    proposal = con.execute("SELECT args FROM tool_log WHERE case_id=? AND tool='farmer_text_proposal' AND actor='agent' "
                           "ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    draft_mode = None
    if proposal:
        try:
            draft_mode = json.loads(proposal["args"] or "{}").get("draft_mode") or None
        except ValueError:
            draft_mode = None
    rows = _usage_rows(con, case_id)
    totals = _usage_totals(rows)
    drafting = _usage_totals([r for r in rows if r[0] == "agent" and not r[1]])
    review = _usage_totals([r for r in rows if not (r[0] == "agent" and not r[1])])
    checks = con.execute("SELECT args FROM tool_log WHERE case_id=? AND tool='draft_checks' ORDER BY id DESC LIMIT 1",
                         (case_id,)).fetchone()
    attempts = None
    if checks:
        try:
            attempts = len(json.loads(checks["args"] or "{}").get("attempts") or [])
        except ValueError:
            attempts = None
    live = bool(draft_mode and draft_mode.startswith("llm"))
    n, cost = drafting["attempted_calls"], _money(drafting["cost_usd"])
    if live:
        state, label = "live_model_draft", "LIVE MODEL DRAFT"
    elif draft_mode and draft_mode.startswith("stub(citation-check-fallback"):
        state = "model_draft_rejected_source_fallback"
        tried = f" after {attempts} attempt(s)" if attempts else ""
        label = (f"SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT: the model draft failed the citation check{tried}, "
                 f"verbatim passages shown ({n} model calls, {cost})")
    elif draft_mode and draft_mode.startswith("stub(llm-error"):
        state = "model_error_source_fallback"
        label = f"SOURCE DRAFT AFTER MODEL ERROR: verbatim passages shown ({n} model calls attempted, {cost})"
    elif draft_mode and n:
        state = "source_draft_with_model_calls"
        label = f"SOURCE DRAFT: verbatim passages shown; the draft run made {n} model calls ({cost})"
    elif draft_mode:
        state, label = "offline_source_draft", "NO MODEL CALLS: offline source draft (verbatim passages)"
    else:
        state, label = "no_draft", "NO DRAFT (clarification, emergency or not yet drafted)"
    draft_state, draft_label = state, label
    case = con.execute("SELECT status, draft, final_text, farmer_text, farmer_draft, officer FROM cases WHERE id=?",
                       (case_id,)).fetchone()
    officer_edited = officer_farmer_text = False
    if case is not None and case["status"] in DECIDED_STATUSES and case["final_text"] is not None:
        officer_edited = (case["final_text"] or "").strip() != (case["draft"] or "").strip()
        try:
            proposed = (json.loads(case["farmer_draft"] or "null") or {}).get("text") or ""
        except ValueError:
            proposed = ""
        officer_farmer_text = bool(case["farmer_text"]) and case["farmer_text"].strip() != proposed.strip()
    if officer_edited or officer_farmer_text:
        what = " and ".join(x for x, on in (("officer text", officer_edited), ("farmer text", officer_farmer_text)) if on)
        state = "officer_written"
        label = f"OFFICER-WRITTEN RESPONSE: {case['officer']} wrote or edited the approved {what}; draft was: {draft_label}"
    return {"state": state, "draft_state": draft_state, "draft_label": draft_label,
            "draft_mode": draft_mode, "live_model": live, "label": label, "model_used": totals["attempted_calls"] > 0,
            "draft_attempts": attempts, "officer_edited_officer_text": officer_edited,
            "officer_wrote_farmer_text": officer_farmer_text,
            "drafting_usage": drafting, "review_usage": review,
            "model_calls": totals["model_calls"], "attempted_calls": totals["attempted_calls"],
            "prompt_tokens": totals["prompt_tokens"], "completion_tokens": totals["completion_tokens"],
            "models": totals["models"], "cost_usd": totals["cost_usd"], "cost_complete": totals["cost_complete"]}


def _tool_evidence(con, case_id: int) -> dict:
    """Recorded tool execution for the case, in order. Nothing is inferred: runs before the mcp_tool_calls and
    draft_checks rows existed say recorded=false. Server-side retrieval rows (search_guidance etc.) are written
    before the MCP server knows the case and carry no case id, so they are not listed here."""
    rows = [dict(r) for r in con.execute("SELECT id, ts, actor, tool, args, result_summary, ok FROM tool_log "
                                         "WHERE case_id=? ORDER BY id", (case_id,))]
    def load(r):
        try:
            return json.loads(r["args"] or "null")
        except ValueError:
            return None
    mcp = [load(r) | {"logged_at": r["ts"]} for r in rows if r["tool"] == "mcp_tool_calls" and isinstance(load(r), dict)]
    checks = [load(r) | {"logged_at": r["ts"]} for r in rows if r["tool"] == "draft_checks" and isinstance(load(r), dict)]
    timeline = [{"seq": i + 1, "ts": r["ts"], "actor": r["actor"], "tool": r["tool"], "ok": bool(r["ok"]),
                 "summary": (r["result_summary"] or "")[:300]} for i, r in enumerate(rows)]
    return {"mcp_runs": mcp, "mcp_recorded": bool(mcp), "draft_checks": checks, "draft_checks_recorded": bool(checks),
            "timeline": timeline}


@app.get("/health")
def health():
    return {"ok": True, "draft_mode": llm.mode()}


def _consented_phone(raw: str, consent: bool) -> str:
    """Validate before a case exists. The error text does not repeat the submitted number."""
    if not consent:
        return ""
    text = (raw or "").strip()
    if not text:
        raise HTTPException(422, "Enter a Ghana mobile number, or leave SMS updates unchecked.")
    try:
        return normalize_phone(text)
    except PhoneError as exc:
        raise HTTPException(422, str(exc)) from exc


def _with_acknowledgement(con, case_id: int, body: dict) -> dict:
    """Add SMS state when one exists. Legacy cases keep their previous response shape."""
    sms = acknowledgement.public_status(con, case_id)
    if sms["status"] != "not_requested":
        body["acknowledgement"] = sms
    return body


REJECTED_FARMER_MESSAGE = (
    "An extension officer reviewed this question and did not approve any advice. Nothing was sent to you."
)
EVIDENCE_GAP_FARMER_MESSAGE = (
    "AgriReach has no sourced guidance for this question. An extension officer will investigate it. "
    "No treatment advice has been approved."
)
PROCESSING_FAILURE_MESSAGE = (
    "AgriReach could not finish preparing this question. An extension officer will review it. "
    "No treatment advice has been approved."
)


# Fixed referral text for a possible poisoning or animal deaths. Not agricultural advice; no model writes it.
EMERGENCY_FARMER_MESSAGE = emergency.FARMER_MESSAGE


def _emergency(reasons) -> bool:
    return any(emergency.is_emergency_reason(reason) for reason in reasons or [])


def _row_emergency(row) -> bool:
    return _emergency(json.loads(row["urgent_reasons"] or "[]"))


def _evidence_gap(reasons, sources) -> bool:
    """A covered question with nothing retrieved. Uncovered crops and contact requests stay on their own path."""
    if sources:
        return False
    joined = " | ".join(str(reason) for reason in reasons or [])
    if "no grounded evidence found in corpus" not in joined:
        return False
    if "is not covered" in joined or "how to reach an extension officer" in joined:
        return False
    return True


def _row_evidence_gap(row) -> bool:
    return _evidence_gap(json.loads(row["urgent_reasons"] or "[]"), json.loads(row["sources"] or "[]"))


def _row_processing_failure(row) -> bool:
    clarification = db._open_clarification(row)
    return bool(clarification and clarification.get("processing_failure"))


def _submission_message(status: str, clarification: str | None) -> str:
    """Describe the state that was actually saved. Draft is not officer review."""
    if clarification:
        return AWAITING_FARMER
    if status == "pending_review":
        return ("Your question has been received. It is waiting for an extension officer to review. "
                "Advice is not available yet.")
    return "Your question has been received."


def _submission_allowed(request: Request, phone: str = "") -> None:
    """Farmer submissions per client (and per phone number) in a time window; see agrireach.ratelimit.

    The farmer portal calls this API from its own container, so every browser would share the portal's address.
    With AGRIREACH_TRUST_PORTAL_CLIENT_HEADER=1 the portal's X-AgriReach-Client value (a digest of the browser's
    address) is used instead. Enable it only where the API port is reachable by the portals alone, otherwise a
    caller could pick a new value for each request."""
    client = _client_id(request)
    keys = [ratelimit.key("client", client)] + ([ratelimit.key("phone", phone)] if phone else [])
    wait = ratelimit.check(keys)
    if wait is not None:
        raise HTTPException(429, ratelimit.MESSAGE, headers={"Retry-After": str(wait)})


@app.post("/farmer/session")
def farmer_session(request: Request):
    """A private farmer session for the farmer portal to keep server-side. It reads only cases filed with it."""
    _submission_allowed(request)
    return officer_auth.new_farmer_session(db.connect())


@app.get("/farmer/session/cases")
def farmer_session_cases(x_farmer_session: str | None = Header(None)):
    """This session's own cases, newest first, as the farmer case view (approved text only). Never by phone."""
    con = db.connect()
    if not officer_auth.farmer_session_valid(con, x_farmer_session):
        raise HTTPException(401, "farmer session expired or unknown")
    items = []
    for case_id in officer_auth.farmer_session_cases(con, x_farmer_session):
        row = db.get_case(con, case_id)
        if row:
            items.append(_with_acknowledgement(con, case_id, _farmer_case_body(con, case_id, row))
                         | {"question": row["question"], "created_at": row["created_at"]})
    return items


def _farmer_may_read(con, case_id: int, token: str | None, session: str | None) -> bool:
    """A per-case access token or the private session that filed the case. A phone number never counts."""
    return db.farmer_case_token_valid(con, case_id, token) or officer_auth.farmer_session_owns(con, session, case_id)


@app.post("/ask")
async def ask(a: Ask, request: Request, x_farmer_session: str | None = Header(None)):
    phone = _consented_phone(a.phone, a.sms_consent)
    if x_farmer_session is not None and not officer_auth.farmer_session_valid(db.connect(), x_farmer_session):
        raise HTTPException(401, "farmer session expired or unknown")
    _submission_allowed(request, phone)
    out = await agent.run(a.question, a.crop, a.region)
    if x_farmer_session is not None:
        officer_auth.link_farmer_case(db.connect(), x_farmer_session, out["case_id"])
    # The farmer gets only an acknowledgement or a clarifying question, never the draft.
    # The phone is applied after the case commit and is not passed to the model.
    access_token = db.issue_farmer_case_token(db.connect(), out["case_id"])
    sms = acknowledgement.schedule(out["case_id"], phone, bool(phone))
    queued = out.get("status") == "pending_review" and not out.get("clarification")
    urgent = queued and _emergency(out.get("urgent_reasons"))
    gap = queued and not urgent and _evidence_gap(out.get("urgent_reasons"), out.get("sources"))
    message = (EMERGENCY_FARMER_MESSAGE if urgent else EVIDENCE_GAP_FARMER_MESSAGE if gap
               else _submission_message(out["status"], out.get("clarification")))
    body = {"case_id": out["case_id"], "access_token": access_token, "status": out["status"],
            "clarification": out["clarification"], "message": message, "acknowledgement": sms}
    if urgent:
        body["emergency"] = True
    if gap:
        body["evidence_gap"] = True
    if out.get("clarification"):
        body["revision"] = db.get_case(db.connect(), out["case_id"])["revision"]
    return body


@app.post("/farmer/cases/{case_id}/supplement")
async def supplement(case_id: int, body: Supplement, request: Request,
                     x_case_access_token: str | None = Header(None), x_farmer_session: str | None = Header(None)):
    """Add the farmer's own missing crop or place to the same draft. Nothing is approved here."""
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row or not _farmer_may_read(con, case_id, x_case_access_token, x_farmer_session):
        raise HTTPException(404, "not found")
    _submission_allowed(request)
    if row["status"] != "draft" or not db._open_clarification(row):
        raise HTTPException(409, "Case is not waiting for farmer information")
    if body.expected_revision != row["revision"]:
        raise HTTPException(409, "stale_revision: reload the case")
    stored = db._open_clarification(row)
    replies = stored["replies"] + [body.text]
    crop, region, clar = agent.clarification_gap(
        row["question"], replies, crop=row["crop"] or "", region=row["region"] or "")
    if clar:
        try:
            updated = db.continue_clarification(con, case_id, expected_revision=body.expected_revision,
                                                clarification=clar, replies=replies, crop=crop, region=region)
        except db.GateError as exc:
            raise HTTPException(409, str(exc))
        return {"case_id": case_id, "status": "draft", "answer": None, "clarification": clar,
                "revision": updated["revision"], "message": AWAITING_FARMER}
    try:
        out = await agent.run(row["question"], crop=crop, region=region, case_id=case_id,
                              expected_revision=body.expected_revision, farmer_replies=replies)
    except Exception as exc:
        if _revision_conflict(exc):
            raise HTTPException(409, "stale_revision: reload the case")
        raise
    completed = _farmer_case_body(con, out["case_id"], db.get_case(con, out["case_id"]))
    if completed.get("evidence_gap") or completed.get("emergency"):
        return completed
    return {"case_id": completed["case_id"], "status": completed["status"], "answer": None,
            "clarification": None, "message": _submission_message(completed["status"], None)}


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
    return _case(row) | {"log": db.case_log(con, case_id), "tool_evidence": _tool_evidence(con, case_id)}


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
    # A reviewable case cannot be rejected or sent back without saying why (other states keep their own errors).
    if d.decision in ("reject", "request_info") and not (d.note or "").strip() and (case := db.get_case(con, case_id)) and case["status"] == "pending_review":
        raise HTTPException(400, "note required: say why you are rejecting or what information you need")
    warnings = []
    try:
        row = db.officer_decide(con, case_id, officer=officer, decision=d.decision, edited_text=d.edited_text,
                                note=d.note, farmer_text=d.farmer_text, expected_revision=d.expected_revision, acknowledgement=d.acknowledgement, approved_voice_script=d.approved_voice_script)
        latest_assessment = con.execute("SELECT assessment FROM safety_assessments WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
        warnings = json.loads(latest_assessment[0]).get("informational", []) if latest_assessment else []
        delivery = None
        if row["status"] == "approved":
            row = db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
            try:
                delivery = service.deliver(con, case_id, service.configured_channels()) if row["status"] == "released" else {"ok": False, "outcome": "undeliverable"}
            except ValueError as e:  # approved and released, but the send failed mid-way: outcome unknown, not a 400
                delivery = {"ok": False, "outcome": "unknown", "detail": str(e)}
            row = db.get_case(con, case_id)  # 'not_delivered' if the send failed; stays 'released' if its outcome is unknown
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


@app.post("/officer/cases/{case_id}/assess")
def assess(case_id: int, body: FarmerText, officer: str = Depends(current_officer)):
    """Re-run the safety assessment on the officer's farmer text. Read-only: nothing is approved or sent."""
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row:
        raise HTTPException(404, "not found")
    with llm.usage_logged(case_id, f"officer:{officer}", "assess"):
        return approval.assess_candidate(body.farmer_text, approval.context(con, row))


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
def farmer_view(case_id: int, x_case_access_token: str | None = Header(None),
                x_farmer_session: str | None = Header(None)):
    """Case numbers are sequential; require a separate secret (case token or the filing session) for every view."""
    con = db.connect()
    row = db.get_case(con, case_id)
    if not row or not _farmer_may_read(con, case_id, x_case_access_token, x_farmer_session):
        raise HTTPException(404, "not found")
    return _with_acknowledgement(con, case_id, _farmer_case_body(con, case_id, row))


def _farmer_case_body(con, case_id: int, row) -> dict:
    if row["status"] == "draft" and (clarification := db._open_clarification(row)):
        body = {"case_id": case_id, "status": "draft", "answer": None, "revision": row["revision"],
                "clarification": clarification["clarification"], "message": AWAITING_FARMER}
        if clarification.get("processing_failure"):
            body["message"] = PROCESSING_FAILURE_MESSAGE
            body["processing_failure"] = True
        return body
    if row["status"] == "undeliverable":  # approved, but the number was removed (STOP or retention purge)
        return {"case_id": case_id, "status": "undeliverable", "answer": None,
                "message": "No answer was sent: this number was removed from AgriReach."}
    if row["status"] == "not_delivered":  # approved, but the channel send failed: no answer has reached the farmer
        return {"case_id": case_id, "status": "not_delivered", "answer": None,
                "message": "Your answer has not been sent yet. An extension officer is working on it."}
    if row["status"] == "rejected":
        return {"case_id": case_id, "status": "rejected", "answer": None, "message": REJECTED_FARMER_MESSAGE}
    if row["status"] != "released":
        body = {"case_id": case_id, "status": row["status"], "answer": None,
                "message": "Waiting for an extension officer to review your question."}
        if row["status"] == "pending_review" and _row_emergency(row):
            body["message"] = EMERGENCY_FARMER_MESSAGE
            body["emergency"] = True
        elif row["status"] == "pending_review" and _row_evidence_gap(row):
            body["message"] = EVIDENCE_GAP_FARMER_MESSAGE
            body["evidence_gap"] = True
        return body
    contact = db.get_contact(con, case_id)
    job = con.execute("SELECT j.state FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? ORDER BY j.id DESC LIMIT 1", (case_id,)).fetchone()
    if contact and job and job["state"] != "accepted":
        return {"case_id": case_id, "status": row["status"], "delivery_status": job["state"], "answer": None,
                "message": "Delivery acceptance has not been confirmed."}
    from agrireach.approval import validated_approval
    try:
        _approval, payload = validated_approval(con, case_id)
    except db.GateError:
        # SafetyError is a GateError. Either failed check withholds the answer. A legacy_unvalidated
        # row stays stored for history and is not returned as the authorized text.
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
        data = await audio.read(16_000_001)
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
