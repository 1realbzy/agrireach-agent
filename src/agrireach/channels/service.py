"""Channel service: an inbound text or voice note becomes a case in the existing pipeline, and an officer-approved,
released case goes back through the channel it came from.

The officer gate is unchanged. deliver() refuses anything that db.release_to_farmer() has not released (status
'released' with a named approving officer); release itself still requires officer approval. The only messages sent
without an officer are fixed system texts: the acknowledgement and the rule-based clarifying question, the same
ones the /ask API already returns to a farmer.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from agrireach import agent, db, voice_script
from agrireach.channels import stt, tts
from agrireach.channels.base import Channel, InboundMessage, OutboundMessage, SendResult, mask_sender  # noqa: F401

ACK = "Thank you. Your question was sent to an extension officer for review. You will get the answer here."


def media_dir() -> Path:
    return Path(os.getenv("AGRIREACH_MEDIA_DIR", "data/media"))


def save_audio(data: bytes, suffix: str = ".ogg") -> str:
    """Store an inbound voice note under a random name (never the sender's number)."""
    d = media_dir()
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{uuid.uuid4().hex}{suffix if suffix.startswith('.') else '.' + suffix}"
    p.write_bytes(data)
    return str(p)


async def handle_inbound(msg: InboundMessage, channel: Channel | None = None, transcriber=None, con=None) -> dict:
    con = con or db.connect()
    if msg.message_id and not db.first_time_seen(con, msg.channel, msg.message_id):
        return {"duplicate": True}
    question, extra, transcript = (msg.text or "").strip(), [], None
    if msg.audio_path:
        tr = transcriber if transcriber is not None else stt.default()
        if tr is None:
            extra.append("voice note received but speech-to-text is off; officer must listen to the audio")
        else:
            try:
                transcript = tr.transcribe(msg.audio_path)
                extra += transcript.warnings
                question = f"{question} {transcript.text}".strip()
            except Exception as e:
                extra.append(f"voice note could not be transcribed ({type(e).__name__}); officer must listen to the audio")
        question = question or "[voice note: no transcript]"
    if not question:
        raise ValueError("an inbound message needs text or audio")
    out = await agent.run(question, extra_urgent_reasons=extra)
    case_id = out["case_id"]
    db.save_contact(con, case_id, channel=msg.channel, sender_id=msg.sender_id, audio_path=msg.audio_path,
                    transcript=transcript.text if transcript else None,
                    stt=transcript.as_dict() if transcript else None)
    db.log(con, f"channel:{msg.channel}", "inbound_message",
           {"from": mask_sender(msg.sender_id), "voice_note": bool(msg.audio_path),
            "transcript_chars": len(transcript.text) if transcript else 0},
           f"case {case_id} -> {out['status']}", case_id=case_id)
    reply = out["clarification"] or ACK
    sent = None
    if channel is not None:
        r = channel.send(msg.sender_id, OutboundMessage(text=reply))
        kind = "clarification" if out["clarification"] else "ack"
        db.record_delivery(con, case_id, msg.channel, kind, r.ok, r.detail)
        sent = {"kind": kind, "ok": r.ok}
    return {"case_id": case_id, "status": out["status"], "priority": out["priority"], "message": reply,
            "transcript": transcript.text if transcript else None, "urgent_reasons": out["urgent_reasons"],
            "sent": sent}


def deliver(con, case_id: int, channels: dict[str, Channel]) -> dict | None:
    """Send a released case's approved text back through its channel. None if the case has no channel contact."""
    contact = db.get_contact(con, case_id)
    if contact is None:
        return None
    row = db.get_case(con, case_id)
    if row is None or row["status"] != "released" or not row["officer"] or not row["final_text"]:
        db.log(con, f"channel:{contact['channel']}", "send_answer", {"to": mask_sender(contact["sender_id"])},
               f"BLOCKED: case is '{row['status'] if row else 'missing'}', not released after officer approval",
               ok=False, case_id=case_id)
        return {"ok": False, "detail": "not released after officer approval"}
    if db.answer_delivered(con, case_id):
        return {"ok": True, "detail": "already delivered"}
    ch = channels.get(contact["channel"])
    audio = None
    if ch is not None and tts.enabled():
        script = voice_script.build(row["final_text"], row["officer"], row["crop"] or "")
        if script.ok:
            try:
                audio = tts.synthesize(script.text, str(media_dir() / "out" / f"case{case_id}-{uuid.uuid4().hex[:8]}.wav"))
            except Exception as e:  # text still goes out; the officer sees why there is no audio
                db.log(con, "channel:tts", "synthesize", {}, f"failed: {type(e).__name__}", ok=False, case_id=case_id)
    r = ch.send(contact["sender_id"], OutboundMessage(text=row["final_text"], audio_path=audio)) if ch else \
        SendResult(False, f"channel '{contact['channel']}' is not configured")
    db.record_delivery(con, case_id, contact["channel"], "answer", r.ok, r.detail)
    db.log(con, f"channel:{contact['channel']}", "send_answer",
           {"to": mask_sender(contact["sender_id"]), "audio": bool(audio)},
           ("sent" if r.ok else "FAILED: ") + r.detail, ok=r.ok, case_id=case_id)
    return {"ok": r.ok, "detail": r.detail, "audio": bool(audio)}


def configured_channels() -> dict[str, Channel]:
    from agrireach.channels import simulator, whatsapp

    chans: dict[str, Channel] = {"simulator": simulator.SimulatorChannel()}
    if whatsapp.enabled():
        chans["whatsapp"] = whatsapp.WhatsAppChannel(whatsapp.Config.from_env())
    return chans
