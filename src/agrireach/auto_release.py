"""Conservative routine auto-release. Off by default; fail closed.

A pending_review case is released to the farmer automatically only when the
feature is on AND every rule below holds. Anything else stays in the officer
queue, exactly as today.

Setting: AGRIREACH_AUTO_RELEASE=1 (also true/yes/on). Unset or any other value
is off. The default is off so existing officer-only tests stay unchanged.

Eligibility (all must hold):
1. The setting is on.
2. The case is pending_review, priority is routine, and there are no urgent reasons.
3. Proposed farmer text exists, is English, and was drafted by a real model
   (farmer_draft.mode starts with "llm:", not a stub).
4. The question is on a conservative allow-list of routine agronomy topics:
   planting timing, harvest timing, or crop spacing. The question and the
   farmer text must not mention excluded topics: pesticides or chemicals,
   doses or rates, spraying, fertiliser application, animal or human health,
   money or loans, or burning.
5. farmer_draft.problems is empty (a "sources differ" note is a conflict).
6. The existing approval assess_candidate() returns outcome "pass" with no
   findings (no safety flags, no source conflict, no figure mismatch).
7. The real claim-check judge ran and supported every advice line
   (judge_status == "supported", every verdict is "supported"). If the judge
   does not run, errors, or times out, the case goes to the officer.
8. Text-to-speech is off (auto-release cannot preview a spoken script).
9. There are no informational assessment warnings (for example a dropped zone
   caveat).

Auto-release goes through the same approval snapshot, fingerprint and release
path as an officer approval, with actor "auto-release". It is recorded in
audit_events, advisory_submissions, safety_assessments and approvals. The
officer can inspect the audit and, for a released case with no accepted
delivery, retract it back to the review queue.
"""
from __future__ import annotations

import json
import os
import re

from agrireach import approval, db, knowledge, safety_gate

SETTING = "AGRIREACH_AUTO_RELEASE"
ACTOR = "auto-release"

# Routine agronomy only: when/how to plant or harvest, or spacing. Conservative.
ALLOW = re.compile(
    r"\b(?:"
    r"when (?:should|do|can|could|to|is(?: it)?(?: the)?(?: best| right)?|would) .{0,60}\b(?:harvest|plant|sow|planted|sown)\w*"
    r"|(?:harvest|plant|sow)\w* .{0,60}\b(?:when|time|timing|window|season|month)"
    r"|what(?:'s| is) the (?:best |right |recommended )?(?:time|window|season|month) .{0,60}\b(?:harvest|plant|sow)"
    r"|(?:how (?:far|wide) (?:apart|should)|spac(?:e|ing)|plant(?:ing)? (?:distance|density|apart)|"
    r"distance between|row (?:width|spacing|distance))"
    r")\b",
    re.I | re.S,
)

# Anything safety-sensitive, medical, financial, or chemical is out of scope.
EXCLUDE = re.compile(
    r"\b(?:"
    r"pesticide|insecticide|herbicide|fungicide|chemical|spray(?:s|ed|ing)?|"
    r"mancozeb|karate|glyphosate|paraquat|atrazine|actellic|phostoxin|gramoxone|"
    r"dose|dosage|knapsack|sachet|capful|per (?:acre|hectare|litre|liter)|"
    r"poison|aflatoxin|mouldy|moldy|sick|illness|disease|infect|fever|pregnant|"
    r"child(?:ren)?|baby|babies|human health|livestock|cattle|goat|sheep|poultry|animal|"
    r"loan|credit|money|price|subsid(?:y|ies)|cost|payment|bank|insurance|"
    r"fertili[sz]er|top-?dress|urea|npk|"
    r"burn(?:ing|ed)?|set(?:ting)? fire|"
    r"kill(?:s|ing)? (?:the )?(?:pest|worm|weed|insect)"
    r")\b",
    re.I,
)


def enabled() -> bool:
    """True only when the setting is an explicit on-value. Default is off."""
    return os.getenv(SETTING, "").strip().lower() in {"1", "true", "yes", "on"}


def _proposal(row) -> dict:
    return json.loads(row["farmer_draft"] or "null") or {}


def _topic_reason(question: str, text: str) -> str | None:
    """Return why the topic is not eligible, or None if it is a routine allow-listed topic."""
    blob = f"{question}\n{text}"
    if EXCLUDE.search(blob):
        return "topic_excluded"
    if not ALLOW.search(question or ""):
        return "topic_not_allowlisted"
    return None


