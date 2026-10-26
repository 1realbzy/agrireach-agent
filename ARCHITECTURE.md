# AgriReach architecture

This is the one architecture document. It describes the code on `main` as of 26 Oct 2026. Nothing is deployed; the app runs locally. Measured results are in [EVALS.md](EVALS.md), sources and licences in [docs/data-sources.md](docs/data-sources.md), and case statuses in [docs/workflow.md](docs/workflow.md).

```text
farmer (UI, API, voice-note simulator, WhatsApp/SMS adapters)
  -> LangGraph agent: intake -> retrieve (MCP) -> check_sources (fetch MCP) -> write (draft + checks) -> file_case
  -> officer queue (urgent or routine) -> officer edits and approves the exact farmer text
  -> approval safety gate -> immutable approval -> release -> delivery
```

`docs/architecture.png` is the original proposed design, drawn before the build. It is kept for the record; this page describes what was built.

## Agent shape

AgriReach is a draft-and-escalate agent for Ghanaian extension officers. A farmer question arrives through the Streamlit UI, the FastAPI case API, the local voice-note simulator, or the WhatsApp and SMS adapters (code only, off by default). A LangGraph graph in `agent.py` runs six nodes:

| Node | What it does |
|---|---|
| `intake` | Detects crop (including Twi names such as *aburo*), place, district and language, and decides whether to ask the farmer a clarifying question. Rule-based. |
| `clarify` | Files the clarifying question and stops. |
| `retrieve` | Calls MCP tools: corpus search, crop calendar, zone planting windows for the farmer's agroecological zone, and recent rainfall for planting and top-dressing questions. |
| `check_sources` | Uses the borrowed fetch MCP server to confirm each cited source page is reachable and mentions the crop. |
| `write` | Drafts the officer advisory with the model (or the offline stub, which quotes passages verbatim), then runs the citation and claim checks. One regeneration with the checks' feedback; if it still fails, or the judge can't run, the officer gets the verbatim passages and the case is urgent. |
| `file_case` | Adds officer-only notes (zone caution, received date against the cited windows, rainfall record), proposes the farmer-facing text, sets priority and files the case through the MCP action tool. |

Routing and escalation are rule-based. The model only words the draft and the farmer text, and a second model judges them. The graph has no node that can approve or release.

## MCP servers: built and borrowed

**Built:** `mcp_server.py`, the Agricultural Knowledge MCP server (official Python SDK, FastMCP over stdio). It serves the curated, licence-checked corpus in `data/knowledge.json` and the case database. Every tool call is logged to `tool_log`.

| Tool | Returns | Safety rule |
|---|---|---|
| `search_guidance` | Ranked verbatim passages with source ids | Conflict-complete: if one source's passage on a claim is returned, every other source's passage on that claim is returned too |
| `get_crop_calendar` | Cited calendar activities | Empty when there is no local reference |
| `get_zone_planting_guidance` | The zone of a Ghana place (`data/zones.json`) and the MoFA and IITA planting-window rows for it | Read-only; an unknown place or crop returns no passages, never a guess |
| `get_recent_rainfall` | Last 30 days of daily rainfall for a district (Open-Meteo, CC BY 4.0), rain days, missing days, provider, licence and retrieval time | Read-only, cached for 6 hours; offline or an unknown district returns "rainfall unavailable"; never says onset has been reached |
| `retrieve_reference` | One passage and its source metadata | Errors on an unknown id; never invents a source |
| `create_or_update_case` | The case id and its `created_at` | **Action tool:** may set only `draft` or `pending_review`; approval is reserved for the officer |

**Borrowed:** `mcp-server-fetch`, the reference fetch server from the Model Context Protocol project, used by `check_sources`. It checks reachability, not agricultural accuracy. There is no weather-forecast tool.

Tool inputs are schema-validated, retrieved text is treated as data, and the model never executes commands.

## Checks on the officer draft

These run in the `write` node, before the officer sees the draft:

- **Citation check** (`citation_check.py`): every date, number and limit ("up to", "not deeper than", "at least") must appear in the passage the sentence cites. Where sources differ, each figure must carry its own source's citation.
- **Claim check** (`claim_check.py`): sentences without figures get code checks: a named source must be cited, "both sources agree" needs two sources that each back the sentence, and a cited sentence must share a content word with its passage.
- **Judge** (`judge.py`): a second model (`AGRIREACH_JUDGE_MODEL`, default `meta-llama/llama-3.3-70b-instruct`) reads each sentence of a model draft against its passages. It is always on (`judge.enabled()` returns `True`) and fails closed: no valid verdict means the draft is rejected. Place names the passages don't contain are masked, because zone fit is decided in code. Offline stub drafts quote passages verbatim and are not judged.

## Approval safety gate

When an officer approves, the exact farmer text goes through `approval.assess_candidate()`. It runs the deterministic gate in `safety_gate.assess()` first, then the source checks. `POLICY_VERSION` in `safety_gate.py` is `chemical-4`.

### Deterministic gate (`safety_gate.py`, `instruction_policy.py`)

Empty text is `safety_blocked` (TEXT). S1 and LANGUAGE look at the whole text. S2 to S4 check each line, except a line copied word for word from a cited passage or one of the fixed template lines (`REFERRALS`, `PROTECTIVE`, `NO_ADVICE`), which passes on provenance.

