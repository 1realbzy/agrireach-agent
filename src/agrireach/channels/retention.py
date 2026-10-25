"""Retention purge for channel senders, e.g. from a daily cron job:

  python -m agrireach.channels.retention            # uses AGRIREACH_RETENTION_DAYS (default 90)
  python -m agrireach.channels.retention --days 30

Removes sender numbers, stored voice notes, held messages and consent records older than the limit. Case text and
the officer's decision are kept, with the sender replaced by "[removed]". The same purge also runs on every inbound
message (channels.service.handle_inbound).
"""
from __future__ import annotations

import argparse
import json

from agrireach import db


def main(argv=None):
    ap = argparse.ArgumentParser(prog="agrireach.channels.retention")
    ap.add_argument("--days", type=int, default=None, help="override AGRIREACH_RETENTION_DAYS")
    args = ap.parse_args(argv)
    print(json.dumps(db.purge_old(db.connect(), args.days)))


if __name__ == "__main__":
    main()
