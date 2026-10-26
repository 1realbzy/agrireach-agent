"""Approval transactions bind exact submissions to an immutable safety snapshot.

Model I/O happens before acquiring a write lock. Rechecking the complete binding
inside BEGIN IMMEDIATE prevents a concurrent case edit from approving stale text.
"""
from __future__ import annotations

import json
import secrets
import re
from datetime import datetime, timedelta, timezone

from agrireach import db, knowledge, safety_gate


# Only a bare greeting or thanks (plus a name) skips the source check; anything more is checked.
GREETING = re.compile(r"^(?i:thank you|thanks|hello|hi|good (?:morning|afternoon|evening)|medaase)(?i: for your question)?(?:,? [A-Z][a-z]+)?[.!]?$")


def audit(con, case_id: int, actor: str, event: str, **details):
    """Append a redacted event in the caller's transaction; never commit here."""
    con.execute("INSERT INTO audit_events(case_id,event_name,actor,details,created_at) VALUES (?,?,?,?,?)",
                (case_id, event, actor, json.dumps(details, sort_keys=True), db.now()))


def context(con, row) -> dict:
    """Snapshot assessment relevant case data and complete resolved source contents."""
    from agrireach.channels import tts
    sources = [knowledge.reference(i) for i in json.loads(row["sources"] or "[]")]
    if not all(sources):
        raise db.SafetyError({"outcome": "review_required", "reason": "Unresolved source", "findings": []})
    sources = json.loads(json.dumps(sources))  # Detach cached corpus dictionaries before model I/O.
    contact = db.get_contact(con, row["id"])
    return {"case": {k: row[k] for k in ("id", "revision", "draft", "question", "crop", "region", "farmer_draft", "priority", "urgent_reasons")},
            "sources": sources, "contact": dict(contact) if contact else None,
            "policy": safety_gate.POLICY_VERSION, "voice_enabled": tts.enabled()}


