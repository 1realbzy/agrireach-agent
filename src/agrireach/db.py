"""SQLite case store with an enforced officer approval gate.

Status lifecycle:
  draft -> pending_review -> approved -> released
                          -> rejected | needs_info
Agent-side writes may ONLY set 'draft' or 'pending_review'. Approval, rejection,
editing and release are officer-only functions, and release requires approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
from contextlib import closing
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_STATUSES = {"draft", "pending_review"}
OFFICER_DECISIONS = {"approve", "edit_approve", "reject", "request_info"}


class GateError(Exception):
    """Raised when an action would bypass the officer approval gate."""


class SafetyError(GateError):
    """Structured safety rejection; callers must preserve findings and recovery."""
    def __init__(self, assessment):
        self.assessment = assessment
        super().__init__(assessment["outcome"])


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///agrireach.db")
    return url.removeprefix("sqlite:///")


def connect(path: str | None = None, *, adopt_legacy_sms=False) -> sqlite3.Connection:
    p = path or db_path()
    existing_file = p != ":memory:" and Path(p).exists()
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=10)
    con.row_factory = sqlite3.Row
    from agrireach.migrations import ensure_schema
    try:
        ensure_schema(con, p, existing_file=existing_file, adopt_legacy_sms=adopt_legacy_sms)
    except BaseException:
        con.close()
        raise
    return con


def log(con, actor: str, tool: str, args: dict, summary: str, ok: bool = True, case_id: int | None = None, *,
        commit: bool = True, args_limit: int | None = 2000):
    """args_limit None stores the whole JSON. The default slice stays for ordinary tool rows."""
    encoded = json.dumps(args, ensure_ascii=False)
    if args_limit is not None:
        encoded = encoded[:args_limit]
    con.execute(
        "INSERT INTO tool_log(ts,case_id,actor,tool,args,result_summary,ok) VALUES (?,?,?,?,?,?,?)",
        (now(), case_id, actor, tool, encoded, summary[:2000], int(ok)),
    )
    if commit:
        con.commit()


def agent_upsert_case(con, *, status: str, question: str = "", case_id: int | None = None, crop=None, region=None,
                      draft=None, sources=None, priority="routine", urgent_reasons=None, farmer_draft=None,
                      inbound_claim: dict | None = None, expected_revision: int | None = None, require_draft: bool = False) -> int:
    """farmer_draft: AgriReach's PROPOSED farmer-facing text (JSON, see farmer_reply). Only the officer's approved
    farmer_text is ever delivered."""
    if status not in AGENT_STATUSES:
        log(con, "agent", "create_or_update_case", {"status": status, "case_id": case_id},
            f"BLOCKED: agent may not set status '{status}'", ok=False, case_id=case_id)
        raise GateError(f"agent may only set {sorted(AGENT_STATUSES)}, not '{status}'")
    if priority not in {"routine", "urgent"}:
        raise ValueError("priority must be routine or urgent")
    t = now()
    if case_id is None and not question:
        raise ValueError("question required for a new case")
    if case_id is None and inbound_claim:
        try:
            con.execute("BEGIN IMMEDIATE")
            inbox = require_inbound_claim(con, inbound_claim)
            if inbox["case_id"] is not None:
                raise GateError("Inbound already has a case; reconcile without replay")
            cur = con.execute(
                "INSERT INTO cases(question,crop,region,draft,sources,priority,urgent_reasons,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (question, crop, region, draft, json.dumps(sources or []), priority,
                 json.dumps(urgent_reasons or []), status, t, t))
            cid = cur.lastrowid
            con.execute("UPDATE channel_inbox SET case_id=?,updated_at=? WHERE id=?", (cid, t, inbox["id"]))
            con.commit()
            return cid
        except BaseException:
            con.rollback()
            raise
    if case_id is None:
        if not question:
            raise ValueError("question required for a new case")
        cur = con.execute(
            "INSERT INTO cases(question,crop,region,draft,sources,priority,urgent_reasons,status,created_at,updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (question, crop, region, draft, json.dumps(sources or []), priority,
             json.dumps(urgent_reasons or []), status, t, t))
        con.commit()
        return cur.lastrowid
    blocked_status = None
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None:
            raise ValueError(f"case {case_id} not found")
        if row["status"] not in AGENT_STATUSES:
            blocked_status = row["status"]
            raise GateError(f"case {case_id} is '{row['status']}' and can no longer be changed by the agent")
        if require_draft and row["status"] != "draft":
            raise GateError("Case is not waiting for farmer information")
        if expected_revision is not None and expected_revision != row["revision"]:
            raise GateError("stale_revision: reload the case")
        cur = con.execute(
            "UPDATE cases SET crop=?, region=?, draft=COALESCE(?,draft), farmer_draft=COALESCE(?,farmer_draft), sources=?, priority=?,"
            " urgent_reasons=?, status=?, updated_at=?, revision=revision+1 WHERE id=? AND revision=?"
            + (" AND status='draft'" if require_draft else ""),
            (crop or row["crop"], region or row["region"], draft, farmer_draft,
             json.dumps(sources if sources is not None else json.loads(row["sources"])), priority,
             json.dumps(urgent_reasons or []), status, t, case_id, row["revision"]))
        if cur.rowcount != 1:
            raise GateError("stale_revision: case changed during agent update")
        con.commit()
    except BaseException:
        con.rollback()
        if blocked_status is not None:
            log(con, "agent", "create_or_update_case", {"case_id": case_id},
                f"BLOCKED: case already '{blocked_status}' (officer-owned)", ok=False, case_id=case_id)
        raise
    return case_id


def continue_clarification(con, case_id: int, *, expected_revision: int, clarification: str, replies: list[str],
                           crop: str = "", region: str = "") -> dict:
    """Replace the stored clarification on a draft. One revision wins; the question text stays the farmer's."""
    payload = json.dumps({"clarification": clarification, "text": "", "replies": replies}, ensure_ascii=False)
    try:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if row is None or row["status"] != "draft" or not _open_clarification(row):
            raise GateError("Case is not waiting for farmer information")
        if row["revision"] != expected_revision:
            raise GateError("stale_revision: reload the case")
        cur = con.execute(
            "UPDATE cases SET crop=?, region=?, farmer_draft=?, updated_at=?, revision=revision+1 "
            "WHERE id=? AND revision=? AND status='draft'",
            (crop or row["crop"], region or row["region"], payload, now(), case_id, expected_revision))
        if cur.rowcount != 1:
            raise GateError("stale_revision: reload the case")
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return dict(get_case(con, case_id))


