"""Channel interface and message types."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class InboundMessage:
    channel: str
    sender_id: str                 # phone number or channel user id: personal data, never logged unmasked
    text: str | None = None        # a typed question, if any
    audio_path: str | None = None  # a saved voice note, if any
    message_id: str | None = None  # channel's own id, for de-duplicating webhook retries
    meta: dict = field(default_factory=dict)


@dataclass
class OutboundMessage:
    text: str                      # officer-approved text, sent as approved
    audio_path: str | None = None  # optional spoken version of the same text


@dataclass
class SendResult:
    ok: bool
    detail: str = ""
    outcome: str = ""

    def __post_init__(self):
        # An adapter must explicitly establish nonacceptance; an unexplained
        # false result is uncertain and cannot safely trigger a resend.
        if not self.outcome:
            self.outcome = "accepted" if self.ok else "unknown"


class Channel(Protocol):
    name: str

    def send(self, recipient_id: str, message: OutboundMessage) -> SendResult: ...


def mask_sender(sender_id: str) -> str:
    """For logs and screens: keep only the last two characters ('sim:farmer-17' -> '***********17')."""
    s = str(sender_id or "")
    return "****" if len(s) <= 4 else "*" * (len(s) - 2) + s[-2:]
