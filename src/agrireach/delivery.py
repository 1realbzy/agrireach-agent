"""Atomic dispatch claims. Unknown external outcomes are never automatically retried."""
from __future__ import annotations

import secrets
import json
from datetime import datetime, timedelta, timezone

from agrireach import approval, db


def expire_claims(con, case_id: int, *, current_time: datetime | None = None) -> None:
    """After 15 minutes, interrupted claims become unknown, never retryable.

    The bound exceeds the configured local TTS and provider request deadlines.
    This maintenance runs before a release/claim attempt; no background worker is
    required. A matching claim check prevents overwriting a completed send.
    """
    cutoff = ((current_time or datetime.now(timezone.utc)) - timedelta(minutes=15)).isoformat(timespec="seconds")
    with con:
        con.execute("BEGIN IMMEDIATE")
        rows = con.execute("SELECT j.id,j.claim_id FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? AND j.state='sending' AND j.updated_at<=?",
                           (case_id, cutoff)).fetchall()
        for row in rows:
            con.execute("UPDATE delivery_jobs SET state='unknown',updated_at=? WHERE id=? AND claim_id=? AND state='sending'",
                        (db.now(), row["id"], row["claim_id"]))
            con.execute("UPDATE delivery_attempts SET outcome='unknown',completed_at=? WHERE claim_id=? AND outcome='sending'",
                        (db.now(), row["claim_id"]))
            approval.audit(con, case_id, "system", "delivery_unknown", job_id=row["id"], reason="claim expired")


def claim(con, case_id: int) -> tuple[int, str] | None:
    """Claim a pending or definitely failed job, or return its existing disposition.

    Raises GateError for stale approval or unavailable release. External sends must
    start only after this transaction commits. Crashed claims require reconciliation.
    """
    expire_claims(con, case_id)
    try:
        con.execute("BEGIN IMMEDIATE")
        record, payload = approval.validated_approval(con, case_id)
        if db.get_case(con, case_id)["status"] != "released":
            raise db.GateError("Release is required before delivery")
        contact = db.get_contact(con, case_id)
        if not contact:
            con.rollback()
            return None
        if contact["sender_id"] in db.REMOVED:
            raise db.GateError("Recipient removed")
        job = con.execute("SELECT * FROM delivery_jobs WHERE approval_id=? AND channel=?",
                          (record["id"], contact["channel"])).fetchone()
        if not job:
            raise db.GateError("Release must create the delivery job")
        if job["recipient_hash"] != db._token_hash(contact["sender_id"]):
            raise db.GateError("Recipient binding changed")
        if job["state"] not in ("pending", "definitely_failed"):
            con.rollback()
            return None
        claim_id = secrets.token_hex(24)
        con.execute("UPDATE delivery_jobs SET state='sending',claim_id=?,updated_at=? WHERE id=?", (claim_id, db.now(), job["id"]))
        con.execute("INSERT INTO delivery_attempts(job_id,claim_id,outcome,started_at) VALUES (?,?,'sending',?)",
                    (job["id"], claim_id, db.now()))
        approval.audit(con, case_id, "channel", "delivery_claimed", approval_id=record["id"], job_id=job["id"], claim_id=claim_id)
        con.commit()
        return job["id"], claim_id
    except BaseException:
        con.rollback()
        raise


def complete(con, case_id: int, job_id: int, claim_id: str, outcome: str, *, provider_id: str | None = None):
    """Record only this claim's outcome; never overwrite a later attempt."""
    if outcome not in ("accepted", "definitely_failed", "unknown", "undeliverable"):
        raise ValueError("Invalid transport outcome")
    with con:
        changed = con.execute("UPDATE delivery_jobs SET state=?,updated_at=? WHERE id=? AND claim_id=? AND state='sending'",
                              (outcome, db.now(), job_id, claim_id))
        if changed.rowcount != 1:
            raise db.GateError("Claim is no longer active; reconcile its late result")
        con.execute("UPDATE delivery_attempts SET outcome=?,completed_at=?,detail=? WHERE claim_id=?",
                    (outcome, db.now(), json.dumps({"provider_id": provider_id}), claim_id))
        approval.audit(con, case_id, "channel", "delivery_" + outcome, job_id=job_id)


def interrupted(con, job_id: int, *, officer: str):
    """Mark an interrupted sending attempt unknown; this never permits resend."""
    with con:
        job = con.execute("SELECT * FROM delivery_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] != "sending":
            raise db.GateError("No active sending job")
        con.execute("UPDATE delivery_jobs SET state='unknown',updated_at=? WHERE id=?", (db.now(), job_id))
        approval.audit(con, None, officer, "delivery_unknown", job_id=job_id, reason="interrupted claim")


def reconcile(con, job_id: int, *, officer: str, accepted: bool, provider_evidence: str):
    """Record an authenticated operator's verified provider evidence.

    The caller must verify the provider record outside this function. The evidence
    reference is retained for review; an ambiguous note is not proof of failure.
    This action records provider evidence; it never sends or retries a message.
    """
    if not provider_evidence.strip() or not officer.strip():
        raise ValueError("Named officer and verified provider evidence reference required")
    with con:
        # Serialize reconciliation with competing reconciliations and claims.
        con.execute("BEGIN IMMEDIATE")
        job = con.execute("SELECT * FROM delivery_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] != "unknown":
            raise db.GateError("Only an unknown job can be reconciled")
        con.execute("UPDATE delivery_jobs SET state=?,updated_at=? WHERE id=?",
                    ("accepted" if accepted else "definitely_failed", db.now(), job_id))
        case_id = con.execute("SELECT case_id FROM approvals WHERE id=?", (job["approval_id"],)).fetchone()[0]
        approval.audit(con, case_id, officer, "delivery_reconciled", job_id=job_id,
                       provider_evidence=provider_evidence, accepted=accepted)
