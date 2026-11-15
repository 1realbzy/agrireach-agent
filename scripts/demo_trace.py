r"""Read-only demo aid: list the LangGraph agent's MCP tool calls for one case.

Usage (same DATABASE_URL as the running API):
    .\.venv\Scripts\python.exe scripts\demo_trace.py <case_id>

The MCP read tools (search_guidance, retrieve_reference, get_crop_calendar, ...)
are logged without a case id, between the case's first "draft" filing and its
"pending_review" filing, so this prints that window. Run it while one question is
processed at a time; concurrent questions would interleave. Opens SQLite read-only.
"""
import os
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    case_id = int(sys.argv[1])
    path = Path(os.environ.get("DATABASE_URL", "sqlite:///agrireach.db").removeprefix("sqlite:///")).resolve()
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    ids = [r[0] for r in con.execute(
        "SELECT id FROM tool_log WHERE case_id=? AND actor='agent' ORDER BY id", (case_id,))]
    if not ids:
        print(f"No agent log for case {case_id}.")
        return 1
    rows = con.execute(
        "SELECT tool, ok, substr(result_summary, 1, 100) FROM tool_log "
        "WHERE id BETWEEN ? AND ? AND (case_id=? OR case_id IS NULL) ORDER BY id", (ids[0], ids[-1], case_id))
    for tool, ok, summary in rows:
        print(f"{tool:<28} {'ok' if ok else 'BLOCKED':<8} {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
