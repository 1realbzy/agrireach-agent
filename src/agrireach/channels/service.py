"""Channel service: an inbound text or voice note becomes a case in the existing pipeline, and an officer-approved,
released case goes back through the channel it came from.

The officer gate is unchanged. deliver() refuses anything that db.release_to_farmer() has not released (status
'released' with a named approving officer); release itself still requires officer approval. The only messages sent
without an officer are fixed system texts: the acknowledgement and the rule-based clarifying question, the same
ones the /ask API already returns to a farmer.
"""
from __future__ import annotations

import json
import logging
import os
import re
import traceback
import uuid
from pathlib import Path

from agrireach import agent, db, voice_script
from agrireach.channels import location, stt, tts
from agrireach.channels.base import Channel, InboundMessage, OutboundMessage, SendResult, mask_sender  # noqa: F401

ACK = "Thank you. Your question was sent to an extension officer for review. You will get the answer here."
RESEND = "Sorry, AgriReach could not take your question just now. Please send it again."
logger = logging.getLogger(__name__)


def media_dir() -> Path:
    return Path(os.getenv("AGRIREACH_MEDIA_DIR", "data/media"))


def save_audio(data: bytes, suffix: str = ".ogg") -> str:
    """Store an inbound voice note under a random name (never the sender's number)."""
    d = media_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex}{suffix if suffix.startswith('.') else '.' + suffix}"
    p.write_bytes(data)
    return str(p)


CONSENT_PROMPT = ("AgriReach: an agricultural extension officer will answer your farming question here. To reply, we "
                  "keep your number and any voice note for up to {days} days. Reply YES to continue. Reply STOP at "
                  "any time and we delete them.")
STOPPED = "Done. Your number and voice notes have been deleted and AgriReach will not message you again."
STOP_WORDS = {"stop", "unsubscribe", "gyae"}  # "gyae" = "stop" in Twi


def consent_required() -> bool:
    return os.getenv("AGRIREACH_CONSENT", "1") != "0"


def _system_send(con, channel: Channel | None, msg: InboundMessage, text: str, what: str) -> dict | None:
    """A fixed system text (consent prompt, location question, opt-out confirmation): no case, no officer needed."""
    if channel is None:
        return None
    r = channel.send(msg.sender_id, OutboundMessage(text=text))
    db.log(con, f"channel:{msg.channel}", f"send_{what}", {"to": mask_sender(msg.sender_id)},
           "sent" if r.ok else f"FAILED: {r.detail}", ok=r.ok)
    return {"kind": what, "ok": r.ok}


def _held(msg: InboundMessage) -> dict:
    return {"text": msg.text, "audio_path": msg.audio_path}


async def handle_inbound(msg: InboundMessage, channel: Channel | None = None, transcriber=None, con=None) -> dict:
    con = con or db.connect()
    if msg.message_id and not db.first_time_seen(con, msg.channel, msg.message_id):
        return {"duplicate": True}
    db.purge_old(con)  # retention runs on every inbound message as well as from the CLI
    word = re.sub(r"[^\w]", "", (msg.text or "").strip().lower())
    consent = db.get_consent(con, msg.channel, msg.sender_id)
    if not msg.audio_path and (word in STOP_WORDS or (word == "no" and consent == "asked")):
        removed = db.forget_sender(con, msg.channel, msg.sender_id)
        if msg.message_id:  # nothing that links back to this sender is kept
            con.execute("DELETE FROM channel_inbound_seen WHERE channel=? AND message_id=?",
                        (msg.channel, msg.message_id))
            con.commit()
        db.log(con, f"channel:{msg.channel}", "forget_sender", {"from": mask_sender(msg.sender_id)},
               f"removed {removed['contacts']} contact(s), {removed['held']} held message(s)")
        return {"case_id": None, "status": "forgotten", "message": STOPPED,
                "sent": _system_send(con, channel, msg, STOPPED, "stopped")}
    if consent_required() and consent != "yes":
        if consent == "asked" and not msg.audio_path and location.parse_reply(msg.text or "")[0] == "yes":
            db.set_consent(con, msg.channel, msg.sender_id, "yes")
            db.log(con, f"channel:{msg.channel}", "consent", {"from": mask_sender(msg.sender_id)}, "yes")
            out = {"case_id": None, "status": "consented", "message": "", "sent": None}
            for h in db.take_held(con, msg.channel, msg.sender_id, "consent"):
                out = await _process(InboundMessage(msg.channel, msg.sender_id, **h), channel, transcriber, con)
            return out
        db.hold(con, msg.channel, msg.sender_id, "consent", _held(msg))
        if consent is None:
            db.set_consent(con, msg.channel, msg.sender_id, "asked")
        prompt = CONSENT_PROMPT.format(days=db.retention_days())
        return {"case_id": None, "status": "awaiting_consent", "message": prompt,
                "sent": _system_send(con, channel, msg, prompt, "consent_prompt")}
    if db.has_held(con, msg.channel, msg.sender_id, "location"):
        return await _location_reply(msg, channel, transcriber, con)
    return await _process(msg, channel, transcriber, con)


