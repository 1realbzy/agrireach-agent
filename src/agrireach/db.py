"""SQLite case store with an enforced officer approval gate.

Status lifecycle:
  draft -> pending_review -> approved -> released
                          -> rejected | needs_info
Agent-side writes may ONLY set 'draft' or 'pending_review'. Approval, rejection,
editing and release are officer-only functions, and release requires approval.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
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
    con = sqlite3.connect(p)
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
        CREATE TABLE IF NOT EXISTS tool_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
          case_id INTEGER, actor TEXT NOT NULL, tool TEXT NOT NULL,
          args TEXT, result_summary TEXT, ok INTEGER NOT NULL);
        """
    )
    return con


def log(con, actor: str, tool: str, args: dict, summary: str, ok: bool = True, case_id: int | None = None):
    con.execute(
        "INSERT INTO tool_log(ts,case_id,actor,tool,args,result_summary,ok) VALUES (?,?,?,?,?,?,?)",
        (now(), case_id, actor, tool, json.dumps(args, ensure_ascii=False)[:2000], summary[:2000], int(ok)),
    )
    con.commit()


def agent_upsert_case(con, *, status: str, question: str = "", case_id: int | None = None, crop=None, region=None,
                      draft=None, sources=None, priority="routine", urgent_reasons=None) -> int:
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
        "UPDATE cases SET draft=COALESCE(?,draft), sources=?, priority=?, urgent_reasons=?, status=?, updated_at=? WHERE id=?",
        (draft, json.dumps(sources if sources is not None else json.loads(row["sources"])), priority,
         json.dumps(urgent_reasons or []), status, t, case_id))
    con.commit()
    return case_id


def officer_decide(con, case_id: int, *, officer: str, decision: str, edited_text: str | None = None,
                   note: str | None = None) -> dict:
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
    t = now()
    con.execute("UPDATE cases SET status=?, final_text=?, officer=?, decided_at=?, officer_note=?, updated_at=? WHERE id=?",
                (status, final, officer.strip(), t, note, t, case_id))
    con.commit()
    log(con, f"officer:{officer.strip()}", "officer_decision", {"decision": decision}, status, case_id=case_id)
    return dict(get_case(con, case_id))


def release_to_farmer(con, case_id: int, actor: str = "system") -> dict:
    row = get_case(con, case_id)
    if row is None:
        raise ValueError(f"case {case_id} not found")
    if row["status"] != "approved" or not row["officer"]:
        log(con, actor, "release_to_farmer", {}, f"BLOCKED: status '{row['status']}', no officer approval",
            ok=False, case_id=case_id)
        raise GateError(f"case {case_id} has no officer approval (status '{row['status']}')")
    con.execute("UPDATE cases SET status='released', updated_at=? WHERE id=?", (now(), case_id))
    con.commit()
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
