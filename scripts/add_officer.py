"""Register an extension officer with a name, email, and password.

    python scripts/add_officer.py "Ama Mensah" ama@agrireach.demo

The script prompts for the password twice with getpass (nothing is echoed).
The password must be at least 12 characters. It is never accepted as a
command-line argument and is never printed or written to a file or log.

Non-interactive use (operators and tests only):

  - If standard input is not a terminal, read the password from the first
    line of stdin and the confirmation from the second line.
  - Or set AGRIREACH_OFFICER_PASSWORD in the environment (not echoed).
    When this variable is set, a confirmation is not required.

Token sign-in has been removed. Officers who were created with a sign-in
token must be registered again with this script (the same name is fine) so
an email and password can be set; until then they cannot sign in.

Running it again for the same name updates the email and password and
revokes existing sessions. A different name cannot reuse an email.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agrireach import db  # noqa: E402
from agrireach.passwords import MIN_LENGTH  # noqa: E402

ENV_PASSWORD = "AGRIREACH_OFFICER_PASSWORD"


def _read_secret_line(label: str) -> str:
    if sys.stdin.isatty():
        return getpass.getpass(label)
    line = sys.stdin.readline()
    if line == "":
        sys.exit("Password input ended before a value was provided.")
    return line.rstrip("\n")


def read_password() -> str:
    env = os.environ.get(ENV_PASSWORD)
    if env is not None:
        password = env
    else:
        password = _read_secret_line("Password: ")
        confirm = _read_secret_line("Confirm password: ")
        if password != confirm:
            sys.exit("Passwords did not match.")
    if len(password) < MIN_LENGTH:
        sys.exit(f"Password must be at least {MIN_LENGTH} characters.")
    return password


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or not args[0].strip() or not args[1].strip():
        sys.exit(__doc__)
    name, email = args[0].strip(), args[1].strip()
    password = read_password()
    try:
        db.add_officer(db.connect(), name, email=email, password=password)
    except ValueError as exc:
        sys.exit(str(exc))
    print(f"Officer {name!r} registered with email {db.normalize_email(email)}.")
    print("They can sign in with that email and password. The password is not shown.")


if __name__ == "__main__":
    main()