def assess_candidate(text: str, ctx: dict) -> dict:
    """Return structured deterministic and model outcomes without mutating storage."""
    from agrireach import citation_check, claim_check, farmer_reply, llm
    from agrireach.channels import sms
    proposal = json.loads(ctx["case"]["farmer_draft"] or "null") or {}
    result = safety_gate.assess(text, ctx["sources"], language=proposal.get("language", "en"),
                                question=ctx["case"].get("question", "")).to_dict()
    source_conflict = any(str(p).startswith("sources differ") for p in proposal.get("problems", []))
    # A refusal to choose between sources is a recovery path, not a resolution
    # claim. Numeric or model-dependent advice still needs source reconciliation.
    conflict_deferred = farmer_reply.CONFIRM in (text or "") and not re.search(r"\d", text or "")
    if source_conflict and not conflict_deferred:
        result["outcome"] = "review_required" if result["outcome"] == "pass" else result["outcome"]
        result["findings"].append(safety_gate.Finding("SOURCE_CONFLICT", "", "Contradictory sources require officer source resolution").to_dict())
    caveat = proposal.get("zone_caveat")
    result["informational"] = []
    if not farmer_reply.caveat_kept(text or "", caveat):
        result["informational"].append("The approved text omits the case zone caveat; review source applicability")
    if ctx["contact"] and ctx["contact"]["channel"] == "sms" and text and sms.length_prompt(text):
        reason = sms.length_prompt(text)
        return result | {"outcome": "safety_blocked", "reason": reason,
                         "findings": [safety_gate.Finding("CHANNEL_LENGTH", text, reason).to_dict()]}
    if result["outcome"] != "pass" or result["judge_status"] != "required":
        return result
    if not ctx["sources"]:
        return result | {"outcome": "review_required", "reason": "No source supports the candidate",
                         "findings": [safety_gate.Finding("SOURCE_SUPPORT", text, "No source supports the candidate").to_dict()]}
    ids = ", ".join(p["id"] for p in ctx["sources"])
    from agrireach.farmer_reply import _ABBREV_WORDS
    # Deterministic rules have already inspected every sentence. Only an exact
    # code built caveat can be omitted from the probabilistic source comparison.
    fixed = {farmer_reply.CONFIRM, (farmer_reply.zone_caveat(ctx["case"]["region"] or "") or {}).get("sentence")}
    source_sentences = {safety_gate.normalized(s) for p in ctx["sources"] for s in safety_gate.sentences(p["text"])}
    checked_sentences = [re.sub(rf"\b({_ABBREV_WORDS})\.(?=\s)", r"\1", s)
                         for s in safety_gate.sentences(text)
                         if s not in fixed and not safety_gate.registered_template(s) and not GREETING.match(s)
                         and safety_gate.normalized(s) not in source_sentences]
    if not checked_sentences:
        return result | {"judge_status": "not_required"}
    draft = "\n".join(f"{s} [{ids}]" for s in checked_sentences)
    figures = citation_check.check_draft(draft, ctx["sources"])
    if not figures.ok:
        findings = [safety_gate.Finding("SOURCE_FIGURES", "", problem, tuple(p["id"] for p in ctx["sources"])).to_dict()
                    for problem in figures.problems]
        return result | {"outcome": "review_required", "reason": "Figures do not match cited sources",
                         "warnings": figures.problems, "findings": findings}
    checked = claim_check.check_claims(draft, ctx["sources"], judge=True)
    result["judge"] = checked.judge
    if checked.judge_failed:
        finding = safety_gate.Finding("JUDGE_AVAILABILITY", "",
            "Required judge did not return a complete valid assessment",
            recovery=("retry_assessment", "revise", "reject", "request_info"))
        return result | {"outcome": "assessment_unavailable", "judge_status": "failed",
                         "findings": [finding.to_dict()]}
    if checked.problems:
        # Only noncritical probabilistic support verdicts may be acknowledged.
        # Lexical/source problems and chemical uncertainty need revision instead.
        model_warnings = [v for v in (checked.judge or {}).get("verdicts", []) if v["verdict"] == "not_supported"]
        chemical = any(p.get("risk") == "chemical" for p in ctx["sources"])
        food_safety = bool(re.search(r"\b(?:aflatoxin|poison(?:ing)?|mouldy|moldy)\b", ctx["case"]["question"] + " " + text, re.I))
        # The judge is advisory: a "not supported" verdict on how-to advice (when, what, how much,
        # how often) must be edited by the officer; acknowledging the warning is not enough.
        how_to = any(re.search(r"\b(?:harvest|plant|sow|appl[yi]|put|pour|mix|spray|treat|stor|dr[yi]|dose|times|every|"
                               r"daily|weekly|days?|weeks?|when|before|after)\w*|\d", v["sentence"], re.I) for v in model_warnings)
        critical = chemical or food_safety or source_conflict or how_to
        recovery = ["revise", "reject", "request_info"]
        result["findings"] = [{"rule_id": "SOURCE_SUPPORT", "sentence": v["sentence"], "reason": v.get("why", "Unsupported source claim"),
                               "evidence": v["cited"], "recovery": recovery} for v in model_warnings] or [
            {"rule_id": "SOURCE_SUPPORT", "sentence": "", "reason": p, "evidence": [s["id"] for s in ctx["sources"]],
             "recovery": recovery} for p in checked.problems]
        result["warnings"] = checked.problems
        return result | {"outcome": "acknowledgement_required" if model_warnings and len(model_warnings) == len(checked.problems) and not critical else "review_required",
                         "judge_status": "concern"}
    return result | {"judge_status": "supported" if checked.judge else "not_required"}