def _transcribe(msg: InboundMessage, transcriber, extra: list[str]):
    if not msg.audio_path:
        return None
    tr = transcriber if transcriber is not None else stt.default()
    if tr is None:
        extra.append("voice note received but speech-to-text is off; officer must listen to the audio")
        return None
    try:
        t = tr.transcribe(msg.audio_path)
        extra += t.warnings
        return t
    except Exception as e:
        extra.append(f"voice note could not be transcribed ({type(e).__name__}); officer must listen to the audio")
        return None


async def _process(msg: InboundMessage, channel, transcriber, con) -> dict:
    extra: list[str] = []
    transcript = _transcribe(msg, transcriber, extra)
    question = f"{(msg.text or '').strip()} {transcript.text if transcript else ''}".strip()
    if msg.audio_path:
        question = question or "[voice note: no transcript]"
    if not question:
        raise ValueError("an inbound message needs text or audio")
    sug = location.suggest(question) if transcript else None
    if sug is not None:
        # A place name that speech-to-text may have mangled: ask the farmer rather than guess.
        db.hold(con, msg.channel, msg.sender_id, "location",
                {"question": question, "extra": extra, "audio_path": msg.audio_path, "transcript": transcript.text,
                 "stt": transcript.as_dict(), "heard": sug.heard, "place": sug.place, "span": list(sug.span)})
        q = sug.question()
        db.log(con, f"channel:{msg.channel}", "location_check", {"from": mask_sender(msg.sender_id)},
               f"heard '{sug.heard}', asked about {sug.place['name']}")
        return {"case_id": None, "status": "awaiting_location", "message": q, "transcript": transcript.text,
                "sent": _system_send(con, channel, msg, q, "location_question")}
    return await _file(con, msg, channel, question, extra, msg.audio_path, transcript.text if transcript else None,
                       transcript.as_dict() if transcript else None)


async def _location_reply(msg: InboundMessage, channel, transcriber, con) -> dict:
    held = db.take_held(con, msg.channel, msg.sender_id, "location")[0]
    extra = list(held["extra"])
    reply_extra: list[str] = []
    rt = _transcribe(msg, transcriber, reply_extra)
    reply = f"{(msg.text or '').strip()} {rt.text if rt else ''}".strip()
    kind, place = location.parse_reply(reply)
    s, e = held["span"]
    q = held["question"]
    stt_info = held["stt"] | {"location_check": {"heard": held["heard"], "asked": held["place"]["name"],
                                                 "reply": kind}}
    if kind == "yes":
        q = q[:s] + held["place"]["name"] + q[e:]
    elif kind == "place":
        q = q[:s] + place["name"] + q[e:]
        stt_info["location_check"]["named"] = place["name"]
    else:
        extra.append(f"location unconfirmed: speech-to-text heard '{held['heard']}', possibly "
                     f"{held['place']['name']} ({held['place']['region']}); the farmer did not confirm")
    if kind != "other" and msg.audio_path:
        db._remove_audio([msg.audio_path])  # a voice "yes" is not kept once used
    db.log(con, f"channel:{msg.channel}", "location_reply", {"from": mask_sender(msg.sender_id)},
           f"{kind}" + (f": {place['name']}" if place else ""))
    out = await _file(con, msg, channel, q, extra, held["audio_path"], held["transcript"], stt_info)
    if kind == "other" and len(re.findall(r"\w+", reply)) > 3:
        # The reply looks like a new question rather than an answer: handle it as one too.
        out = {"location_case": out, **(await _file(con, msg, channel, reply, reply_extra, msg.audio_path,
                                                    rt.text if rt else None, rt.as_dict() if rt else None))}
    return out


def _leaves(e: BaseException):
    if isinstance(e, BaseExceptionGroup):
        for x in e.exceptions:
            yield from _leaves(x)
    else:
        yield e


