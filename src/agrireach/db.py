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
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

AGENT_STATUSES = {"draft", "pending_review"}
OFFICER_DECISIONS = {"approve", "edit_approve", "reject", "request_info"}


class GateError(Exception):
    """Raised when an action would bypass the officer approval gate."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///agrireach.db")
    return url.removeprefix("sqlite:///")


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or db_path()
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=10)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS cases (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          question TEXT NOT NULL, crop TEXT, region TEXT,
          draft TEXT, final_text TEXT,
          sources TEXT DEFAULT '[]',
          priority TEXT DEFAULT 'routine', urgent_reasons TEXT DEFAULT '[]',
          status TEXT NOT NULL DEFAULT 'draft',
          officer TEXT, decided_at TEXT, officer_note TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS officers (
          name TEXT PRIMARY KEY, token_sha256 TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tool_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
          case_id INTEGER, actor TEXT NOT NULL, tool TEXT NOT NULL,
          args TEXT, result_summary TEXT, ok INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_contacts (
          case_id INTEGER PRIMARY KEY REFERENCES cases(id),
          channel TEXT NOT NULL, sender_id TEXT NOT NULL,
          audio_path TEXT, transcript TEXT, stt TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_deliveries (
          id INTEGER PRIMARY KEY AUTOINCREMENT, case_id INTEGER NOT NULL REFERENCES cases(id),
          channel TEXT NOT NULL, kind TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT, ts TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS channel_inbound_seen (
          channel TEXT NOT NULL, message_id TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY (channel, message_id));
        CREATE TABLE IF NOT EXISTS channel_consent (
          channel TEXT NOT NULL, sender_id TEXT NOT NULL, status TEXT NOT NULL, asked_at TEXT NOT NULL,
          decided_at TEXT, PRIMARY KEY (channel, sender_id));
        CREATE TABLE IF NOT EXISTS channel_pending (
          id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL, sender_id TEXT NOT NULL,
          kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        """
    )
    cols = {r[1] for r in con.execute("PRAGMA table_info(cases)")}
    for col in ("farmer_draft", "farmer_text"):  # added for the farmer-facing reply; older DBs gain them here
        if col not in cols:
            con.execute(f"ALTER TABLE cases ADD COLUMN {col} TEXT")
    con.commit()
    return con


def log(con, actor: str, tool: str, args: dict, summary: str, ok: bool = True, case_id: int | None = None):
    con.execute(
        "INSERT INTO tool_log(ts,case_id,actor,tool,args,result_summary,ok) VALUES (?,?,?,?,?,?,?)",
        (now(), case_id, actor, tool, json.dumps(args, ensure_ascii=False)[:2000], summary[:2000], int(ok)),
    )
    con.commit()


def agent_upsert_case(con, *, status: str, question: str = "", case_id: int | None = None, crop=None, region=None,
                      draft=None, sources=None, priority="routine", urgent_reasons=None, farmer_draft=None) -> int:
    """farmer_draft: AgriReach's PROPOSED farmer-facing text (JSON, see farmer_reply). Only the officer's approved
    farmer_text is ever delivered."""
    if status not in AGENT_STATUSES:
        log(con, "agent", "create_or_update_case", {"status": status, "case_id": case_id},
            f"BLOCKED: agent may not set status '{status}'", ok=False, case_id=case_id)
        raise GateError(f"agent may only set {sorted(AGENT_STATUSES)}, not '{status}'")
    if priority not in {"routine", "urgent"}:
        raise ValueError("priority must be routine or urgent")
    t = now()
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
    row = get_case(con, case_id)
    if row is None:
        raise ValueError(f"case {case_id} not found")
    if row["status"] not in AGENT_STATUSES:
        log(con, "agent", "create_or_update_case", {"case_id": case_id},
            f"BLOCKED: case already '{row['status']}' (officer-owned)", ok=False, case_id=case_id)
        raise GateError(f"case {case_id} is '{row['status']}' and can no longer be changed by the agent")
    con.execute(
        "UPDATE cases SET draft=COALESCE(?,draft), farmer_draft=COALESCE(?,farmer_draft), sources=?, priority=?,"
        " urgent_reasons=?, status=?, updated_at=? WHERE id=?",
        (draft, farmer_draft, json.dumps(sources if sources is not None else json.loads(row["sources"])), priority,
         json.dumps(urgent_reasons or []), status, t, case_id))
    con.commit()
    return case_id