def decide(con, case_id: int, *, officer: str, decision: str, edited_text=None,
           farmer_text=None, note=None, expected_revision=None, acknowledgement=None, approved_voice_script=None) -> dict:
    """Assess, persist evidence and atomically decide on an unchanged case.

    Raises SafetyError with rule evidence, or GateError on stale state/challenge.
    Rejected submissions remain in storage. Remote callers authenticate officer
    before entry; direct Python calls are trusted local application code.
    """
    row = db.get_case(con, case_id)
    if row is None:
        raise ValueError("Case not found")
    if not officer or not officer.strip():
        raise db.GateError("Named officer required")
    if decision not in db.OFFICER_DECISIONS:
        raise ValueError("Valid decision required")
    if expected_revision is None or expected_revision != row["revision"]:
        raise db.GateError("stale_revision: reload the case")
    if row["status"] not in ("pending_review", "not_delivered"):
        raise db.GateError("Case is not available for review")
    active = con.execute("SELECT 1 FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? AND j.state IN ('sending','unknown','accepted')", (case_id,)).fetchone()
    if active and decision in ("approve", "edit_approve"):
        # Rejecting advice does not cancel or resolve an external send. The job
        # remains visible and cannot be retried without reconciliation.
        raise db.GateError("Delivery is active, unresolved or accepted; reapproval is prohibited")
    approving = decision in ("approve", "edit_approve")
    final = edited_text if decision == "edit_approve" else row["draft"]
    if decision == "edit_approve" and not edited_text:
        raise ValueError("edited_text required")
    ctx = context(con, row) if approving else {"revision": row["revision"]}
    from agrireach import llm
    with llm.usage_logged(case_id, f"officer:{officer}", "approval_check"):
        assessment = assess_candidate(farmer_text, ctx) if approving else {"outcome": "pass", "judge_status": "not_required"}
    script_text = None
    if approving and ctx["voice_enabled"]:
        from agrireach import voice_script
        script = voice_script.build(farmer_text or "", officer, row["crop"] or "")
        if not script.ok or (farmer_text or "").strip() != voice_script.speakable(farmer_text or "") or approved_voice_script != script.text:
            assessment = {"outcome": "review_required", "reason": "Preview and approve the exact spoken script; remove unsafe markup explicitly", "findings": [safety_gate.Finding("VOICE_APPROVAL", "", "Preview and approve the exact spoken script").to_dict()], "judge_status": "not_required"}
        else:
            script_text = script.text
    credential = con.execute("SELECT token_sha256 FROM officers WHERE name=?", (officer,)).fetchone()
    credential_hash = credential[0] if credential else None
    # Bind stable warning identity, not model explanation prose, which may change
    # between identical assessments. New sentences/rules/evidence still invalidate.
    warning_identity = {
        "outcome": assessment["outcome"],
        "judge_status": assessment.get("judge_status"),
        "findings": sorted(
            (f["rule_id"], f.get("sentence", ""), tuple(sorted(f.get("evidence", []))))
            for f in assessment.get("findings", [])),
    }
    binding = safety_gate.fingerprint({"context": ctx, "farmer_text": farmer_text, "officer_text": final,
                                       "decision": decision, "officer": officer, "credential": credential_hash, "voice_script": script_text,
                                       "assessment": warning_identity})
    status = {"approve": "approved", "edit_approve": "approved", "reject": "rejected", "request_info": "needs_info"}[decision]
    blocked = None
    try:
        con.execute("BEGIN IMMEDIATE")
        fresh = db.get_case(con, case_id)
        current_credential = con.execute("SELECT token_sha256 FROM officers WHERE name=?", (officer,)).fetchone()
        if fresh["status"] != row["status"] or (context(con, fresh) if approving else {"revision": fresh["revision"]}) != ctx or (current_credential[0] if current_credential else None) != credential_hash:
            raise db.GateError("stale_revision: assessment context changed")
        submission = con.execute("INSERT INTO advisory_submissions(case_id,revision,officer,farmer_text,officer_text,decision,note,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (case_id, expected_revision, officer, farmer_text, final, decision, note, db.now())).lastrowid
        assessment_id = con.execute("INSERT INTO safety_assessments(case_id,snapshot,assessment,created_at) VALUES (?,?,?,?)",
            (case_id, json.dumps(ctx), json.dumps(assessment), db.now())).lastrowid
        outcome = assessment["outcome"]
        challenge_hash = None
        if acknowledgement and outcome != "acknowledgement_required":
            raise db.GateError("Acknowledgement does not match an eligible warning assessment")
        if outcome == "acknowledgement_required":
            if acknowledgement:
                challenge_hash = db._token_hash(acknowledgement)
                challenge = con.execute("SELECT * FROM acknowledgement_challenges WHERE token_hash=?", (challenge_hash,)).fetchone()
                if not challenge or challenge["binding"] != binding or challenge["consumed_approval"] or challenge["expires_at"] <= db.now() or not credential_hash:
                    raise db.GateError("Invalid, expired or replayed acknowledgement; reassess")
            else:
                token = secrets.token_urlsafe(32)
                expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(timespec="seconds")
                con.execute("INSERT INTO acknowledgement_challenges VALUES (?,?,?,?,?,NULL)",
                    (db._token_hash(token), case_id, assessment_id, binding, expiry))
                blocked = assessment | {"acknowledgement": token, "expires_at": expiry}
        elif outcome != "pass":
            blocked = assessment
        if blocked:
            audit(con, case_id, officer, outcome, submission_id=submission, assessment_id=assessment_id,
                  rule_ids=[f["rule_id"] for f in assessment.get("findings", [])])
        else:
            approval_id = None
            if approving:
                payload = {"farmer_text": farmer_text, "officer_text": final, "officer": officer,
                           "context": ctx, "assessment": assessment, "binding": binding, "voice_script": script_text}
                approval_id = con.execute("INSERT INTO approvals(case_id,revision,submission_id,assessment_id,payload,fingerprint,provenance,created_at) VALUES (?,?,?,?,?,?,'assessed',?)",
                    (case_id, expected_revision + 1, submission, assessment_id, json.dumps(payload), safety_gate.fingerprint(payload), db.now())).lastrowid
                if challenge_hash:
                    con.execute("UPDATE acknowledgement_challenges SET consumed_approval=? WHERE token_hash=? AND consumed_approval IS NULL", (approval_id, challenge_hash))
                    audit(con, case_id, officer, "acknowledgement_consumed", approval_id=approval_id, assessment_id=assessment_id)
            con.execute("UPDATE cases SET status=?,final_text=?,farmer_text=?,officer=?,officer_note=?,decided_at=?,updated_at=?,revision=revision+1 WHERE id=?",
                        (status, final if approving else None, farmer_text if approving else None, officer, note, db.now(), db.now(), case_id))
            audit(con, case_id, officer, "approval_recorded" if approving else "officer_decision",
                  revision=expected_revision + 1, approval_id=approval_id, submission_id=submission, decision=decision, informational=assessment.get("informational", []))
        con.commit()
    except BaseException:
        con.rollback()
        raise
    if blocked:
        raise db.SafetyError(blocked)
    return dict(db.get_case(con, case_id))


def validated_approval(con, case_id: int) -> tuple[dict, dict]:
    """Validate immutable payload, current sources and current case before exposure.

    Never regenerate a judge verdict during delivery. A changed source/policy or
    missing modern approval requires fresh officer review, including legacy rows.
    """
    row = db.get_case(con, case_id)
    approval = con.execute("SELECT * FROM approvals WHERE case_id=? ORDER BY id DESC LIMIT 1", (case_id,)).fetchone()
    if not row or not approval or approval["provenance"] != "assessed":
        raise db.GateError("Fresh safety assessed approval required")
    payload = json.loads(approval["payload"])
    ctx = context(con, row)
    ctx["case"]["revision"] = payload["context"]["case"]["revision"]
    if row["revision"] != approval["revision"] or ctx != payload["context"] or safety_gate.fingerprint(payload) != approval["fingerprint"]:
        raise db.GateError("Approval fingerprint changed; fresh approval required")
    result = safety_gate.assess(payload["farmer_text"], ctx["sources"], language=(json.loads(ctx["case"]["farmer_draft"] or "null") or {}).get("language", "en"), question=ctx["case"]["question"])
    if result.outcome != "pass":
        raise db.SafetyError(result.to_dict())
    return dict(approval), payload


def release(con, case_id: int, actor="system") -> dict:
    """Release one valid immutable approval; repeated requests are idempotent."""
    try:
        con.execute("BEGIN IMMEDIATE")
        approval, payload = validated_approval(con, case_id)
        row = db.get_case(con, case_id)
        if row["status"] not in ("approved", "not_delivered", "released"):
            raise db.GateError(f"Case is {row['status']}; not eligible for release")
        contact = db.get_contact(con, case_id)
        if contact:
            if contact["sender_id"] in db.REMOVED:
                why = "not sent: the farmer opted out (STOP)" if contact["sender_id"] == db.OPTED_OUT else "not sent: the number was removed by the retention purge"
                con.execute("UPDATE cases SET status='undeliverable',updated_at=? WHERE id=?", (db.now(), case_id))
                con.execute("INSERT INTO channel_deliveries(case_id,channel,kind,ok,detail,ts) VALUES (?,?,'answer',0,?,?)", (case_id, contact["channel"], why, db.now()))
                audit(con, case_id, actor, "delivery_undeliverable", approval_id=approval["id"])
                db.log(con, actor, "mark_undeliverable", {}, why, ok=False, case_id=case_id, commit=False)
                con.commit()
                return dict(db.get_case(con, case_id))
            con.execute("INSERT INTO delivery_jobs(approval_id,channel,recipient_hash,state,updated_at) VALUES (?,?,?,'pending',?) ON CONFLICT(approval_id,channel) DO NOTHING",
                (approval["id"], contact["channel"], db._token_hash(contact["sender_id"]), db.now()))
            job = con.execute("SELECT state FROM delivery_jobs WHERE approval_id=? AND channel=?", (approval["id"], contact["channel"])).fetchone()
            if job["state"] in ("sending", "unknown"):
                raise db.GateError("Delivery is active or unknown; reconciliation required")
        con.execute("UPDATE cases SET status='released',updated_at=? WHERE id=?", (db.now(), case_id))
        audit(con, case_id, actor, "release_recorded", approval_id=approval["id"])
        con.commit()
    except BaseException:
        con.rollback()
        raise
    return dict(db.get_case(con, case_id))
