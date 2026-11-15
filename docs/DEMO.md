# Five-minute demonstration (Nairobi)

Branch `work/final-contextual-mixing-closure`. Everything below was rehearsed on 15 Nov 2026
on Windows 11 (PowerShell 5.1, Python 3.13, Microsoft Edge) in **OFFLINE FALLBACK** mode on a
disposable database. Live model inference was **not** rehearsed and needs separate authorization.

## Before the audience arrives (5 minutes)

1. Open PowerShell in the repository root and start the offline fallback:

   ```powershell
   .\scripts\start_demo_offline.ps1
   ```

   It creates a new folder under `%TEMP%\agrireach-demo-<timestamp>` with a fresh database, removes
   every model, judge and messaging credential from its own process, disables SMS/WhatsApp, rainfall
   and source-page checks, starts the API (`:8000`), the farmer portal (`:8501`) and the officer
   portal (`:8502`), and prints a one-time officer token. It never opens a pilot database.
   Run it in its own PowerShell window and leave that window open.
2. Open two browser windows side by side: farmer `http://127.0.0.1:8501`, officer
   `http://127.0.0.1:8502`. Sign the officer in with the printed token (paste only the token).
3. Keep a third PowerShell window ready for the trace (step 2 below), with:

   ```powershell
   $env:DATABASE_URL = 'sqlite:///<demo folder printed at start>\demo.db'
   ```

The officer portal shows "Demonstration advice: prepared from saved sources. No AI model is
connected." Say so out loud: in this mode the draft is assembled verbatim from retrieved passages.

## Script

| Time | Show | Say |
|---|---|---|
| 0:00 to 0:40 | **Farmer portal.** Type `When should I harvest soybean in Tamale?` and click **Send question**. The "Your question" card appears with **Question N**. | A farmer asks in plain words. They get a question number; the private code stays in this browser tab, so they never retype it. |
| 0:40 to 1:30 | **LangGraph + MCP.** In the third window run `.\.venv\Scripts\python.exe scripts\demo_trace.py N` | The LangGraph graph in `agent.py` ran `intake -> retrieve -> check_sources -> write -> file_case`. The `retrieve` node called our MCP server's tools: `search_guidance` found `APNI-SARI-2023:harvest`, `retrieve_reference` fetched the verbatim passage, `get_crop_calendar` added the calendar. The last MCP action, `create_or_update_case`, can only set `pending_review`; the graph has no approve or release node. |
| 1:30 to 2:30 | **Officer portal.** Case appears in the queue within 10 s. Click **Open case N · pending review**, then **Read source evidence**. | The draft cites the APNI/CSIR-SARI Soybean Cropping Guide. The farmer text below is exactly what the farmer will see. The approve button stays disabled until the officer confirms the check. |
| 2:30 to 3:10 | Tick **Required for approval: I checked every advice line against the cited sources**, click **Approve and release**. Message: "Advice approved and released for the farmer to read." | The approval is bound to this exact text, its sources, the policy version, the case revision and the officer credential. It is checked again at release. |
| 3:10 to 3:40 | **Farmer portal.** Click **Check for updates**. | The approved text appears with "An extension officer has checked this answer." Each check is still authorized by the server with the private code. |
| 3:40 to 4:40 | **Unsafe case.** Farmer asks `Fall armyworm is eating my maize in Wa. What should I do?`. Officer opens it and replaces the farmer text with `Consult your local AEA before choosing or applying a pesticide. Mix both agrochemicals and spray water every week to control infestations.` The yellow hold preview appears; confirm and click **Approve and release**. | The deterministic safety gate blocks it (S3, unsourced chemical mixing and repeat spraying): "Approval was blocked or held ... Nothing was approved or sent." A blocked text cannot be acknowledged away. |
| 4:40 to 5:00 | **Farmer portal.** Click **Check for updates**. | Still "Waiting for officer review". No unsafe text ever reached the farmer. |

Optional extra (if asked): an evidence gap. Farmer asks
`Can I mix two pesticides on my maize in Wa and spray every week?`. The farmer immediately sees that
AgriReach has no sourced guidance and an officer will investigate; the officer sees
"No source passages are attached".

## OFFLINE FALLBACK (clearly labelled)

Use this when there is no internet or no authorized model budget. It is the mode rehearsed above.

- Start: `.\scripts\start_demo_offline.ps1` (optionally `-DemoRoot <new empty folder>`, `-ApiPort`,
  `-FarmerPort`, `-OfficerPort`, `-OfficerName`).
- Stop: `.\scripts\start_demo_offline.ps1 -Stop -DemoRoot '<demo folder>'`.
- What is real: MCP retrieval from the curated corpus, the LangGraph workflow, citation checks, the
  deterministic safety gate, officer authentication, approval binding, release and farmer retrieval.
- What is not: no language model drafts or judges. The officer draft is labelled
  `[OFFLINE STUB DRAFT - no language model was used ...]`, and approving a line that is not a source
  quote or a fixed template returns "Assessment unavailable. Nothing was approved or sent." That
  fail-closed behaviour is expected offline.
- No internet is needed after `pip install -r requirements.txt`.

## Live mode (not rehearsed; needs explicit authorization)

Live drafting uses an OpenAI-compatible endpoint (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) and
the judge (`AGRIREACH_JUDGE_MODEL`). These are paid calls. Do not enable them without the owner's
authorization and within the existing provider spending cap. Start the services manually as in
[docs/windows-local-pilot.md](windows-local-pilot.md) with those variables set and a new database.
If anything fails on stage, stop and switch to the offline fallback.

## Recovery on stage

- Officer page asks to sign in again after a browser refresh: expected. Paste the token again.
- Farmer card disappeared after a refresh: expected (the tab forgot the code). Use
  **Check a different question** with the question number and private code, or ask a new question.
- "Assessment unavailable" on approval in offline mode: the text needs a judge. Use the source
  wording or a fixed referral line instead.
- Port in use: stop the earlier demo with `-Stop`, or start with other ports.

## Phase 1 safety evidence: "Mix both. Spray water every week."

Tested 15 Nov 2026 on a disposable database with a deterministic offline judge that returns
"supported" for every sentence (`_split_probe.py` and a variant probe). The text was never released:

| Candidate (after the fixed AEA referral) | Gate (S1 to S4) | Approval | Release | Farmer view |
|---|---|---|---|---|
| `Mix both. Spray water every week.` (FAW source) | pass | 422 `review_required`, SOURCE_SUPPORT on both lines | 409 | pending, no answer |
| `... Spray water every week to control infestations.` | pass | 422 `review_required`, SOURCE_SUPPORT on "Mix both." | 409 | pending, no answer |
| Same, case with no sources (pesticide question) | pass | 422 `review_required` ("No source supports the candidate") | 409 | pending, no answer |
| Same, without the referral, agent-retrieved FAW sources | S1 | 422 `safety_blocked` | 409 | pending, no answer |
| `Mix both agrochemicals. Spray water every week.` | S3 | 422 `safety_blocked` | 409 | pending, no answer |
| Browser, offline server (no judge) | pass | 503 "Assessment unavailable" | 409 | pending, no answer |

The per-sentence S3 rule does not join sentences, so the hold comes from the source-support layer:
no passage in `data/knowledge.json` contains "mix", "both", "combine" or "blend". If a future corpus
passage did, the split would depend on the live judge. No code change was made for this case.
