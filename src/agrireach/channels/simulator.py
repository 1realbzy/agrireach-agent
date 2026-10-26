"""Local simulator channel: a farmer's phone, simulated with files on disk. No outside service.

Sender ids must look like 'sim:<name>' (e.g. sim:farmer-1), so a real phone number can't be typed in by mistake.
Outgoing messages are appended to <outbox>/outbox.jsonl (AGRIREACH_OUTBOX, default data/outbox).

CLI (run from the repo root with PYTHONPATH=src):
  python -m agrireach.channels.simulator ask --sender sim:farmer-1 --audio question.wav
  python -m agrireach.channels.simulator ask --sender sim:farmer-1 --text "When should I plant soybean in Tamale?"
  python -m agrireach.channels.simulator officer-approve --case 3 --officer "Ama Mensah" --accept-proposed
  python -m agrireach.channels.simulator outbox [--sender sim:farmer-1]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from agrireach import db
from agrireach.channels import service
from agrireach.channels.base import InboundMessage, OutboundMessage, SendResult

SENDER_RE = re.compile(r"^sim:[a-z0-9][a-z0-9_-]{0,31}$")


def check_sender(sender: str) -> str:
    if not SENDER_RE.match(sender or ""):
        raise ValueError("simulator sender ids must look like 'sim:farmer-1' (letters, digits, - or _); "
                         "never use a real phone number")
    return sender


class SimulatorChannel:
    name = "simulator"

    def __init__(self, outbox: str | None = None):
        self.dir = Path(outbox or os.getenv("AGRIREACH_OUTBOX", "data/outbox"))

    def send(self, recipient_id: str, message: OutboundMessage) -> SendResult:
        check_sender(recipient_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        audio = None
        if message.audio_path:
            audio = str(self.dir / Path(message.audio_path).name)
            shutil.copyfile(message.audio_path, audio)
        rec = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "to": recipient_id,
               "text": message.text, "audio": audio}
        with open(self.dir / "outbox.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return SendResult(True, "written to simulator outbox")

    def messages(self, recipient_id: str | None = None) -> list[dict]:
        p = self.dir / "outbox.jsonl"
        if not p.exists():
            return []
        rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        return [r for r in rows if recipient_id is None or r["to"] == recipient_id]


async def ask(sender: str, text: str | None = None, audio: str | None = None, transcriber=None) -> dict:
    check_sender(sender)
    audio_path = None
    if audio:
        audio_path = service.save_audio(Path(audio).read_bytes(), Path(audio).suffix or ".wav")
    return await service.handle_inbound(InboundMessage("simulator", sender, text=text, audio_path=audio_path),
                                        channel=SimulatorChannel(), transcriber=transcriber)


def officer_approve(case_id: int, officer: str, farmer_text: str, edited_text: str | None = None, *, token: str, expected_revision: int, acknowledgement: str | None = None, approved_voice_script: str | None = None) -> dict:
    """The officer's decision (named officer required) on the exact farmer_text to send, then release and delivery."""
    if not (farmer_text or "").strip():
        raise ValueError("farmer_text required: the officer approves the exact text the farmer will receive")
    con = db.connect()
    if db.officer_for_token(con, token) != officer:
        raise db.GateError("registered officer credential required")
    db.officer_decide(con, case_id, officer=officer, decision="edit_approve" if edited_text else "approve",
                      edited_text=edited_text, farmer_text=farmer_text, expected_revision=expected_revision, acknowledgement=acknowledgement, approved_voice_script=approved_voice_script)
    db.release_to_farmer(con, case_id, actor=f"officer:{officer}")
    return service.deliver(con, case_id, service.configured_channels()) or {}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agrireach.channels.simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--sender", required=True)
    a.add_argument("--text")
    a.add_argument("--audio")
    o = sub.add_parser("officer-approve")
    o.add_argument("--case", type=int, required=True)
    o.add_argument("--officer", required=True)
    o.add_argument("--edited-text")
    o.add_argument("--revision", type=int, required=True)
    o.add_argument("--voice-script-file", help="UTF8 file containing the exact reviewed spoken script")
    g = o.add_mutually_exclusive_group(required=True)
    g.add_argument("--farmer-text", help="the exact text the farmer will receive")
    g.add_argument("--accept-proposed", action="store_true",
                   help="approve AgriReach's proposed farmer text, printed here first")
    b = sub.add_parser("outbox")
    b.add_argument("--sender")
    args = ap.parse_args(argv)
    if args.cmd == "ask":
        out = asyncio.run(ask(args.sender, args.text, args.audio))
    elif args.cmd == "officer-approve":
        text = args.farmer_text
        if args.accept_proposed:
            row = db.get_case(db.connect(), args.case)
            text = (json.loads(row["farmer_draft"] or "null") or {}).get("text", "") if row else ""
            print(f"Approving this farmer text:\n{text}\n")
        try:
            out = officer_approve(args.case, args.officer, text, args.edited_text,
                                  token=os.getenv("AGRIREACH_OFFICER_TOKEN", ""), expected_revision=args.revision,
                                  acknowledgement=os.getenv("AGRIREACH_ACKNOWLEDGEMENT"),
                                  approved_voice_script=Path(args.voice_script_file).read_text() if args.voice_script_file else None)
        except db.SafetyError as exc:
            out = {"error": exc.assessment}  # Challenge is returned only to this local officer, never logged.
        except db.GateError as exc:
            out = {"error": {"outcome": "conflict", "reason": str(exc)}}
    else:
        out = SimulatorChannel().messages(args.sender)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1 if isinstance(out, dict) and ("error" in out or out.get("ok") is False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
