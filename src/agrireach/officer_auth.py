"""Officer email/password sign-in, expiring server-side sessions, and private farmer sessions (migration v7).

Officers
- Accounts are provisioned by an operator with scripts/officer_accounts.py; there is no sign-up or admin HTTP route.
- Passwords are hashed with stdlib scrypt (N=2**14, r=8, p=1, 16-byte salt); only the hash is stored.
- POST /officer/auth/login returns an opaque session token (shown to the portal once); only its SHA-256 is stored.
  Sessions expire after AGRIREACH_OFFICER_SESSION_HOURS (default 8, at most 24) and are revoked by logout, by
  disabling the account, by a password change, or by the operator (scripts/officer_accounts.py revoke).
- Failed logins are rate limited per email and per client: AGRIREACH_LOGIN_MAX_FAILURES (default 5) failures in
  AGRIREACH_LOGIN_WINDOW_SECONDS (default 900) lock that key until the window passes (HTTP 429, Retry-After).
- Legacy officer tokens (scripts/add_officer.py) still work unless AGRIREACH_LEGACY_OFFICER_TOKENS=0. Set it to 0
  on any deployed server so only expiring sessions can sign in.

Farmers
- A phone number is an identifier, never proof of ownership, and never grants access to a case.
- POST /farmer/session issues an opaque private session (AGRIREACH_FARMER_SESSION_HOURS, default 24) that the
  farmer portal keeps server-side. Cases filed with it can be read and listed with it; no reference numbers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

SCRYPT_N, SCRYPT_R, SCRYPT_P, SALT_BYTES, KEY_BYTES = 2 ** 14, 8, 1, 16, 32
MIN_PASSWORD = 12
MAX_PASSWORD = 256
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
INVALID_LOGIN = "Invalid email or password."
LOCKED = "Too many failed sign-in attempts. Wait a few minutes and try again."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _int_env(name: str, default: int, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, maximum) if maximum else value


def session_hours() -> int:
    return _int_env("AGRIREACH_OFFICER_SESSION_HOURS", 8, 24)


def farmer_session_hours() -> int:
    return _int_env("AGRIREACH_FARMER_SESSION_HOURS", 24, 24 * 7)


def login_limits() -> tuple[int, int]:
    return _int_env("AGRIREACH_LOGIN_MAX_FAILURES", 5), _int_env("AGRIREACH_LOGIN_WINDOW_SECONDS", 900)


def legacy_tokens_enabled() -> bool:
    return os.getenv("AGRIREACH_LEGACY_OFFICER_TOKENS", "1").strip() != "0"


# --- Passwords ---------------------------------------------------------------------------------------------------

def hash_password(password: str) -> str:
    check_password_policy(password)
    salt = secrets.token_bytes(SALT_BYTES)
    key = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=KEY_BYTES)
    enc = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${enc(salt)}${enc(key)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        kind, n, r, p, salt, key = stored.split("$")
        if kind != "scrypt":
            return False
        expected = base64.b64decode(key)
        actual = hashlib.scrypt((password or "").encode("utf-8")[:4 * MAX_PASSWORD], salt=base64.b64decode(salt),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


_DUMMY_HASH: str | None = None


def _dummy_hash() -> str:
    """Used for unknown emails so a wrong email costs the same time as a wrong password."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(24))
    return _DUMMY_HASH


def check_password_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
    if len(password) > MAX_PASSWORD:
        raise ValueError(f"password must be at most {MAX_PASSWORD} characters")


def normalise_email(email: str) -> str:
    value = (email or "").strip().lower()
    if not EMAIL.match(value) or len(value) > 254:
        raise ValueError("a valid email address is required")
    return value


# --- Accounts (operator CLI only) -------------------------------------------------------------------------------