def eligibility(con, case_id: int) -> dict:
    """Explain whether a case may be auto-released. May call the judge (model I/O).

    Never mutates the case. Fail closed: any gap or error is a rejection with a reason.
    """
    row = db.get_case(con, case_id)
    if row is None:
        return {"eligible": False, "reason": "case_not_found"}
    if row["status"] != "pending_review":
        return {"eligible": False, "reason": "not_pending_review", "status": row["status"]}
    if (row["priority"] or "routine") != "routine" or json.loads(row["urgent_reasons"] or "[]"):
        return {"eligible": False, "reason": "not_routine"}
    proposal = _proposal(row)
    text = (proposal.get("text") or "").strip()
    if not text:
        return {"eligible": False, "reason": "no_farmer_text"}
    if (proposal.get("language") or "en") != "en":
        return {"eligible": False, "reason": "language_not_english"}
    mode = str(proposal.get("mode") or "")
    if not mode.startswith("llm:") or "stub" in mode:
        return {"eligible": False, "reason": "not_model_draft", "mode": mode or "missing"}
    if proposal.get("needs_officer_text"):
        return {"eligible": False, "reason": "needs_officer_text"}
    if proposal.get("problems"):
        if any(str(p).startswith("sources differ") for p in proposal["problems"]):
            return {"eligible": False, "reason": "source_conflict"}
        return {"eligible": False, "reason": "proposal_problems"}
    if topic := _topic_reason(row["question"] or "", text):
        return {"eligible": False, "reason": topic}
    from agrireach.channels import tts
    if tts.enabled():
        return {"eligible": False, "reason": "voice_preview_required"}
    try:
        ctx = approval.context(con, row)
        assessment = approval.assess_candidate(text, ctx)
    except Exception:
        return {"eligible": False, "reason": "assessment_error"}
    findings = assessment.get("findings") or []
    # Judge failure always wins: a crash, timeout or missing verdict is fail-closed, even if
    # the assessment also carries a JUDGE_AVAILABILITY finding.
    if assessment.get("outcome") == "assessment_unavailable" or assessment.get("judge_status") == "failed":
        return {"eligible": False, "reason": "judge_unavailable", "outcome": assessment.get("outcome"),
                "judge_status": assessment.get("judge_status"), "assessment": assessment}
    if assessment.get("outcome") != "pass":
        if any(f.get("rule_id") == "SOURCE_CONFLICT" for f in findings):
            reason = "source_conflict"
        elif findings:
            reason = "safety_flags"
        else:
            reason = "assessment_not_pass"
        return {"eligible": False, "reason": reason, "outcome": assessment.get("outcome"),
                "judge_status": assessment.get("judge_status"), "assessment": assessment}
    if assessment.get("findings"):
        return {"eligible": False, "reason": "safety_flags", "assessment": assessment}
    if assessment.get("informational"):
        return {"eligible": False, "reason": "informational_warnings", "assessment": assessment}
    # The judge must have actually run and supported every line. "not_required" (verbatim
    # quotes or no judge) is fail-closed: we do not auto-release without a real verdict.
    if assessment.get("judge_status") != "supported":
        return {"eligible": False, "reason": "judge_did_not_run", "judge_status": assessment.get("judge_status"),
                "assessment": assessment}
    judge = assessment.get("judge") or {}
    verdicts = judge.get("verdicts") or []
    if judge.get("error") or not verdicts:
        return {"eligible": False, "reason": "judge_unavailable", "assessment": assessment}
    if any(v.get("verdict") != "supported" for v in verdicts):
        return {"eligible": False, "reason": "judge_not_supported", "assessment": assessment}
    sources = [knowledge.reference(i) or {"id": i} for i in json.loads(row["sources"] or "[]")]
    return {"eligible": True, "reason": "routine_allowlisted_judge_passed", "farmer_text": text,
            "assessment": assessment, "context": ctx, "row": row, "sources": sources, "verdicts": verdicts}


def _record_deferral(con, case_id: int, report: dict) -> None:
    """Audit why auto-release was not applied. Never stores exception text or secrets."""
    try:
        with con:
            approval.audit(con, case_id, ACTOR, "auto_release_deferred",
                           reason=report.get("reason"), outcome=report.get("outcome"),
                           judge_status=report.get("judge_status"))
    except Exception:
        pass


