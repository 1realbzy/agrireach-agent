"""Atomic dispatch claims. Unknown external outcomes are never automatically retried."""
from __future__ import annotations

import secrets

from agrireach import approval, db


def claim(con, case_id: int) -> tuple[int, str] | None:
    """Claim a pending or definitely failed job, or return its existing disposition.

    Raises GateError for stale approval or unavailable release. External sends must
    start only after this transaction commits. Crashed claims require reconciliation.
    """
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


def complete(con, case_id: int, job_id: int, claim_id: str, outcome: str):
    """Record only this claim's outcome; never overwrite a later attempt."""
    if outcome not in ("accepted", "definitely_failed", "unknown", "undeliverable"):
        raise ValueError("Invalid transport outcome")
    with con:
        changed = con.execute("UPDATE delivery_jobs SET state=?,updated_at=? WHERE id=? AND claim_id=? AND state='sending'",
                              (outcome, db.now(), job_id, claim_id))
        if changed.rowcount != 1:
            raise db.GateError("Claim is no longer active; reconcile its late result")
        con.execute("UPDATE delivery_attempts SET outcome=?,completed_at=? WHERE claim_id=?",
                    (outcome, db.now(), claim_id))
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
    This action is deliberately not exposed as a routine retry button.
    """
    if not provider_evidence.strip() or not officer.strip():
        raise ValueError("Named officer and verified provider evidence reference required")
    with con:
        job = con.execute("SELECT * FROM delivery_jobs WHERE id=?", (job_id,)).fetchone()
        if not job or job["state"] != "unknown":
            raise db.GateError("Only an unknown job can be reconciled")
        con.execute("UPDATE delivery_jobs SET state=?,updated_at=? WHERE id=?",
                    ("accepted" if accepted else "definitely_failed", db.now(), job_id))
        approval.audit(con, None, officer, "delivery_reconciled", job_id=job_id,
                       provider_evidence=provider_evidence, accepted=accepted)