def log_failure(con, msg: InboundMessage, e: BaseException) -> None:
    """Log every sub-exception of a failed run with its own traceback: an anyio TaskGroup (MCP stdio client) wraps
    the real error in ExceptionGroup, and run 5's log said only 'FAILED: ExceptionGroup'."""
    leaves = list(_leaves(e))
    for i, x in enumerate(leaves, 1):
        tb = "".join(traceback.format_exception(x)).replace(msg.sender_id, mask_sender(msg.sender_id))
        logger.error("inbound %s from %s failed (%d of %d): %s", msg.channel, mask_sender(msg.sender_id), i,
                     len(leaves), tb)
        db.log(con, f"channel:{msg.channel}", "inbound_error",
               {"from": mask_sender(msg.sender_id), "exception": type(x).__name__, "n": i, "of": len(leaves),
                "group": type(e).__name__}, tb if len(tb) <= 1900 else f"{tb[:100]}...\n{tb[-1790:]}", ok=False)


async def _file(con, msg: InboundMessage, channel, question, extra, audio_path, transcript_text, stt_info) -> dict:
    try:
        # queue=False: the case is filed as a draft and only queued below, together with its contact.
        out = await agent.run(question, extra_urgent_reasons=extra, queue=False)
    except Exception as e:
        # The case (if one was saved) stays a draft, out of the officer queue: nobody could send its answer. The
        # farmer is asked to send the question again, every sub-exception is logged, and the error is re-raised.
        log_failure(con, msg, e)
        _system_send(con, channel, msg, RESEND, "resend")
        raise
    case_id = out["case_id"]
    if msg.channel == "sms":
        _add_sms_review(con, case_id)
    contact = dict(channel=msg.channel, sender_id=msg.sender_id, audio_path=audio_path, transcript=transcript_text,
                   stt=stt_info)
    if out["status"] == "draft" and not out["clarification"]:
        db.queue_with_contact(con, case_id, **contact)  # contact + pending_review in one transaction
        out["status"] = "pending_review"
    else:
        db.save_contact(con, case_id, **contact)  # a clarifying question: the case waits for the farmer
    db.log(con, f"channel:{msg.channel}", "inbound_message",
           {"from": mask_sender(msg.sender_id), "voice_note": bool(audio_path),
            "transcript_chars": len(transcript_text or "")},
           f"case {case_id} -> {out['status']}", case_id=case_id)
    reply = out["clarification"] or ACK
    sent = None
    if channel is not None:
        r = channel.send(msg.sender_id, OutboundMessage(text=reply))
        kind = "clarification" if out["clarification"] else "ack"
        db.record_delivery(con, case_id, msg.channel, kind, r.ok, r.detail)
        sent = {"kind": kind, "ok": r.ok}
    return {"case_id": case_id, "status": out["status"], "priority": out["priority"], "message": reply,
            "transcript": transcript_text, "urgent_reasons": out["urgent_reasons"], "question": question,
            "sent": sent}


def sms_review(fd: dict) -> dict:
    """Add the SMS limit (a fact for the officer) and, if the proposed text won't fit, an approval prompt."""
    from agrireach.channels import sms

    fd = dict(fd)
    fd["sms_limit"] = sms.limit_fact()
    prompt = sms.length_prompt(fd.get("text") or "")
    if prompt:
        fd["problems"] = list(fd.get("problems") or []) + [prompt]
    return fd


def _add_sms_review(con, case_id: int) -> None:
    row = db.get_case(con, case_id)
    if row is None or not row["farmer_draft"] or row["status"] not in ("draft", "pending_review"):
        return
    fd = sms_review(json.loads(row["farmer_draft"]))
    con.execute("UPDATE cases SET farmer_draft=? WHERE id=?", (json.dumps(fd, ensure_ascii=False), case_id))
    con.commit()


