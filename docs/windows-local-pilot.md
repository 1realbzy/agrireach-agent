# Windows controlled local pilot

Scope: one Windows PC, two people taking turns in separate browser sessions. Bind both services to loopback. The farmer simulator is unauthenticated and exposes synthetic messages; do not publish it or open firewall ports. This is an offline text workflow trial, not production or agronomic validation. Real SMS and WhatsApp must stay disabled. No model credentials are needed for the labelled stub. Voice and live model/provider testing are separate, unverified activities.

## Setup (PowerShell, Python 3.13 and Git installed)

Use a folder in your private Windows user profile; SQLite databases and migration backups inherit its Windows ACLs. POSIX mode bits do not verify Windows file privacy. Keep this synthetic pilot out of shared or synced folders.

Run from a normal PowerShell window. No activation script or execution-policy change is needed:

```powershell
git clone --branch work/phase2-inbound-durability https://github.com/1realbzy/agrireach-agent.git
Set-Location agrireach-agent
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Create `pilot-env.ps1` in the repository with this content. It contains no secrets. Dot-source it in **each** terminal before running an application or maintenance command. The application does not automatically load `.env`.

```powershell
$env:PYTHONPATH = 'src'
$env:DATABASE_URL = 'sqlite:///data/pilot.db'
$env:AGRIREACH_API = 'http://127.0.0.1:8000'
$env:AGRIREACH_SIMULATOR = '1'
$env:SMS_ENABLED = '0'
$env:WHATSAPP_ENABLED = '0'
$env:AGRIREACH_SOURCE_CHECK = '0'
$env:AGRIREACH_RAINFALL = 'off'
$env:AGRIREACH_STT = 'none'
$env:AGRIREACH_TTS = ''
$env:AGRIREACH_CONSENT = '1'
$env:AGRIREACH_RETENTION_DAYS = '90'
$env:AGRIREACH_MEDIA_DIR = 'data/pilot-media'
$env:AGRIREACH_OUTBOX = 'data/pilot-outbox'
$env:LLM_BASE_URL = ''
$env:LLM_MODEL = ''
$env:LLM_API_KEY = ''
$env:AGRIREACH_JUDGE_BASE_URL = ''
$env:AGRIREACH_JUDGE_API_KEY = ''
```

Initialize and verify a new pilot database (stop both services before migrations on an existing database):

```powershell
. .\pilot-env.ps1
.\.venv\Scripts\python.exe -m agrireach.migrations data/pilot.db
.\.venv\Scripts\python.exe -m agrireach.migrations data/pilot.db --verify-only
.\.venv\Scripts\python.exe scripts/add_officer.py 'Pilot Officer'
```

The last command prints a private token once. Give it directly to the second participant; never commit or screenshot it. The database stores a hash. Re-running with the same officer name rotates the token and invalidates the old one. There is no public self-registration: this administrator command registers the officer.

Terminal 1, from the repository root:

```powershell
. .\pilot-env.ps1
.\.venv\Scripts\python.exe -m uvicorn agrireach.api:app --host 127.0.0.1 --port 8000 --ws none --no-access-log
```

Terminal 2, from the same repository root:

```powershell
. .\pilot-env.ps1
.\.venv\Scripts\python.exe -m streamlit run src/agrireach/ui.py --server.address 127.0.0.1 --server.port 8501 --server.headless true
```

Open http://127.0.0.1:8501. The second participant selects the officer tab and enters the private token in **Officer sign in token**. No password or email is required. Keep the farmer browser session separate. On one PC both people use loopback; a second physical PC is outside this pilot scope.

## Repeatable scenario and acceptance record

Record commit (`git rev-parse HEAD`), Python version, date, operator initials, case IDs and pass/fail; omit tokens and personal data. Use `sim:pilot-1`, never real phone numbers. Keep the services running. From a third PowerShell terminal:

```powershell
. .\pilot-env.ps1
.\.venv\Scripts\python.exe -m agrireach.channels.simulator ask --sender sim:pilot-1 --text 'How do I reach an extension officer about maize in Tamale?'
.\.venv\Scripts\python.exe -m agrireach.channels.simulator ask --sender sim:pilot-1 --text 'YES'
.\.venv\Scripts\python.exe -m agrireach.channels.simulator outbox --sender sim:pilot-1
```

- [ ] First question produces consent prompt only. YES files a case; only acknowledgement, no advisory, appears in outbox.
- [ ] Officer sees question, evidence, draft mode, proposed text and safety findings. Offline stub is clearly labelled. No claim of model quality is made.
- [ ] Officer reviews the evidence and exact farmer text. For a deterministic offline approval, use the fixed referral: `Consult your local AEA before choosing or applying a pesticide.` If held, inspect the finding and revise; never bypass validation.
- [ ] Officer confirms review and approves. Exactly the approved response appears in simulator outbox, with immutable approval/assessment evidence. Releasing again produces no second advisory.
- [ ] Submit another question under `sim:pilot-2`, answer YES, reject it with a reason in the officer tab. No advisory appears for the rejected case.
- [ ] Blank/invalid officer token cannot read the queue or decide. Signed-out farmer cannot see officer drafts.
- [ ] Try approving `Spray pesticide twice every week.` Safety blocks or holds it; no advisory is sent.
- [ ] Two officer sessions load the same revision; after one changes it, the stale decision is refused and requires reload.
- [ ] Submit another question, consent, then send STOP before approval. Contact is removed; approval/release cannot send to that recipient. Existing approval evidence is preserved.
- [ ] Restart backend and UI. Cases, approvals and outbox persist; restarting does not resend advisories.
- [ ] Run the deterministic failure tests below. Duplicate provider webhooks, crash boundaries and delivery ambiguity use fakes, never provider credentials.

The proposed referral must pass the actual safety gate. If it does not, record NO GO and the structured finding; do not alter evidence or disable checks to complete the scenario.

```powershell
$env:PYTHONPATH = 'tests;src'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts/replay_safety.py --strict
.\.venv\Scripts\python.exe scripts/verify_legacy_migration.py
$env:PYTHONPATH = 'src'
.\.venv\Scripts\python.exe scripts/reconcile_inbox.py
```

Recovery reports counts by default. Stop application writers before applying stale-claim reconciliation:

```powershell
.\.venv\Scripts\python.exe scripts/reconcile_inbox.py --apply --minutes 30
```

It marks stale processing uncertain and never replays or sends. Pending work has not been claimed; failed work has an explicit reason; completed work has a case or classified system outcome; uncertain work requires evidence review. A linked case alone does not prove ACK or delivery completed. Inspect approval, delivery job and attempt evidence locally. Never reset unknown/sending deliveries or uncertain inbound rows to pending to force a retry.

## Troubleshooting and shutdown

Use Ctrl+C in both servers before backups or migrations. Copy the stopped pilot database and outbox to a private local backup; never restore over newer approval evidence. Preserve existing migration files and ledger checksums. Do not delete the database as a repair.

If imports fail, verify repository root and dot-source `pilot-env.ps1`. If UI cannot connect, check `Invoke-RestMethod http://127.0.0.1:8000/health` and port 8000. If ports are occupied, stop the previous instance. If sign-in fails, verify the same database path in both terminals and rotate the token privately if necessary. A locked database means another writer may be running: stop writers and retry, never edit the ledger. A 409 means reload stale data; 422 means revise/reject held content; 503 may mean assessment unavailable. Arbitrary prose can require a live judge and intentionally cannot be approved offline. Voice dependencies and model assets are not part of this text pilot.

STOP revokes persisted pending inbox work and prevents a durable worker from later attaching a contact. An in-progress provider call cannot be cancelled, and there remains a final contact-check-to-send race. System prompts and simulator intake do not have full durable inbox coverage. STOP erases consent rather than maintaining a permanent suppression list; a new later message can initiate consent again. Controlled testing requires serialized simulator intake and STOP before delivery; concurrency guarantees are tested with durable adapter fakes. Do not enable external messaging based on this pilot.
