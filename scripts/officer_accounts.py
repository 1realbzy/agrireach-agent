"""Operator CLI for officer email/password accounts (migration v7). Never prints a password or session token.

    python scripts/officer_accounts.py create  ama@example.org "Ama Mensah"   # prompts for the password twice
    python scripts/officer_accounts.py create  ama@example.org "Ama Mensah" --password-stdin < secret.txt
    python scripts/officer_accounts.py set-password ama@example.org          # also revokes open sessions
    python scripts/officer_accounts.py disable ama@example.org               # also revokes open sessions
    python scripts/officer_accounts.py enable  ama@example.org
    python scripts/officer_accounts.py revoke  ama@example.org               # sign the officer out everywhere
    python scripts/officer_accounts.py list

Uses DATABASE_URL like the API. Passwords: at least 12 characters, hashed with scrypt; there are no defaults.
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agrireach import db, officer_auth  # noqa: E402


def _password(args) -> str:
    if args.password_stdin:
        value = sys.stdin.readline().rstrip("\r\n")
    else:
        value = getpass.getpass("New password: ")
        if getpass.getpass("Repeat password: ") != value:
            sys.exit("Passwords do not match; nothing changed.")
    officer_auth.check_password_policy(value)
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("email")
    create.add_argument("name", help="officer name recorded on approvals")
    create.add_argument("--password-stdin", action="store_true")
    setpw = sub.add_parser("set-password")
    setpw.add_argument("email")
    setpw.add_argument("--password-stdin", action="store_true")
    for name in ("disable", "enable", "revoke"):
        sub.add_parser(name).add_argument("email")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    con = db.connect()
    try:
        if args.command == "create":
            email = officer_auth.create_account(con, args.email, args.name, _password(args))
            print(f"Officer account {email} created for {args.name.strip()!r}.")
        elif args.command == "set-password":
            revoked = officer_auth.set_password(con, args.email, _password(args))
            print(f"Password changed; {revoked} open session(s) revoked.")
        elif args.command == "disable":
            print(f"Account disabled; {officer_auth.set_disabled(con, args.email, True)} session(s) revoked.")
        elif args.command == "enable":
            officer_auth.set_disabled(con, args.email, False)
            print("Account enabled.")
        elif args.command == "revoke":
            print(f"{officer_auth.revoke_sessions(con, args.email)} session(s) revoked.")
        else:
            for row in officer_auth.list_accounts(con):
                state = "disabled" if row["disabled"] else "active"
                print(f"{row['email']}\t{row['officer_name']}\t{state}\topen sessions: {row['open_sessions']}")
    except ValueError as exc:
        sys.exit(f"Refused: {exc}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