def _open_clarification(row) -> dict | None:
    """A draft waiting on the farmer. Empty text means this is not an advisory proposal."""
    try:
        data = json.loads(row["farmer_draft"] or "null")
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("text"):
        return None
    clar = data.get("clarification")
    replies = data.get("replies")
    if not isinstance(clar, str) or not clar.strip() or not isinstance(replies, list):
        return None
    if not all(isinstance(item, str) for item in replies):
        return None
    return data


def officer_decide(con, case_id: int, *, officer: str, decision: str, edited_text=None,
                   note=None, farmer_text=None, expected_revision=None, acknowledgement=None, approved_voice_script=None) -> dict:
    """Enforced local workflow boundary; remote callers authenticate officer first."""
    from agrireach.approval import decide
    try:
        return decide(con, case_id, officer=officer, decision=decision, edited_text=edited_text,
                      note=note, farmer_text=farmer_text, expected_revision=expected_revision,
                      acknowledgement=acknowledgement, approved_voice_script=approved_voice_script)
    except SafetyError:
        raise  # The assessment and rejected submission are already durable.
    except GateError:
        from agrireach.approval import audit
        if get_case(con, case_id):
            with con:
                audit(con, case_id, officer, "approval_conflict", expected_revision=expected_revision)
        raise


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def reopen_case(con, case_id: int, *, officer: str, expected_revision: int, information: str) -> dict:
    """Return a clarified or invalidated unsent approval to review, keeping evidence.

    Trusted local callers supply the officer; remote callers must authenticate it.
    Raises GateError on stale state. It never releases or approves advice.
    """
    if not officer.strip() or not information.strip():
        raise ValueError("Officer and additional information are required")
    with con:
        con.execute("BEGIN IMMEDIATE")
        active = con.execute("SELECT 1 FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? AND j.state IN ('sending','unknown','accepted')", (case_id,)).fetchone()
        if active:
            raise GateError("Active or unresolved delivery must be reconciled before reopening")
        changed = con.execute("UPDATE cases SET status='pending_review', revision=revision+1, updated_at=? "
                              "WHERE id=? AND revision=? AND status IN ('needs_info','approved','not_delivered')",
                              (now(), case_id, expected_revision))
        if changed.rowcount != 1:
            raise GateError("stale_revision: reload the needs_info case")
        con.execute("INSERT INTO advisory_submissions(case_id,revision,officer,decision,note,created_at) "
                    "VALUES (?,?,?,'reopen',?,?)", (case_id, expected_revision, officer, information, now()))
        from agrireach.approval import audit
        audit(con, case_id, officer, "case_reopened", revision=expected_revision+1)
    return dict(get_case(con, case_id))


