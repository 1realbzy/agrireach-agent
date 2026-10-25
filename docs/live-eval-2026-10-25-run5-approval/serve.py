"""Throwaway AgriReach API server for the approval-path eval. Env is set by serve.sh; this only points the SMS
adapter at the local mock (module constant, no app code changed), creates an officer and starts uvicorn."""
import os, sys
sys.path.insert(0, "src")
port, mock = int(sys.argv[1]), sys.argv[2]
from agrireach.channels import sms
if mock != "none":
    sms.SANDBOX_BASE = mock
from agrireach import api, db
tok = db.add_officer(db.connect(), "Eval Officer")
open(os.environ["TOKEN_FILE"], "w").write(tok)
import uvicorn
uvicorn.run(api.app, host="127.0.0.1", port=port, log_level="warning")
