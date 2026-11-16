"""Ghana mobile numbers for farmer SMS consent.

National destination codes follow the NCA numbering plan
(https://nca.org.gh/numbering/) and the published plan table
(https://nms-test.nca.org.gh/numbering-plan/). Public mobile NDCs used here are
20-28 and 50-59. 029 is listed for National Security and is rejected. Fixed
lines (03), machine-to-machine (07), toll-free (08) and premium (09) numbers
are rejected.

mNotify quick-SMS samples address recipients as the national trunk form
0XXXXXXXXX (https://readthedocs.mnotify.com/). Stored values are E.164.
"""
from __future__ import annotations

import re

from agrireach.channels.base import mask_sender

MESSAGE = "Enter a Ghana mobile number as 10 digits starting with 0, or as +233 followed by 9 digits."
_MOBILE_NSN = {f"{n:02d}" for n in (*range(20, 29), *range(50, 60))}
_SEPARATORS = re.compile(r"[\s\-().]")


class PhoneError(ValueError):
    """A farmer-facing rejection that never repeats the submitted number."""


def normalize(raw: str | None) -> str:
    """Return +233 and nine digits, or raise PhoneError."""
    if raw is None or not str(raw).strip():
        raise PhoneError(MESSAGE)
    compact = _SEPARATORS.sub("", str(raw).strip())
    if compact.startswith("+"):
        digits = compact[1:]
        nsn = _international(digits) if digits.isdigit() else None
    elif compact.startswith("00") and compact[2:].isdigit():
        nsn = _international(compact[2:])
    elif compact.isdigit():
        nsn = _national(compact)
    else:
        nsn = None
    if nsn is None or len(nsn) != 9 or nsn[:2] not in _MOBILE_NSN:
        raise PhoneError(MESSAGE)
    return "+233" + nsn


def to_local(e164: str) -> str:
    """National trunk form used by the documented mNotify request samples."""
    normalized = normalize(e164)
    return "0" + normalized[4:]


def mask_phone(e164: str) -> str:
    """Last two digits only, for operator views and logs."""
    return mask_sender(e164)


def _international(digits: str) -> str | None:
    if not digits.startswith("233"):
        return None
    rest = digits[3:]
    if rest.startswith("0"):
        return None
    return rest


def _national(digits: str) -> str | None:
    if len(digits) == 10 and digits.startswith("0"):
        return digits[1:]
    if len(digits) == 12 and digits.startswith("233"):
        return _international(digits)
    if len(digits) == 9:
        return digits
    return None
