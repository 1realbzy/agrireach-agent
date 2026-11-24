"""Test helper: register an officer and return a session token.

Production add_officer requires an email and password and does not return a
session. Tests that only need an authorized officer use this wrapper.
"""
from agrireach import db

TEST_PASSWORD = "test-officer-pass-12"


def officer_email(name: str) -> str:
    slug = ".".join(part.lower() for part in name.split() if part)
    return f"{slug}@agrireach.test"


def add_officer(con, name: str, email: str | None = None, password: str = TEST_PASSWORD) -> str:
    """Register the officer and return a fresh session bearer (not a long-lived token)."""
    email = email or officer_email(name)
    db.add_officer(con, name, email=email, password=password)
    result = db.login_officer(con, email, password)
    if not result:
        raise RuntimeError("test officer login failed")
    return result[1]