def _commit_release(con, case_id: int, report: dict) -> dict:
    """Persist an assessed approval as auto-release and publish it, using the same snapshots as decide()."""
    row = report["row"]
    ctx = report["context"]
    assessment = report["assessment"]
    farmer_text = report["farmer_text"]
    expected_revision = row["revision"]
    warning_identity = {
        "outcome": assessment["outcome"],
        "judge_status": assessment.get("judge_status"),
        "findings": sorted(
            (f["rule_id"], f.get("sentence", ""), tuple(sorted(f.get("evidence", []))))
            for f in assessment.get("findings", [])),
    }
    binding = safety_gate.fingerprint({"context": ctx, "farmer_text": farmer_text, "officer_text": row["draft"],
                                       "decision": "approve", "officer": ACTOR, "credential": None, "voice_script": None,
                                       "assessment": warning_identity})
    note = ("Auto-released: allow-listed routine agronomy; the claim-check judge supported every "
            "advice line; no safety flags or source conflict.")
    try:
        con.execute("BEGIN IMMEDIATE")
        fresh = db.get_case(con, case_id)
        if fresh["status"] != "pending_review" or approval.context(con, fresh) != ctx:
            raise db.GateError("stale_revision: assessment context changed")
        submission = con.execute(
            "INSERT INTO advisory_submissions(case_id,revision,officer,farmer_text,officer_text,decision,note,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (case_id, expected_revision, ACTOR, farmer_text, row["draft"], "approve", note, db.now())).lastrowid
        assessment_id = con.execute(
            "INSERT INTO safety_assessments(case_id,snapshot,assessment,created_at) VALUES (?,?,?,?)",
            (case_id, json.dumps(ctx), json.dumps(assessment), db.now())).lastrowid
        payload = {"farmer_text": farmer_text, "officer_text": row["draft"], "officer": ACTOR,
                   "context": ctx, "assessment": assessment, "binding": binding, "voice_script": None,
                   "auto_released": True, "qualification": report["reason"]}
        approval_id = con.execute(
            "INSERT INTO approvals(case_id,revision,submission_id,assessment_id,payload,fingerprint,provenance,created_at) "
            "VALUES (?,?,?,?,?,?,'assessed',?)",
            (case_id, expected_revision + 1, submission, assessment_id, json.dumps(payload),
             safety_gate.fingerprint(payload), db.now())).lastrowid
        con.execute(
            "UPDATE cases SET status=?,final_text=?,farmer_text=?,officer=?,officer_note=?,decided_at=?,updated_at=?,revision=revision+1 WHERE id=?",
            ("approved", row["draft"], farmer_text, ACTOR, note, db.now(), db.now(), case_id))
        approval.audit(con, case_id, ACTOR, "auto_release_recorded",
                       revision=expected_revision + 1, approval_id=approval_id, submission_id=submission,
                       assessment_id=assessment_id, reason=report["reason"],
                       judge_status=assessment.get("judge_status"),
                       verdicts=[{"n": v.get("n"), "verdict": v.get("verdict")} for v in report.get("verdicts") or []],
                       sources=[s.get("id") for s in report.get("sources") or []],
                       farmer_text=farmer_text)
        con.commit()
    except BaseException:
        con.rollback()
        raise
    released = db.release_to_farmer(con, case_id, actor=ACTOR)
    return {"released": released["status"] == "released", "case": dict(released),
            "farmer_text": farmer_text, "reason": report["reason"], "approval_id": approval_id}


def consider(case_id: int) -> dict:
    """If the feature is on and the case is eligible, auto-approve and release it.

    Fail closed: errors, timeouts and ineligible cases stay in the officer queue.
    Safe to call more than once (already-released cases are skipped).
    """
    if not enabled():
        return {"released": False, "reason": "disabled"}
    con = db.connect()
    try:
        report = eligibility(con, case_id)
        if not report.get("eligible"):
            _record_deferral(con, case_id, report)
            return {"released": False, "reason": report.get("reason")}
        result = _commit_release(con, case_id, report)
        contact = db.get_contact(con, case_id)
        if contact and result.get("released"):
            try:
                from agrireach.channels import service
                service.deliver(con, case_id, service.configured_channels())
            except Exception:
                # Delivery problems are recorded by the delivery layer; the approval stays.
                pass
        return result
    except Exception as exc:
        _record_deferral(con, case_id, {"reason": "error", "outcome": type(exc).__name__})
        return {"released": False, "reason": "error", "error_type": type(exc).__name__}


def audit_view(con, case_id: int) -> dict | None:
    """Structured audit for the officer UI, or None if this case was never auto-released."""
    events = list_audit_events(con, case_id)
    recorded = next((e for e in reversed(events) if e["event_name"] == "auto_release_recorded"), None)
    if not recorded:
        return None
    details = recorded.get("details") or {}
    row = db.get_case(con, case_id)
    sources = []
    for sid in details.get("sources") or json.loads((row["sources"] if row else None) or "[]"):
        ref = knowledge.reference(sid) or {}
        title = ((ref.get("source") or {}).get("title")) or sid
        sources.append({"id": sid, "title": title, "page": ref.get("page")})
    return {
        "auto_released": True,
        "actor": recorded["actor"],
        "released_at": recorded["created_at"],
        "farmer_text": details.get("farmer_text") or (row["farmer_text"] if row else None),
        "reason": details.get("reason"),
        "judge_status": details.get("judge_status"),
        "verdicts": details.get("verdicts") or [],
        "sources": sources,
        "approval_id": details.get("approval_id"),
        "status": row["status"] if row else None,
        "retracted": any(e["event_name"] == "case_reopened" and e["created_at"] >= recorded["created_at"] for e in events),
        "events": events,
    }


def list_audit_events(con, case_id: int) -> list[dict]:
    rows = con.execute(
        "SELECT id,event_name,actor,details,created_at FROM audit_events WHERE case_id=? ORDER BY id",
        (case_id,),
    ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["details"] = json.loads(item["details"] or "{}")
        except json.JSONDecodeError:
            item["details"] = {}
        out.append(item)
    return out


def is_auto_released_actor(officer: str | None) -> bool:
    return (officer or "") == ACTOR
