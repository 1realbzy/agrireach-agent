"""Register an extension officer and print their sign-in token ONCE (only its SHA-256 is stored).

    python scripts/add_officer.py "Ama Mensah"

Running it again for the same name issues a new token and the old one stops working.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agrireach import db  # noqa: E402

if len(sys.argv) != 2 or not sys.argv[1].strip():
    sys.exit(__doc__)
token = db.add_officer(db.connect(), sys.argv[1])
print(f"Officer {sys.argv[1].strip()!r} registered. Sign-in token (shown once, keep it private):\n{token}")
