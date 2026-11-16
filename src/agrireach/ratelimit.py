"""Per-client limit on farmer submissions (POST /ask and clarification replies).

Counts are kept in memory in the API process (one uvicorn worker in compose.demo.yaml); a restart clears them.
Keys are SHA-256 digests of the client address, the farmer-portal browser id, or the farmer's phone number, so no
address or number is stored here. Officer routes are not limited.

Settings (whole numbers above zero; anything else uses the default, never "unlimited"):
  AGRIREACH_SUBMIT_LIMIT            submissions allowed per key in the window (default 10)
  AGRIREACH_SUBMIT_WINDOW_SECONDS   window length in seconds (default 600)
"""
from __future__ import annotations

import hashlib
import math
import os
import threading
import time
from collections import deque

DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 600
MAX_KEYS = 50_000

MESSAGE = ("Too many questions have been sent from this connection or phone number in a short time. Please wait a "
           "few minutes and try again. If someone is ill or has swallowed a chemical, call 112 now.")

_lock = threading.Lock()
_hits: dict[str, deque] = {}


def _positive(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def limits() -> tuple[int, int]:
    return (_positive("AGRIREACH_SUBMIT_LIMIT", DEFAULT_LIMIT),
            _positive("AGRIREACH_SUBMIT_WINDOW_SECONDS", DEFAULT_WINDOW_SECONDS))


def key(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]}"


def check(keys: list[str], now: float | None = None) -> int | None:
    """Record one submission against every key and return None, or return the seconds to wait (nothing recorded)
    when any key has already reached the limit in the current window."""
    limit, window = limits()
    now = time.monotonic() if now is None else now
    with _lock:
        wait = 0
        for k in keys:
            q = _hits.get(k)
            while q and q[0] <= now - window:
                q.popleft()
            if q is not None and len(q) >= limit:
                wait = max(wait, math.ceil(q[0] + window - now))
        if wait:
            return max(wait, 1)
        if len(_hits) >= MAX_KEYS:
            for k in [k for k, q in _hits.items() if not q or q[-1] <= now - window]:
                del _hits[k]
        for k in keys:
            _hits.setdefault(k, deque()).append(now)
    return None


def reset() -> None:
    with _lock:
        _hits.clear()