def _deliver_transport(con, case_id: int, channels: dict[str, Channel]) -> dict | None:
    """Send a released case's approved text back through its channel. None if the case has no channel contact."""
    contact = db.get_contact(con, case_id)
    if contact is None:
        return None
    row = db.get_case(con, case_id)
    from agrireach.approval import validated_approval
    _record, payload = validated_approval(con, case_id)
    text = payload["farmer_text"]  # exactly what the officer approved
    if row is None or row["status"] != "released" or not row["officer"] or not text:
        db.log(con, f"channel:{contact['channel']}", "send_answer", {"to": mask_sender(contact["sender_id"])},
               f"BLOCKED: case is '{row['status'] if row else 'missing'}', not released after officer approval",
               ok=False, case_id=case_id)
        return {"ok": False, "detail": "not released after officer approval"}
    if contact["sender_id"] in db.REMOVED:
        why = ("not sent: the farmer opted out (STOP)" if contact["sender_id"] == db.OPTED_OUT
               else "not sent: the number was removed by the retention purge")
        db.record_delivery(con, case_id, contact["channel"], "answer", False, why)
        db.log(con, f"channel:{contact['channel']}", "send_answer", {}, f"BLOCKED: {why}", ok=False, case_id=case_id)
        db.mark_undeliverable(con, case_id, why, actor=f"channel:{contact['channel']}")  # never left 'released'
        return {"ok": False, "detail": why}
    if db.answer_delivered(con, case_id):
        return {"ok": True, "detail": "already delivered"}
    ch = channels.get(contact["channel"])
    audio = None
    if ch is not None and tts.enabled():
        script_text = payload.get("voice_script")
        if script_text:
            try:
                audio = tts.synthesize(script_text, str(media_dir() / "out" / f"case{case_id}-{uuid.uuid4().hex[:8]}.wav"))
            except Exception as e:  # text still goes out; the officer sees why there is no audio
                db.log(con, "channel:tts", "synthesize", {}, f"failed: {type(e).__name__}", ok=False, case_id=case_id)
    r = ch.send(contact["sender_id"], OutboundMessage(text=text, audio_path=audio)) if ch else \
        SendResult(False, f"channel '{contact['channel']}' is not configured", "definitely_failed")
    db.record_delivery(con, case_id, contact["channel"], "answer", r.ok, r.detail)
    db.log(con, f"channel:{contact['channel']}", "send_answer",
           {"to": mask_sender(contact["sender_id"]), "audio": bool(audio)},
           ("sent: " if r.ok else "FAILED: ") + r.detail, ok=r.ok, case_id=case_id)
    if not r.ok:  # never looks delivered: back to the officer queue with the reason
        db.mark_not_delivered(con, case_id, r.detail, actor=f"channel:{contact['channel']}")
    return {"ok": r.ok, "detail": r.detail, "audio": bool(audio), "outcome": r.outcome, "provider_id": r.provider_id}


def deliver(con, case_id: int, channels: dict[str, Channel]) -> dict | None:
    """Enforced advisory boundary: one committed claim before any transport call.

    Unexpected failures leave unknown, never a retryable failed job. A process
    crash leaves sending, also ineligible for a second claim.
    """
    from agrireach import delivery
    contact = db.get_contact(con, case_id)
    if not contact:
        return None
    if contact["sender_id"] in db.REMOVED:
        why = "not sent: the farmer opted out (STOP)" if contact["sender_id"] == db.OPTED_OUT else "not sent: the number was removed by the retention purge"
        return {"ok": False, "detail": why, "outcome": "undeliverable"}
    try:
        claimed = delivery.claim(con, case_id)
    except db.SafetyError as exc:
        return {"ok": False, "detail": str(exc), "outcome": "blocked", "assessment": exc.assessment}
    except db.GateError as exc:
        db.log(con, "channel", "send_answer", {}, "BLOCKED: " + str(exc), ok=False, case_id=case_id)
        return {"ok": False, "detail": str(exc), "outcome": "blocked"}
    if claimed is None:
        job = con.execute("SELECT j.state FROM delivery_jobs j JOIN approvals a ON a.id=j.approval_id WHERE a.case_id=? ORDER BY j.id DESC LIMIT 1", (case_id,)).fetchone()
        if job and job["state"] == "accepted":
            return {"ok": True, "detail": "already delivered", "outcome": "accepted"}
        return {"ok": False, "detail": "No send: existing job", "outcome": "unchanged"}
    job_id, claim_id = claimed
    try:
        result = _deliver_transport(con, case_id, channels)
    except Exception:
        delivery.complete(con, case_id, job_id, claim_id, "unknown")
        raise
    outcome = result.get("outcome", "accepted" if result.get("ok") else "unknown")
    delivery.complete(con, case_id, job_id, claim_id, outcome, provider_id=result.get("provider_id"))
    return result


def configured_channels() -> dict[str, Channel]:
    from agrireach.channels import simulator, sms, whatsapp

    chans: dict[str, Channel] = {"simulator": simulator.SimulatorChannel()}
    if whatsapp.enabled():
        chans["whatsapp"] = whatsapp.WhatsAppChannel(whatsapp.Config.from_env())
    if sms.enabled():
        chans["sms"] = sms.SmsChannel(sms.Config.from_env())
    return chans