def issue_farmer_case_token(con, case_id: int) -> str:
    """Issue one unguessable capability for a web case. Only its digest is stored."""
    token = secrets.token_urlsafe(32)
    con.execute("INSERT INTO farmer_case_access(case_id,token_sha256,created_at) VALUES (?,?,?)",
                (case_id, _token_hash(token), now()))
    con.commit()
    return token


def farmer_case_token_valid(con, case_id: int, token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    return con.execute("SELECT 1 FROM farmer_case_access WHERE case_id=? AND token_sha256=?",
                       (case_id, _token_hash(token))).fetchone() is not None


def add_officer(con, name: str) -> str:
    """Register a named officer (or replace their sign-in) and return a new sign-in token. Only its SHA-256 is stored,
    so the token is shown once (scripts/add_officer.py) and cannot be read back from the database."""
    if not name or not name.strip():
        raise ValueError("officer name required")
    token = secrets.token_urlsafe(24)
    con.execute("INSERT INTO officers(name, token_sha256, created_at) VALUES (?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET token_sha256=excluded.token_sha256, created_at=excluded.created_at",
                (name.strip(), _token_hash(token), now()))
    con.commit()
    return token


def officer_for_token(con, token: str | None) -> str | None:
    if not token:
        return None
    r = con.execute("SELECT name FROM officers WHERE token_sha256=?", (_token_hash(token),)).fetchone()
    return r["name"] if r else None


def release_to_farmer(con, case_id: int, actor: str = "system") -> dict:
    """Validate the exact approval before idempotent publication or channel release."""
    from agrireach.approval import release
    from agrireach.delivery import expire_claims
    expire_claims(con, case_id)
    try:
        return release(con, case_id, actor)
    except GateError as exc:
        if get_case(con, case_id):
            from agrireach.approval import audit
            with con:
                audit(con, case_id, actor, "release_blocked", rule_ids=[f["rule_id"] for f in getattr(exc, "assessment", {}).get("findings", [])])
                log(con, actor, "release_to_farmer", {}, "BLOCKED: approval validation failed", ok=False, case_id=case_id, commit=False)
        raise


def mark_not_delivered(con, case_id: int, reason: str, actor: str = "system") -> bool:
    """released -> not_delivered when the channel could not send the approved answer. The case goes back to the
    officer queue; the farmer view stops showing it as answered."""
    cur = con.execute("UPDATE cases SET status='not_delivered', updated_at=? WHERE id=? AND status='released'",
                      (now(), case_id))
    con.commit()
    if cur.rowcount == 1:
        log(con, actor, "mark_not_delivered", {}, f"not_delivered: {reason}", ok=False, case_id=case_id)
    return cur.rowcount == 1


def mark_undeliverable(con, case_id: int, reason: str, actor: str = "system") -> bool:
    """released -> undeliverable (terminal): the approved answer can never be sent, because the farmer opted out or
    the number was removed by the retention purge. The officer's decision and text stay on the record."""
    cur = con.execute("UPDATE cases SET status='undeliverable', updated_at=? WHERE id=? AND status='released'",
                      (now(), case_id))
    con.commit()
    if cur.rowcount == 1:
        log(con, actor, "mark_undeliverable", {}, f"undeliverable: {reason}", ok=False, case_id=case_id)
    return cur.rowcount == 1


def delivery_problem(con, case_id: int) -> str | None:
    r = con.execute("SELECT detail FROM channel_deliveries WHERE case_id=? AND kind='answer' AND ok=0 "
                    "ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    return r["detail"] if r else None


def get_case(con, case_id: int):
    return con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()


def list_cases(con, status: str | tuple | None = None) -> list[dict]:
    q, a = "SELECT * FROM cases", ()
    if status:
        a = (status,) if isinstance(status, str) else tuple(status)
        q += f" WHERE status IN ({','.join('?' * len(a))})"
    q += " ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, id"
    return [dict(r) for r in con.execute(q, a)]


def case_log(con, case_id: int) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM tool_log WHERE case_id=? ORDER BY id", (case_id,))]


# --- Channel contacts (voice notes, WhatsApp). sender_id is personal data: it is stored only so the approved answer
# can be sent back, and is never written to tool_log or shown unmasked (see channels.base.mask_sender).

def require_inbound_claim(con, claim: dict):
    row = con.execute("SELECT * FROM channel_inbox WHERE channel=? AND message_id=? AND lease_id=? AND state='processing'",
                      (claim["channel"], claim["message_id"], claim["lease_id"])).fetchone()
    if row is None:
        raise GateError("Inbound claim revoked or interrupted; no further processing")
    return row


def save_contact(con, case_id: int, *, channel: str, sender_id: str, audio_path: str | None = None,
                 transcript: str | None = None, stt: dict | None = None, inbound_claim: dict | None = None):
    with con:
        con.execute("BEGIN IMMEDIATE")
        if inbound_claim:
            require_inbound_claim(con, inbound_claim)
        con.execute("INSERT OR REPLACE INTO channel_contacts(case_id,channel,sender_id,audio_path,transcript,stt,created_at)"
                    " VALUES (?,?,?,?,?,?,?)", (case_id, channel, sender_id, audio_path, transcript,
                                                 json.dumps(stt or {}), now()))
        con.execute("UPDATE cases SET revision=revision+1 WHERE id=?", (case_id,))


def queue_with_contact(con, case_id: int, *, channel: str, sender_id: str, audio_path: str | None = None,
                       transcript: str | None = None, stt: dict | None = None, inbound_claim: dict | None = None):
    """Save a channel case's contact and move the case from 'draft' to the officer queue in one transaction: a case
    is never in the queue without the contact its approved answer goes back to (live run 5 lost one that way)."""
    with con:  # commits both, or rolls both back
        con.execute("BEGIN IMMEDIATE")
        if inbound_claim:
            require_inbound_claim(con, inbound_claim)
        con.execute("INSERT OR REPLACE INTO channel_contacts(case_id,channel,sender_id,audio_path,transcript,stt,"
                    "created_at) VALUES (?,?,?,?,?,?,?)", (case_id, channel, sender_id, audio_path, transcript,
                                                           json.dumps(stt or {}), now()))
        cur = con.execute("UPDATE cases SET status='pending_review', revision=revision+1, updated_at=? WHERE id=? AND status='draft'",
                          (now(), case_id))
        if cur.rowcount != 1:
            raise GateError(f"case {case_id} is not a draft; not queued")
    log(con, f"channel:{channel}", "queue_case", {"case_id": case_id}, "contact saved; case queued for review",
        case_id=case_id)


def get_contact(con, case_id: int):
    return con.execute("SELECT * FROM channel_contacts WHERE case_id=?", (case_id,)).fetchone()


def record_delivery(con, case_id: int, channel: str, kind: str, ok: bool, detail: str):
    """kind: 'ack' or 'clarification' (fixed system messages) or 'answer' (officer-approved text)."""
    con.execute("INSERT INTO channel_deliveries(case_id,channel,kind,ok,detail,ts) VALUES (?,?,?,?,?,?)",
                (case_id, channel, kind, int(ok), detail[:500], now()))
    con.commit()


def answer_delivered(con, case_id: int) -> bool:
    return con.execute("SELECT 1 FROM channel_deliveries WHERE case_id=? AND kind='answer' AND ok=1",
                       (case_id,)).fetchone() is not None


def _inbox_connection(con):
    """Use a separate SQLite connection so inbox commits never commit caller writes."""
    row = con.execute("PRAGMA database_list").fetchone()
    path = row[2]
    if not path:
        raise ValueError("Durable inbox requires a file-backed SQLite database")
    other = sqlite3.connect(path, timeout=10)
    other.row_factory = sqlite3.Row
    other.execute("PRAGMA foreign_keys=ON")
    return other


from contextlib import contextmanager


@contextmanager
def _inbox_transaction(inbox):
    try:
        yield
        inbox.commit()
    except BaseException:
        inbox.rollback()
        raise


def enqueue_inbound(con, channel: str, message_id: str, payload: dict, *, sender_id: str | None = None) -> bool:
    """Commit an inbound event without committing unrelated caller transactions."""
    if not channel or not message_id:
        raise ValueError("channel and message_id are required")
    with closing(_inbox_connection(con)) as inbox, _inbox_transaction(inbox):
        cur = inbox.execute(
            "INSERT INTO channel_inbox(channel,message_id,payload,state,created_at,updated_at,sender_id) "
            "VALUES (?,?,?,'pending',?,?,?) ON CONFLICT(channel,message_id) DO NOTHING",
            (channel, message_id, json.dumps(payload, ensure_ascii=False), now(), now(), sender_id))
        return cur.rowcount == 1


def claim_inbound(con, channel: str, message_id: str) -> tuple[str, dict] | None:
    """Generate a private claim ID; a crash leaves an item for reconciliation."""
    claim_id = secrets.token_urlsafe(32)
    with closing(_inbox_connection(con)) as inbox, _inbox_transaction(inbox):
        inbox.execute("BEGIN IMMEDIATE")
        row = inbox.execute(
            "SELECT id,payload FROM channel_inbox WHERE channel=? AND message_id=? AND state='pending'",
            (channel, message_id)).fetchone()
        if row is None:
            return None
        inbox.execute(
            "UPDATE channel_inbox SET state='processing',attempt_count=attempt_count+1,"
            "lease_id=?,updated_at=? WHERE id=? AND state='pending'",
            (claim_id, now(), row["id"]))
        return claim_id, json.loads(row["payload"])


def finish_inbound(con, channel: str, message_id: str, claim_id: str,
                   state: str, case_id: int | None = None, *, reason: str | None = None,
                   event_kind: str = "advisory") -> bool:
    """Only the current claim holder may finish; case association is validated."""
    if state not in ("completed", "failed", "uncertain"):
        raise ValueError("invalid inbound outcome")
    if state == "completed" and case_id is None and event_kind not in ("consent", "consented", "stop", "location", "awaiting_consent", "awaiting_location"):
        raise ValueError("completed advisory inbound processing requires a case ID")
    if state == "completed" and case_id is None and not (reason or "").strip():
        raise ValueError("non-advisory completion requires a reason")
    if state in ("failed", "uncertain") and not (reason or "").strip():
        raise ValueError("failed or uncertain processing requires an outcome reason")
    with closing(_inbox_connection(con)) as inbox, _inbox_transaction(inbox):
        cur = inbox.execute(
            "UPDATE channel_inbox SET state=?,case_id=COALESCE(?,case_id),outcome_reason=?,lease_id=NULL,updated_at=? "
            "WHERE channel=? AND message_id=? AND lease_id=? AND state='processing' "
            "AND (case_id IS NULL OR ? IS NULL OR case_id=?)",
            (state, case_id, reason, now(), channel, message_id, claim_id, case_id, case_id))
        return cur.rowcount == 1


def reconcile_interrupted_inbound(con, *, older_than: str) -> int:
    """Conservatively mark abandoned claims uncertain; never resend automatically."""
    with closing(_inbox_connection(con)) as inbox, _inbox_transaction(inbox):
        cur = inbox.execute(
            "UPDATE channel_inbox SET state='uncertain',lease_id=NULL,updated_at=?, "
            "outcome_reason='interrupted claim; reconciliation required' "
            "WHERE state='processing' AND updated_at<?", (now(), older_than))
        return cur.rowcount


def purge_inbound(con, *, older_than: str, channel: str | None = None,
                  message_ids: list[str] | None = None) -> int:
    """Remove sensitive inbox payloads only for terminal records, preserving pending work."""
    where = "state IN ('completed','failed','uncertain') AND updated_at<?"
    args = [older_than]
    if channel is not None:
        where += " AND channel=?"
        args.append(channel)
    if message_ids is not None:
        if not message_ids:
            return 0
        where += " AND message_id IN (" + ",".join("?" for _ in message_ids) + ")"
        args.extend(message_ids)
    with closing(_inbox_connection(con)) as inbox, _inbox_transaction(inbox):
        cur = inbox.execute("DELETE FROM channel_inbox WHERE " + where, args)
        return cur.rowcount


def first_time_seen(con, channel: str, message_id: str) -> bool:
    """True the first time a (channel, message id) arrives; webhook retries can deliver the same message twice."""
    try:
        con.execute("INSERT INTO channel_inbound_seen(channel,message_id,ts) VALUES (?,?,?)", (channel, message_id, now()))
        con.commit()
        return True
    except sqlite3.IntegrityError:
        con.rollback()  # the failed INSERT opened a transaction; release its write lock
        return False


# --- Consent, held messages, and retention for channel senders ------------------------------------------------------

def get_consent(con, channel: str, sender_id: str) -> str | None:
    r = con.execute("SELECT status FROM channel_consent WHERE channel=? AND sender_id=?", (channel, sender_id)).fetchone()
    return r["status"] if r else None


def set_consent(con, channel: str, sender_id: str, status: str):
    """status: 'asked' (prompt sent, waiting) or 'yes'."""
    con.execute("INSERT INTO channel_consent(channel,sender_id,status,asked_at,decided_at) VALUES (?,?,?,?,?) "
                "ON CONFLICT(channel,sender_id) DO UPDATE SET status=excluded.status, decided_at=excluded.decided_at",
                (channel, sender_id, status, now(), None if status == "asked" else now()))
    con.commit()


def hold(con, channel: str, sender_id: str, kind: str, payload: dict) -> int:
    """Keep an inbound message until the farmer answers a question (kind: 'consent' or 'location')."""
    cur = con.execute("INSERT INTO channel_pending(channel,sender_id,kind,payload,created_at) VALUES (?,?,?,?,?)",
                      (channel, sender_id, kind, json.dumps(payload), now()))
    con.commit()
    return cur.lastrowid


def take_held(con, channel: str, sender_id: str, kind: str) -> list[dict]:
    rows = con.execute("SELECT id, payload FROM channel_pending WHERE channel=? AND sender_id=? AND kind=? ORDER BY id",
                       (channel, sender_id, kind)).fetchall()
    con.execute("DELETE FROM channel_pending WHERE channel=? AND sender_id=? AND kind=?", (channel, sender_id, kind))
    con.commit()
    return [json.loads(r["payload"]) for r in rows]


def has_held(con, channel: str, sender_id: str, kind: str) -> bool:
    return con.execute("SELECT 1 FROM channel_pending WHERE channel=? AND sender_id=? AND kind=?",
                       (channel, sender_id, kind)).fetchone() is not None


def _remove_audio(paths):
    for p in paths:
        if p:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


PURGED = "[removed]"       # number removed by the retention purge
OPTED_OUT = "[opted out]"  # number removed because the farmer sent STOP
REMOVED = (PURGED, OPTED_OUT)


def forget_sender(con, channel: str, sender_id: str) -> dict:
    """The farmer said STOP: drop their number, held messages, voice notes and consent. Cases stay (anonymised) so
    the officer's record of the advice given is kept, but nothing can be sent to this sender any more."""
    held = con.execute("SELECT payload FROM channel_pending WHERE channel=? AND sender_id=?",
                       (channel, sender_id)).fetchall()
    contacts = con.execute("SELECT audio_path FROM channel_contacts WHERE channel=? AND sender_id=?",
                           (channel, sender_id)).fetchall()
    _remove_audio([json.loads(r["payload"]).get("audio_path") for r in held] + [r["audio_path"] for r in contacts])
    con.execute("UPDATE channel_contacts SET sender_id=?, audio_path=NULL WHERE channel=? AND sender_id=?",
                (OPTED_OUT, channel, sender_id))
    con.execute("DELETE FROM channel_pending WHERE channel=? AND sender_id=?", (channel, sender_id))
    con.execute("DELETE FROM channel_consent WHERE channel=? AND sender_id=?", (channel, sender_id))
    con.execute("DELETE FROM channel_inbox WHERE channel=? AND sender_id=?", (channel, sender_id))
    con.commit()
    return {"contacts": len(contacts), "held": len(held)}


def retention_days() -> int:
    return int(os.getenv("AGRIREACH_RETENTION_DAYS", "90"))


def purge_old(con, days: int | None = None, now_ts: str | None = None) -> dict:
    """Remove sender numbers, voice notes, held messages and consent records older than `days`
    (AGRIREACH_RETENTION_DAYS, default 90). Case text and the officer's decision are kept, anonymised."""
    days = retention_days() if days is None else days
    ref = datetime.fromisoformat(now_ts) if now_ts else datetime.now(timezone.utc)
    cutoff = (ref - timedelta(days=days)).isoformat(timespec="seconds")
    old = con.execute("SELECT audio_path FROM channel_contacts WHERE created_at <= ? AND sender_id NOT IN (?,?)",
                      (cutoff, *REMOVED)).fetchall()
    held = con.execute("SELECT payload FROM channel_pending WHERE created_at <= ?", (cutoff,)).fetchall()
    _remove_audio([r["audio_path"] for r in old] + [json.loads(r["payload"]).get("audio_path") for r in held])
    con.execute("UPDATE channel_contacts SET sender_id=?, audio_path=NULL WHERE created_at <= ? "
                "AND sender_id NOT IN (?,?)", (PURGED, cutoff, *REMOVED))
    con.execute("DELETE FROM channel_pending WHERE created_at <= ?", (cutoff,))
    n_consent = con.execute("DELETE FROM channel_consent WHERE COALESCE(decided_at, asked_at) <= ?", (cutoff,)).rowcount
    # Expired unprocessed events are discarded, never replayed after consent data expires.
    n_inbox = con.execute("DELETE FROM channel_inbox WHERE created_at <= ?", (cutoff,)).rowcount
    # Web SMS numbers follow the same retention window. Cases and acknowledgement jobs stay.
    n_farmer_sms = con.execute("DELETE FROM farmer_sms_contacts WHERE created_at <= ?", (cutoff,)).rowcount
    con.commit()
    return {"contacts": len(old), "held": len(held), "consent": n_consent, "inbox": n_inbox,
            "farmer_sms": n_farmer_sms, "cutoff": cutoff}
