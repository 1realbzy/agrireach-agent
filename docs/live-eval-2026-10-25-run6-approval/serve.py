"""Throwaway AgriReach API server for the approval-path eval (run 6). Env is set by serve.sh. This only:
points the SMS adapter at the local mock (module constant), creates an officer, wraps service.handle_inbound so any
exception prints its full traceback to server.log before it is re-raised (app behaviour unchanged; sms.process
swallows it into a 'FAILED: <type>' log row), and starts uvicorn with info logging. No app code is changed."""
import os, sys, traceback
sys.path.insert(0, "src")
port, mock = int(sys.argv[1]), sys.argv[2]
from agrireach.channels import sms, service
if mock != "none":
    sms.SANDBOX_BASE = mock
_orig = service.handle_inbound
async def _traced(*a, **k):
    try:
        return await _orig(*a, **k)
    except BaseException:
        print("=== TRACE service.handle_inbound ===", flush=True)
        traceback.print_exc()
        sys.stderr.flush()
        raise
service.handle_inbound = _traced
from agrireach import api, db
tok = db.add_officer(db.connect(), "Eval Officer")
open(os.environ["TOKEN_FILE"], "w").write(tok)
import uvicorn
uvicorn.run(api.app, host="127.0.0.1", port=port, log_level="info")
