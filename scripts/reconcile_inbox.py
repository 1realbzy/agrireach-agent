"""Conservative inbox crash reconciliation. No automatic message replay.

Usage:
  python scripts/reconcile_inbox.py
  python scripts/reconcile_inbox.py --apply --minutes 30

Default mode reports counts only. Apply marks stale processing claims uncertain,
requiring operator review before any further action.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from agrireach import db


def inspect(con, older_than: str) -> dict[str, int]:
    counts = con.execute(
        "SELECT state, COUNT(*) AS n FROM channel_inbox GROUP BY state"
    ).fetchall()
    result = {str(row["state"]): int(row["n"]) for row in counts}
    result["stale_processing"] = int(con.execute(
        "SELECT COUNT(*) FROM channel_inbox WHERE state='processing' AND updated_at<?",
        (older_than,),
    ).fetchone()[0])
    # Report evidence without assuming an uncertain event is safe to replay.
    result["uncertain_with_case"] = int(con.execute(
        "SELECT COUNT(*) FROM channel_inbox i JOIN cases c ON c.id=i.case_id "
        "WHERE i.state='uncertain'"
    ).fetchone()[0])
    result["uncertain_without_case"] = int(con.execute(
        "SELECT COUNT(*) FROM channel_inbox WHERE state='uncertain' AND case_id IS NULL"
    ).fetchone()[0])
    result["uncertain_missing_case"] = int(con.execute(
        "SELECT COUNT(*) FROM channel_inbox i LEFT JOIN cases c ON c.id=i.case_id "
        "WHERE i.state='uncertain' AND i.case_id IS NOT NULL AND c.id IS NULL"
    ).fetchone()[0])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Mark stale claims uncertain; never replay")
    parser.add_argument("--minutes", type=int, default=30, help="Minimum age of a stale processing claim")
    args = parser.parse_args()
    if args.minutes < 1:
        parser.error("--minutes must be at least 1")
    older_than = (datetime.now(timezone.utc) - timedelta(minutes=args.minutes)).isoformat(timespec="seconds")
    con = db.connect()
    try:
        before = inspect(con, older_than)
        print("Inbox state counts:", before)
        if args.apply:
            changed = db.reconcile_interrupted_inbound(con, older_than=older_than)
            print("Marked uncertain:", changed)
            print("No messages were replayed or sent.")
        else:
            print("Dry run only. Pass --apply to mark stale processing claims uncertain.")
    finally:
        con.close()


if __name__ == "__main__":
    main()
