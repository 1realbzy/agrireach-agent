"""Administrative SMS acknowledgement. Separate from approved-advice delivery.

The case is already committed before a job is queued. The provider is called
only after the claim transaction commits. Unknown outcomes are not claimed
again. A simulated result is never handset delivery.

Recovery:
* pending: a later dispatch may claim it once.
* sending, older than 15 minutes: becomes unknown. It is not sent again.
* definitely_failed: dispatch may claim it again, because the provider refused
  or the request never left this process.
* unknown: stays unknown until an officer records provider evidence. That
  record does not send a message.
* accepted: already accepted by the provider or the simulator. Not sent again.
* A crash after commit and before claim leaves the job pending.
* A crash after claim leaves sending, then unknown. It is not sent again.
"""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone

from agrireach import approval, db
from agrireach.channels import mnotify
from agrireach.phone import mask_phone, normalize

TEMPLATE = (
    "AgriReach: We have received your farming question. Reference: {case_reference}. "
    "We will notify you when an extension officer has reviewed the advice."
)
OUTCOMES = ("accepted", "definitely_failed", "unknown", "undeliverable")


def message_for(case_id: int) -> str:
    """Fixed template. The only interpolated value is the case reference."""
    return TEMPLATE.format(case_reference=case_id)


def remember_consent(con, case_id: int, phone_e164: str) -> None:
    """Store a consented number when SMS is disabled. No job and no send."""
    stored = normalize(phone_e164)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT INTO farmer_sms_contacts(case_id, phone_e164, consent, created_at) VALUES (?, ?, 'granted', ?) "
            "ON CONFLICT(case_id) DO NOTHING",
            (case_id, stored, db.now()))
        approval.audit(con, case_id, "system", "sms_consent_recorded", stored=True)
        con.commit()
    except BaseException:
        con.rollback()
        raise


def enqueue(con, case_id: int, phone_e164: str, job_mode: str) -> int:
    """Persist the number and one pending job in the same transaction."""
    if job_mode not in ("simulated", "live"):
        raise ValueError("only simulated or live acknowledgement jobs are queued")
    stored = normalize(phone_e164)
    try:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT id FROM acknowledgement_jobs WHERE case_id=?", (case_id,)).fetchone()
        if existing:
            con.rollback()
            return existing["id"]
        con.execute(
            "INSERT INTO farmer_sms_contacts(case_id, phone_e164, consent, created_at) VALUES (?, ?, 'granted', ?) "
            "ON CONFLICT(case_id) DO NOTHING",
            (case_id, stored, db.now()))
        cur = con.execute(
            "INSERT INTO acknowledgement_jobs(case_id, state, mode, updated_at) VALUES (?, 'pending', ?, ?)",
            (case_id, job_mode, db.now()))
        approval.audit(con, case_id, "system", "acknowledgement_scheduled", mode=job_mode,
                       simulated=job_mode == "simulated")
        con.commit()
        return cur.lastrowid
    except BaseException:
        con.rollback()
        raise


def expire_claim(con, job_id: int, *, current_time: datetime | None = None) -> None:
    """An abandoned sending claim becomes unknown and cannot be sent again."""
    cutoff = ((current_time or datetime.now(timezone.utc)) - timedelta(minutes=15)).isoformat(timespec="seconds")
    with con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT id, claim_id, case_id FROM acknowledgement_jobs WHERE id=? AND state='sending' AND updated_at<=?",
            (job_id, cutoff)).fetchone()
        if not row:
            return
        con.execute(
            "UPDATE acknowledgement_jobs SET state='unknown', updated_at=? WHERE id=? AND claim_id=? AND state='sending'",
            (db.now(), row["id"], row["claim_id"]))
        con.execute(
            "UPDATE acknowledgement_attempts SET outcome='unknown', completed_at=?, detail=? WHERE claim_id=? AND outcome='sending'",
            (db.now(), json.dumps({"reason": "claim expired", "handset_delivered": False}), row["claim_id"]))
        approval.audit(con, row["case_id"], "system", "acknowledgement_unknown", job_id=row["id"], reason="claim expired")