def create_account(con, email: str, officer_name: str, password: str) -> str:
    """Create an officer account. The officer name is the name recorded on approvals."""
    email = normalise_email(email)
    name = (officer_name or "").strip()
    if not name:
        raise ValueError("officer name required")
    hashed = hash_password(password)
    t = _iso(_now())
    with con:
        if con.execute("SELECT 1 FROM officer_accounts WHERE email=?", (email,)).fetchone():
            raise ValueError("an account with this email already exists")
        if not con.execute("SELECT 1 FROM officers WHERE name=?", (name,)).fetchone():
            # The legacy token column is NOT NULL; store the digest of a random value nobody holds.
            con.execute("INSERT INTO officers(name, token_sha256, created_at) VALUES (?,?,?)",
                        (name, _sha(secrets.token_urlsafe(32)), t))
        con.execute("INSERT INTO officer_accounts(email, officer_name, password_hash, disabled, created_at, updated_at)"
                    " VALUES (?,?,?,0,?,?)", (email, name, hashed, t, t))
    return email


def set_password(con, email: str, password: str) -> int:
    """Change a password and revoke every open session of that account. Returns sessions revoked."""
    email = normalise_email(email)
    hashed = hash_password(password)
    with con:
        if con.execute("UPDATE officer_accounts SET password_hash=?, updated_at=? WHERE email=?",
                       (hashed, _iso(_now()), email)).rowcount != 1:
            raise ValueError("no such account")
        return _revoke(con, email, "password changed")


def set_disabled(con, email: str, disabled: bool) -> int:
    email = normalise_email(email)
    with con:
        if con.execute("UPDATE officer_accounts SET disabled=?, updated_at=? WHERE email=?",
                       (int(disabled), _iso(_now()), email)).rowcount != 1:
            raise ValueError("no such account")
        return _revoke(con, email, "account disabled") if disabled else 0


def revoke_sessions(con, email: str, reason: str = "revoked by operator") -> int:
    email = normalise_email(email)
    with con:
        return _revoke(con, email, reason)


def _revoke(con, email: str, reason: str) -> int:
    return con.execute("UPDATE officer_sessions SET revoked_at=?, revoked_reason=? WHERE email=? AND revoked_at IS NULL",
                       (_iso(_now()), reason[:200], email)).rowcount


def list_accounts(con) -> list[dict]:
    now = _iso(_now())
    rows = con.execute(
        "SELECT a.email, a.officer_name, a.disabled, a.created_at, "
        "(SELECT count(*) FROM officer_sessions s WHERE s.email=a.email AND s.revoked_at IS NULL AND s.expires_at>?)"
        " AS open_sessions FROM officer_accounts a ORDER BY a.email", (now,)).fetchall()
    return [dict(r) for r in rows]


# --- Login rate limiting -----------------------------------------------------------------------------------------

def _keys(email: str, client: str) -> list[str]:
    return [_sha(f"email:{email}"), _sha(f"client:{client}")]


def retry_after(con, email: str, client: str) -> int | None:
    """Seconds until a locked key may try again, or None. Per email and per client, failures only."""
    limit, window = login_limits()
    now = _now()
    since = _iso(now - timedelta(seconds=window))
    wait = 0
    # The client key is shared by everyone behind one portal unless the portal header is trusted; give it 4x room.
    for key, allowed in zip(_keys(email, client), (limit, limit * 4)):
        rows = con.execute("SELECT created_at FROM officer_login_attempts WHERE key_sha256=? AND ok=0 AND created_at>?"
                           " ORDER BY created_at", (key, since)).fetchall()
        if len(rows) >= allowed:
            oldest = datetime.fromisoformat(rows[len(rows) - allowed]["created_at"])
            wait = max(wait, int((oldest + timedelta(seconds=window) - now).total_seconds()) + 1)
    return max(wait, 1) if wait else None


def _record(con, email: str, client: str, ok: bool) -> None:
    t = _iso(_now())
    keys = _keys(email, client) if not ok else _keys(email, client)[:1]
    con.executemany("INSERT INTO officer_login_attempts(key_sha256, ok, created_at) VALUES (?,?,?)",
                    [(k, int(ok), t) for k in keys])
    # Keep the table small: anything older than a day is no longer used by any window.
    con.execute("DELETE FROM officer_login_attempts WHERE created_at<?", (_iso(_now() - timedelta(days=1)),))