def officer_decide(con, case_id: int, *, officer: str, decision: str, edited_text: str | None = None,
                   note: str | None = None, farmer_text: str | None = None) -> dict:
    """Approval covers exactly what is delivered: farmer_text is the farmer-facing text the officer approved. If it is
    not given, the approved officer text itself is what the farmer gets (the API requires it explicitly)."""
    if not officer or not officer.strip():
        raise GateError("a named officer is required")
    if decision not in OFFICER_DECISIONS:
        raise ValueError(f"decision must be one of {sorted(OFFICER_DECISIONS)}")
    row = get_case(con, case_id)
    if row is None:
        raise ValueError(f"case {case_id} not found")
    if row["status"] != "pending_review":
        raise GateError(f"case {case_id} is '{row['status']}', not pending_review")
    status = {"approve": "approved", "edit_approve": "approved", "reject": "rejected",
              "request_info": "needs_info"}[decision]
    final = None
    if decision == "approve":
        final = row["draft"]
    elif decision == "edit_approve":
        if not edited_text:
            raise ValueError("edited_text required for edit_approve")
        final = edited_text
    farmer = None
    if final is not None:
        farmer = farmer_text.strip() if farmer_text and farmer_text.strip() else final
    t = now()
    # Write only if the case is STILL pending_review: the status check above and this write are not atomic, so two
    # officers deciding at once would otherwise both "win" (last write on the record, first text on the phone).
    cur = con.execute("UPDATE cases SET status=?, final_text=?, farmer_text=?, officer=?, decided_at=?, officer_note=?,"
                      " updated_at=? WHERE id=? AND status='pending_review'",
                      (status, final, farmer, officer.strip(), t, note, t, case_id))
    con.commit()
    if cur.rowcount != 1:
        log(con, f"officer:{officer.strip()}", "officer_decision", {"decision": decision},
            "BLOCKED: another decision was recorded first", ok=False, case_id=case_id)
        raise GateError(f"case {case_id} was decided by someone else first; reload it")
    log(con, f"officer:{officer.strip()}", "officer_decision",
        {"decision": decision, "farmer_text": None if farmer is None else
         ("officer-approved farmer text" if farmer != final else "same as officer text"),
         "farmer_text_chars": len(farmer or "")}, status, case_id=case_id)
    return dict(get_case(con, case_id))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
    row = get_case(con, case_id)
    if row is None:
        raise ValueError(f"case {case_id} not found")
    if row["status"] != "approved" or not row["officer"]:
        log(con, actor, "release_to_farmer", {}, f"BLOCKED: status '{row['status']}', no officer approval",
            ok=False, case_id=case_id)
        raise GateError(f"case {case_id} has no officer approval (status '{row['status']}')")
    cur = con.execute("UPDATE cases SET status='released', updated_at=? WHERE id=? AND status='approved'",
                      (now(), case_id))
    con.commit()
    if cur.rowcount != 1:
        raise GateError(f"case {case_id} is no longer 'approved'")
    log(con, actor, "release_to_farmer", {}, f"released; approved by {row['officer']}", case_id=case_id)
    return dict(get_case(con, case_id))


def get_case(con, case_id: int):
    return con.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()


def list_cases(con, status: str | None = None) -> list[dict]:
    q, a = "SELECT * FROM cases", ()
    if status:
        q, a = q + " WHERE status=?", (status,)
    q += " ORDER BY CASE priority WHEN 'urgent' THEN 0 ELSE 1 END, id"
    return [dict(r) for r in con.execute(q, a)]


def case_log(con, case_id: int) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM tool_log WHERE case_id=? ORDER BY id", (case_id,))]


# --- Channel contacts (voice notes, WhatsApp). sender_id is personal data: it is stored only so the approved answer
# can be sent back, and is never written to tool_log or shown unmasked (see channels.base.mask_sender).

def save_contact(con, case_id: int, *, channel: str, sender_id: str, audio_path: str | None = None,
                 transcript: str | None = None, stt: dict | None = None):
    con.execute("INSERT OR REPLACE INTO channel_contacts(case_id,channel,sender_id,audio_path,transcript,stt,created_at)"
                " VALUES (?,?,?,?,?,?,?)", (case_id, channel, sender_id, audio_path, transcript,
                                             json.dumps(stt or {}), now()))
    con.commit()


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


PURGED = "[removed]"


def forget_sender(con, channel: str, sender_id: str) -> dict:
    """The farmer said STOP: drop their number, held messages, voice notes and consent. Cases stay (anonymised) so
    the officer's record of the advice given is kept, but nothing can be sent to this sender any more."""
    held = con.execute("SELECT payload FROM channel_pending WHERE channel=? AND sender_id=?",
                       (channel, sender_id)).fetchall()
    contacts = con.execute("SELECT audio_path FROM channel_contacts WHERE channel=? AND sender_id=?",
                           (channel, sender_id)).fetchall()
    _remove_audio([json.loads(r["payload"]).get("audio_path") for r in held] + [r["audio_path"] for r in contacts])
    con.execute("UPDATE channel_contacts SET sender_id=?, audio_path=NULL WHERE channel=? AND sender_id=?",
                (PURGED, channel, sender_id))
    con.execute("DELETE FROM channel_pending WHERE channel=? AND sender_id=?", (channel, sender_id))
    con.execute("DELETE FROM channel_consent WHERE channel=? AND sender_id=?", (channel, sender_id))
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
    old = con.execute("SELECT audio_path FROM channel_contacts WHERE created_at <= ? AND sender_id != ?",
                      (cutoff, PURGED)).fetchall()
    held = con.execute("SELECT payload FROM channel_pending WHERE created_at <= ?", (cutoff,)).fetchall()
    _remove_audio([r["audio_path"] for r in old] + [json.loads(r["payload"]).get("audio_path") for r in held])
    con.execute("UPDATE channel_contacts SET sender_id=?, audio_path=NULL WHERE created_at <= ? AND sender_id != ?",
                (PURGED, cutoff, PURGED))
    con.execute("DELETE FROM channel_pending WHERE created_at <= ?", (cutoff,))
    n_consent = con.execute("DELETE FROM channel_consent WHERE COALESCE(decided_at, asked_at) <= ?", (cutoff,)).rowcount
    con.commit()
    return {"contacts": len(old), "held": len(held), "consent": n_consent, "cutoff": cutoff}