| Stop | What it catches | Outcome |
|---|---|---|
| **S1** chemical safeguard | A cited chemical passage applies, but the reply drops its AEA consultation line and has no fixed referral line. A source that is not registered in `SOURCE_FINGERPRINTS`, or whose text has changed, always keeps S1 on. A registered source that is off the question's topic is skipped. | `safety_blocked`; an unknown or changed chemical source is `review_required` |
| **S2** skips the officer or reverses safety advice | A mention of the AEA or extension officer that is not a plain referral ("Do not ask the AEA."), or a line that reverses label or glove advice (`skips_officer()`, plus the reversal pattern in `assess()`) | `safety_blocked` |
| **S3** unsourced input | A product or household chemical, a dose or rate, a vague thing applied ("Pour it on"), anything put on the plants, a cure claim (`unsourced_input()`), a repeat application (`REPEAT`), or a pesticide or spraying mention | `safety_blocked` if the line mentions a pesticide or spraying, otherwise `review_required` |
| **S4** burning | Advice to burn or set fire, unless the line says not to or a cited source mentions burning (`burns_land()`) | `review_required` |
| **LANGUAGE** | Text that is not English (for example Twi markers or a non-Latin script). The English rules can't read it, so a reviewer who reads the language must check it. | `review_required` |

`REPEAT` treats how often to apply as a dose: an apply, spray or treat word plus a repeat word ("twice", "every", "weekly", "again", "keep applying"), or "re-apply" or "second dose". "Once at X and once at Y" is a split dose and passes. It is a word list, so it misses some wordings and over-holds others; see the README Limitations.

### Source checks (`approval.py`)

`assess_candidate()` adds two whole-text checks to the gate's result:

- **SOURCE_CONFLICT**: the case's sources disagree and the text does not defer to the officer (the fixed "Your extension officer will confirm which to follow." line, with no figures). A `pass` becomes `review_required`.
- **CHANNEL_LENGTH**: an SMS case whose text won't fit. Nothing is cut. `safety_blocked`.

If the outcome is still `pass`, the next checks run on the lines that are not source quotes, templates, code-built caveats or a bare greeting (`GREETING`):

- **SOURCE_SUPPORT** (no sources): the case has no source. `review_required`.
- **SOURCE_FIGURES**: the citation check runs on those lines. A figure not in the sources gives `review_required`.
- **Judge and claim check**: the claim check runs with the judge. If the judge can't give a verdict, the outcome is `assessment_unavailable` (JUDGE_AVAILABILITY) and the officer can retry. Other problems are SOURCE_SUPPORT findings. They are `acknowledgement_required` only when every problem is a judge "not supported" verdict and none is critical. Critical means a chemical source, a food-safety question, a source conflict, or a how-to line (when, what, how much, how often). Otherwise the outcome is `review_required`.

`decide()` adds **VOICE_APPROVAL**: with text-to-speech on, the officer must preview and approve the exact spoken script, or the outcome is `review_required`.

In offline stub mode there is no judge, so approving a line that needs one returns `assessment_unavailable`.

### Outcomes

| Outcome | HTTP | What the officer can do |
|---|---|---|
| `pass` | 200 | The approval is recorded, released and delivered |
| `acknowledgement_required` | 409 | Acknowledge with the single-use token returned. It is bound to the case, text, officer credential and warning set, and expires after 10 minutes |
| `assessment_unavailable` | 503 | Retry the assessment, revise, reject or request info |
| `review_required` | 422 | Revise, reject or request info. It cannot be acknowledged |
| `safety_blocked` | 422 | Revise, reject or request info. It cannot be acknowledged |

A favourable judge verdict never overrides a deterministic hold.

## Officer approval binding (`approval.py`)

Officers sign in with a bearer token from `scripts/add_officer.py`; only its SHA-256 hash is stored. Approval needs the exact farmer text, the officer's confirmation that they checked it, and the current case revision.

1. `context()` snapshots the case, the full text of its sources, the farmer contact, `POLICY_VERSION` and the voice setting.
2. The assessment runs before any write lock, so a slow model call doesn't block other cases.
3. Inside `BEGIN IMMEDIATE`, the snapshot and the officer credential are checked again. If anything changed, the officer must reload.
4. The submission, the assessment and the approval are written together. The approval payload holds the farmer text, officer text, context, assessment and a binding fingerprint. Database triggers make approvals, submissions, assessments and audit events immutable.

## Delivery (`approval.release()`, `delivery.py`, `channels/`)

Release calls `validated_approval()`: the case revision, source text and policy version must still match the approval, and the deterministic gate is run again. Any change needs a fresh approval. Web cases then show the approved text at `GET /farmer/cases/{id}`. Channel cases (simulator, WhatsApp, SMS) get one delivery job per approval and channel. `delivery.claim()` reserves it atomically before any send, so two callers can't send the same job. A definite provider refusal is `definitely_failed` and can be retried. A send that is interrupted, or fails in an unexpected way, becomes `unknown` and is never retried automatically: an officer must first record verified provider evidence (`POST /officer/delivery-jobs/{id}/reconcile`), and reconciliation never sends. A farmer who sent STOP, or whose number was purged, is marked `undeliverable`.

## Logging and debugging

- `tool_log`: every tool call (redacted), check and judge result, officer decision and delivery outcome. Every farmer-text proposal writes a `farmer_text_proposal` entry with its path and `draft_mode`, so a stub run can be told apart from a model run. Every model call writes a `model_usage` cost row. Sender numbers are masked.
- To trace a case, follow `cases.id` to `advisory_submissions`, `safety_assessments`, `approvals` (exact approved text and snapshot), `delivery_jobs`, `delivery_attempts` and `audit_events`. Open the database read-only and don't copy tokens or contact numbers into logs.
- Never repair a fingerprint to force a release. A mismatch means the officer must approve again.
- Older engineering decisions are in [docs/safety-decisions.md](docs/safety-decisions.md). Dated evidence from earlier rounds is in [docs/evidence/](docs/evidence/README.md).

## Why this shape

Extension officers already sit between information and households. The agent speeds up retrieval and drafting, and the officer stays accountable. Every check fails towards the officer, never towards the farmer.