class LoginLocked(Exception):
    def __init__(self, wait: int):
        self.wait = wait
        super().__init__(LOCKED)


def login(con, email: str, password: str, client: str) -> dict | None:
    """A new session for a correct email and password, None for a wrong one; LoginLocked when rate limited.
    The returned token is the only copy; the database keeps its SHA-256."""
    try:
        email = normalise_email(email)
    except ValueError:
        email = (email or "").strip().lower()[:254]
    wait = retry_after(con, email, client)
    if wait is not None:
        raise LoginLocked(wait)
    row = con.execute("SELECT email, officer_name, password_hash, disabled FROM officer_accounts WHERE email=?",
                      (email,)).fetchone()
    ok = verify_password(password or "", row["password_hash"] if row else _dummy_hash())
    ok = bool(ok and row and not row["disabled"] and isinstance(password, str) and len(password) <= MAX_PASSWORD)
    with con:
        _record(con, email, client, ok)
        if not ok:
            return None
        token = secrets.token_urlsafe(32)
        created = _now()
        expires = created + timedelta(hours=session_hours())
        con.execute("INSERT INTO officer_sessions(token_sha256, email, created_at, expires_at) VALUES (?,?,?,?)",
                    (_sha(token), email, _iso(created), _iso(expires)))
    return {"session_token": token, "token_type": "Bearer", "expires_at": _iso(expires),
            "officer": row["officer_name"], "email": email}


def session_for_token(con, token: str | None) -> dict | None:
    """The open session behind a bearer token: unexpired, unrevoked, account enabled."""
    if not token or len(token) > 256:
        return None
    row = con.execute(
        "SELECT s.id, s.email, s.expires_at, a.officer_name FROM officer_sessions s "
        "JOIN officer_accounts a ON a.email=s.email "
        "WHERE s.token_sha256=? AND s.revoked_at IS NULL AND a.disabled=0", (_sha(token),)).fetchone()
    if not row or datetime.fromisoformat(row["expires_at"]) <= _now():
        return None
    return {"session_id": row["id"], "email": row["email"], "officer": row["officer_name"],
            "expires_at": row["expires_at"]}


def logout(con, token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    with con:
        return con.execute("UPDATE officer_sessions SET revoked_at=?, revoked_reason='logout' "
                           "WHERE token_sha256=? AND revoked_at IS NULL", (_iso(_now()), _sha(token))).rowcount == 1


# --- Farmer private sessions -------------------------------------------------------------------------------------

def new_farmer_session(con) -> dict:
    token = secrets.token_urlsafe(32)
    created = _now()
    expires = created + timedelta(hours=farmer_session_hours())
    with con:
        con.execute("INSERT INTO farmer_sessions(token_sha256, created_at, expires_at) VALUES (?,?,?)",
                    (_sha(token), _iso(created), _iso(expires)))
    return {"farmer_session": token, "expires_at": _iso(expires)}


def farmer_session_valid(con, token: str | None) -> bool:
    if not token or len(token) > 256:
        return False
    row = con.execute("SELECT expires_at FROM farmer_sessions WHERE token_sha256=?", (_sha(token),)).fetchone()
    return bool(row and datetime.fromisoformat(row["expires_at"]) > _now())


def link_farmer_case(con, token: str, case_id: int) -> None:
    with con:
        con.execute("INSERT OR IGNORE INTO farmer_session_cases(session_sha256, case_id, created_at) VALUES (?,?,?)",
                    (_sha(token), case_id, _iso(_now())))


def farmer_session_owns(con, token: str | None, case_id: int) -> bool:
    if not farmer_session_valid(con, token):
        return False
    return con.execute("SELECT 1 FROM farmer_session_cases WHERE session_sha256=? AND case_id=?",
                       (_sha(token), case_id)).fetchone() is not None


def farmer_session_cases(con, token: str | None) -> list[int]:
    if not farmer_session_valid(con, token):
        return []
    return [r[0] for r in con.execute("SELECT case_id FROM farmer_session_cases WHERE session_sha256=? "
                                      "ORDER BY case_id DESC LIMIT 50", (_sha(token),))]