def claim(con, job_id: int) -> tuple | None:
    """Claim a pending or definitely failed job. Returns None when no send may start."""
    expire_claim(con, job_id)
    try:
        con.execute("BEGIN IMMEDIATE")
        job = con.execute("SELECT * FROM acknowledgement_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] not in ("pending", "definitely_failed"):
            con.rollback()
            return None
        contact = con.execute("SELECT phone_e164 FROM farmer_sms_contacts WHERE case_id=?", (job["case_id"],)).fetchone()
        if not contact:
            con.execute(
                "UPDATE acknowledgement_jobs SET state='undeliverable', claim_id=NULL, updated_at=? WHERE id=? AND state=?",
                (db.now(), job_id, job["state"]))
            approval.audit(con, job["case_id"], "system", "acknowledgement_undeliverable", job_id=job_id,
                           reason="phone removed")
            con.commit()
            return None
        claim_id = secrets.token_hex(24)
        changed = con.execute(
            "UPDATE acknowledgement_jobs SET state='sending', claim_id=?, updated_at=? WHERE id=? AND state=?",
            (claim_id, db.now(), job_id, job["state"]))
        if changed.rowcount != 1:
            raise db.GateError("acknowledgement claim lost")
        con.execute(
            "INSERT INTO acknowledgement_attempts(job_id, claim_id, outcome, started_at) VALUES (?, ?, 'sending', ?)",
            (job_id, claim_id, db.now()))
        approval.audit(con, job["case_id"], "channel", "acknowledgement_claimed", job_id=job_id)
        con.commit()
        return job_id, claim_id, contact["phone_e164"], message_for(job["case_id"]), job["mode"], job["case_id"]
    except BaseException:
        con.rollback()
        raise


def complete(con, job_id: int, claim_id: str, outcome: str, *, provider_id: str | None = None,
             simulated: bool = False, detail: str = "") -> None:
    """Record this claim only. A later claim is left untouched."""
    if outcome not in OUTCOMES:
        raise ValueError("Invalid transport outcome")
    with con:
        job = con.execute("SELECT case_id FROM acknowledgement_jobs WHERE id=?", (job_id,)).fetchone()
        changed = con.execute(
            "UPDATE acknowledgement_jobs SET state=?, updated_at=? WHERE id=? AND claim_id=? AND state='sending'",
            (outcome, db.now(), job_id, claim_id))
        if changed.rowcount != 1:
            raise db.GateError("Claim is no longer active; reconcile its late result")
        con.execute(
            "UPDATE acknowledgement_attempts SET outcome=?, completed_at=?, detail=? WHERE claim_id=?",
            (outcome, db.now(), json.dumps({
                "provider_id": provider_id, "simulated": simulated, "handset_delivered": False, "detail": detail,
            }), claim_id))
        approval.audit(con, job["case_id"], "channel", "acknowledgement_" + outcome, job_id=job_id,
                       simulated=simulated, handset_delivered=False)


def reconcile(con, job_id: int, *, officer: str, accepted: bool, provider_evidence: str) -> None:
    """Record verified provider evidence. This never sends or retries."""
    if not provider_evidence.strip() or not officer.strip():
        raise ValueError("Named officer and verified provider evidence reference required")
    with con:
        con.execute("BEGIN IMMEDIATE")
        job = con.execute("SELECT * FROM acknowledgement_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] != "unknown":
            raise db.GateError("Only an unknown acknowledgement can be reconciled")
        state = "accepted" if accepted else "definitely_failed"
        con.execute("UPDATE acknowledgement_jobs SET state=?, updated_at=? WHERE id=?", (state, db.now(), job_id))
        approval.audit(con, job["case_id"], officer, "acknowledgement_reconciled", job_id=job_id,
                       provider_evidence=provider_evidence, accepted=accepted, handset_delivered=False)


def dispatch(con, job_id: int, *, client=None) -> dict:
    """Send only after the claim commits. A second call does not send again."""
    claimed = claim(con, job_id)
    job = con.execute("SELECT case_id, mode FROM acknowledgement_jobs WHERE id=?", (job_id,)).fetchone()
    if claimed is None:
        return public_status(con, job["case_id"])
    job_id, claim_id, phone_e164, text, job_mode, case_id = claimed
    try:
        if job_mode == "simulated":
            result = mnotify.simulate(case_id)
        else:
            result = mnotify.transmit(phone_e164, text, client=client)
    except Exception:
        complete(con, job_id, claim_id, "unknown",
                 detail="outcome unknown: dispatch failed before a result was recorded")
        raise
    outcome = result.outcome if result.outcome in OUTCOMES else "unknown"
    complete(con, job_id, claim_id, outcome, provider_id=result.provider_id,
             simulated=result.simulated, detail=result.detail)
    return public_status(con, case_id)


def schedule(case_id: int, phone_e164: str, consent: bool, *, client=None) -> dict:
    """Queue and dispatch after the case exists. A scheduling failure keeps the case."""
    if not consent or not str(phone_e164 or "").strip():
        return _not_sent("not_requested", "No confirmation SMS was sent.")
    chosen = mnotify.mode()
    con = db.connect()
    if chosen == "disabled":
        remember_consent(con, case_id, phone_e164)
        return _not_sent("disabled", "SMS confirmation is turned off. No message was sent.")
    try:
        job_id = enqueue(con, case_id, phone_e164, chosen)
    except Exception:
        return _not_sent(
            "not_scheduled",
            "Your question was saved. The confirmation SMS could not be scheduled. Do not send the question again.")
    return dispatch(con, job_id, client=client)


def public_status(con, case_id: int) -> dict:
    """Farmer-facing acknowledgement state. No phone number and no handset delivery."""
    job = con.execute("SELECT state, mode FROM acknowledgement_jobs WHERE case_id=?", (case_id,)).fetchone()
    contact = con.execute("SELECT 1 FROM farmer_sms_contacts WHERE case_id=?", (case_id,)).fetchone()
    if job is None and contact is None:
        return _not_sent("not_requested", "No confirmation SMS was sent.")
    if job is None:
        return _not_sent("disabled", "SMS confirmation is turned off. No message was sent.")
    simulated = job["mode"] == "simulated"
    state = job["state"]
    if state == "accepted" and simulated:
        text = "A simulated SMS confirmation was recorded. No message was sent to a phone."
    elif state == "accepted":
        text = "The SMS provider accepted a confirmation. This does not mean your phone has received it."
    elif state == "definitely_failed":
        text = "Your question was saved. The confirmation SMS was not accepted."
    elif state == "unknown":
        text = ("Your question was saved. The confirmation SMS outcome is uncertain, "
                "so it will not be sent again automatically.")
    elif state == "undeliverable":
        text = "Your question was saved. The confirmation SMS cannot be sent."
    elif state == "sending":
        text = "Your question was saved. The confirmation SMS has not been confirmed."
    else:
        text = "Your question was saved. The confirmation SMS is waiting to be sent."
    return {"status": state, "simulated": simulated, "handset_delivered": False, "message": text}


def operator_status(con, case_id: int) -> dict | None:
    """Officer view. The phone is masked. Simulated results stay labelled."""
    job = con.execute(
        "SELECT id, state, mode, updated_at FROM acknowledgement_jobs WHERE case_id=?", (case_id,)).fetchone()
    contact = con.execute("SELECT phone_e164 FROM farmer_sms_contacts WHERE case_id=?", (case_id,)).fetchone()
    if job is None and contact is None:
        return None
    body = public_status(con, case_id)
    body["job_id"] = job["id"] if job else None
    body["mode"] = job["mode"] if job else "disabled"
    body["updated_at"] = job["updated_at"] if job else None
    body["phone_masked"] = mask_phone(contact["phone_e164"]) if contact else None
    return body


def _not_sent(status: str, message: str) -> dict:
    return {"status": status, "simulated": False, "handset_delivered": False, "message": message}
