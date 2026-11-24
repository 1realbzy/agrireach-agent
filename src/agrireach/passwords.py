"""Argon2id password hashing for officer accounts.

Uses argon2-cffi's PasswordHasher: a per-password random salt is built in, and
verify() is constant-time for a valid hash. Parameters are a conservative
balance of the OWASP Argon2id baseline and local/CI cost.
"""
from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_LENGTH = 12

# time_cost=2, memory_cost=32 MiB, parallelism=1, 32-byte hash, 16-byte salt.
HASHER = PasswordHasher(
    time_cost=2,
    memory_cost=32768,
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Used only so a missing account still runs a full verify, reducing timing leaks.
_DUMMY_HASH = HASHER.hash("agrireach-timing-dummy-not-a-password")


def hash_password(password: str) -> str:
    if len(password) < MIN_LENGTH:
        raise ValueError(f"password must be at least {MIN_LENGTH} characters")
    return HASHER.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Return True only when password_hash is a real stored hash that matches.

    Always runs Argon2 verification (against a dummy hash when none is stored)
    so missing accounts and accounts without a password do not take a shorter path.
    """
    target = password_hash or _DUMMY_HASH
    try:
        matched = HASHER.verify(target, password)
    except (VerifyMismatchError, InvalidHashError, VerificationError, TypeError, ValueError):
        return False
    return bool(matched) and password_hash is not None
