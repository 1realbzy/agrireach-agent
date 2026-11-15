# AgriReach codebase walkthrough

Checked against branch `work/final-contextual-mixing-closure` on 15 Nov 2026. File and function
names below are the ones in `src/agrireach/`. Where this page and the code disagree, the code wins.

## 1. The idea in one paragraph

A farmer asks a question. A LangGraph agent gathers evidence from a curated corpus through our own
MCP server, drafts an officer-facing advisory and a short farmer-facing text, checks every figure
and claim against the cited passages, and files the case as `pending_review`. Nothing goes to the
farmer until a named extension officer approves the exact farmer text, that text passes a
deterministic safety gate plus source checks, and the approval is re-validated at release.
Every check fails towards the officer, never towards the farmer.

```text
farmer portal / API / simulator
  -> api.ask() -> agent.run()  [LangGraph: intake -> clarify | retrieve -> check_sources -> write -> file_case]
       -> MCP server (mcp_server.py) tools over stdio; fetch MCP server for source reachability
  -> SQLite case (pending_review) -> officer portal queue
  -> officer decision -> approval.decide() -> assess_candidate() -> safety_gate.assess() + source checks
  -> immutable approval -> approval.release() -> validated_approval() -> farmer view / channel delivery
```

## 2. Repository structure and entrypoints

| Path | Role |
|---|---|
| `src/agrireach/api.py` | FastAPI app (`uvicorn agrireach.api:app`). The only process that should write cases. |
| `src/agrireach/farmer_ui.py`, `officer_ui.py` | Streamlit entrypoints for the two portals (ports 8501/8502). Both call `ui.main(role)`. |
| `src/agrireach/ui.py`, `ui_feedback.py` | Shared Streamlit screens (`farmer_screen()`, `officer_screen()`) and API-status-to-message mapping (`feedback()`). |
| `src/agrireach/agent.py` | LangGraph agent (`build_graph()`, `run()`); CLI: `python -m agrireach.agent "question"`. |
| `src/agrireach/mcp_server.py` | Our MCP server (`python -m agrireach.mcp_server`, FastMCP over stdio). |
| `src/agrireach/mcp_transport.py` | Wrapper around the MCP SDK `stdio_client` that drains shutdown cleanly. |
| `src/agrireach/knowledge.py`, `data/knowledge.json` | Curated verbatim passages (42) with source metadata; `search()`, `reference()`, `calendar()`. |
| `src/agrireach/llm.py`, `judge.py`, `farmer_reply.py` | Drafting model or offline stub, judge model, farmer-text proposal. |
| `src/agrireach/citation_check.py`, `claim_check.py` | Code checks on figures and claims. |
| `src/agrireach/safety_gate.py`, `instruction_policy.py`, `relevance.py` | Deterministic approval gate. |
| `src/agrireach/approval.py`, `delivery.py`, `acknowledgement.py` | Approval binding, release, delivery jobs, question acknowledgements. |
| `src/agrireach/db.py`, `migrations.py` | SQLite store and versioned schema ledger. |
| `src/agrireach/channels/` | Simulator, SMS (Africa's Talking, mNotify), WhatsApp adapters, speech, retention. Off by default. |
| `scripts/` | Operator tools: `add_officer.py`, `start_demo_offline.ps1`, `demo_trace.py`, `replay_safety.py`, `start_pilot_ui.ps1`, browser verifiers. |
| `tests/` | Offline pytest suite (stub model, fake judges, temporary databases). |

## 3. FastAPI endpoints (`api.py`)

Farmer side (no login; a per-case secret instead):

| Endpoint | Function | Notes |
|---|---|---|
| `POST /ask` | `ask()` | Runs the agent, then `db.issue_farmer_case_token()` and returns `case_id`, a random `access_token`, the status, any clarification, and an `evidence_gap` flag. Never returns the draft. |
| `POST /farmer/cases/{id}/supplement` | `supplement()` | The farmer's answer to a clarifying question; needs `X-Case-Access-Token` and `expected_revision`. |
| `GET /farmer/cases/{id}` | `farmer_view()` | Needs `X-Case-Access-Token`; wrong or missing code returns 404 (case numbers are sequential, so the number alone proves nothing). Returns `answer` only for a released case whose approval still passes `validated_approval()`. |
| `GET /health` | `health()` | `{"ok": true, "draft_mode": "stub" | "llm"}`. |

Officer side (all use `Depends(current_officer)`: `Authorization: Bearer <token>`, hashed lookup in `officers`):
`GET /officer/queue`, `GET /officer/cases`, `GET /officer/cases/{id}` (adds the case `log`),
`POST /officer/cases/{id}/assess` (read-only check of a farmer text), `POST /officer/cases/{id}/farmer-draft`
(re-propose farmer text), `POST /officer/cases/{id}/decision` (`decide()`: approve, edit_approve,
reject, request_info), `POST /cases/{id}/release` (`release()`), `POST /officer/cases/{id}/reopen`,
`POST /officer/cases/{id}/sms-check`, `POST /officer/cases/{id}/voice-preview`, delivery and
acknowledgement status/reconciliation routes, and voice/audio routes.

Simulator (only when `AGRIREACH_SIMULATOR=1`, enforced by `_simulator_enabled()`):
`POST /channels/simulator/inbound`, `GET /channels/simulator/outbox`. The outbox is unauthenticated,
which is why it is off by default and never for deployment.

Status codes the UI relies on: 401 bad officer token; 404 bad farmer code; 409 stale revision,
acknowledgement required, or release without a valid approval; 422 `review_required` or
`safety_blocked`; 503 `assessment_unavailable` (no judge verdict).

## 4. LangGraph nodes and transitions (`agent.py`)

`build_graph(tools)` wires a `StateGraph(S)`:

```text
intake --(clarification needed)--> clarify --> END
intake --(otherwise)-------------> retrieve -> check_sources -> write -> file_case -> END
```

- `intake()`: rule-based crop, place, language and risk detection (`clarification_gap()`,
  `_detect_region()`), opens a `draft` case through the MCP action tool, adds urgent reasons
  (Twi text, uncovered crop, contact request, chemical or pest terms).
- `clarify()`: files the clarifying question (for example "Which district or region is your farm
  in?") and stops. The farmer answers through `/supplement`, which re-runs the agent with the reply.
- `retrieve()`: MCP calls `search_guidance`, `retrieve_reference` for each hit,
  `get_zone_planting_guidance` (planting questions), `get_recent_rainfall` (planting/top-dressing),
  `get_crop_calendar`; fits passages to the farmer's zone (`_fit_to_zone()`), detects source
  conflicts, and records "no grounded evidence found in corpus" when nothing matches.
- `check_sources()`: optional reachability check of cited source pages through the third-party
  `mcp-server-fetch` (off with `AGRIREACH_SOURCE_CHECK=0`).
- `write()`: `llm.draft()` (model) or `llm.stub_draft()` (offline, verbatim quotes with
  `STUB_LABEL`), then `citation_check.check_draft()` and `claim_check.check_claims()`. One
  regeneration with the problems; if it still fails, the officer gets the verbatim passages and the
  case is urgent.
- `file_case()`: proposes the farmer text (`farmer_reply.propose()`), adds officer-only facts, and
  files `pending_review` through `create_or_update_case`.

Why a graph: routing is explicit and testable, the model only words text, and there is
deliberately no node that can approve or release. `run()` / `_invoke()` open the MCP sessions
(`_server_params()`, `Tools`) and record model usage (`_log_usage()`).

## 5. MCP server and tool calls (`mcp_server.py`)

`FastMCP("agrireach-knowledge")` exposes: `search_guidance(query, crop, region)`,
`get_crop_calendar(crop, region)`, `get_zone_planting_guidance(crop, place, season)`,
`get_recent_rainfall(district, days, threshold_mm)`, `retrieve_reference(passage_id)` (read tools)
and `create_or_update_case(status, ...)` (the only acting tool; `db.agent_upsert_case()` accepts
only `draft` or `pending_review`). The agent is the MCP client: `agent.Tools.call()` calls a tool
with a timeout (`MCP_TIMEOUT`, default 20 s) and turns tool errors into exceptions, which the graph
records as "tool error during retrieval" rather than guessing. Every tool call writes a `tool_log`
row. Read-tool rows have no case id; `scripts/demo_trace.py <case>` shows the window of calls for
one case.

Why MCP: the corpus and the case store sit behind a narrow, schema-validated tool surface, the
same surface an external MCP client would see, and the action tool cannot express approval.

## 6. Knowledge retrieval and sources (`knowledge.py`, `zones.py`, `rainfall.py`)

`data/knowledge.json` holds 42 verbatim passages from APNI/CSIR-SARI 2023 soybean and maize guides,
IITA guides, the MoFA Maize Production Guide and Agbetiameh et al. 2018 (licences in
`docs/data-sources.md`). `knowledge.search()` stems words, scopes by crop and region, and is
conflict-complete (`claim_keys()`): if one source's passage on a claim is returned, the other
sources' passages on that claim are too, so ranking cannot hide a disagreement. `reference()`
returns one passage by id; the UI shows sources by title and page (`ui.source_name()`). Coverage is
soybean and maize only; other crops become officer-only evidence-gap cases.

## 7. Language model integration (`llm.py`, `farmer_reply.py`)

`llm.mode()` is `llm` only when `LLM_BASE_URL` and `LLM_MODEL` are set, otherwise `stub`.
`llm.draft()` calls an OpenAI-compatible endpoint (`provider_client()`, `create()`), with a
per-request provider attempt budget (`reserve_provider_attempt()`, `AGRIREACH_REQUEST_BUDGET`),
token caps (`MAX_TOKENS`) and cost rows (`record_usage()`, `log_usage()`). `farmer_reply.propose()`
builds the farmer text: a rule-based rewrite (`rule_rewrite()`) or the model (`_llm_rewrite()`),
then keeps required safety lines (`ensure_safety_line()`) and the SMS length limit. The model never
decides routing, approval or release.

## 8. Citation checks and judging (`citation_check.py`, `claim_check.py`, `judge.py`)

- `citation_check.check_draft()`: every number, unit, date and limit ("up to", "not deeper than",
  "at least") must appear in the passage the sentence cites (`extract_figures()`, `_matches()`);
  conflicting sources must each keep their own citation.
- `claim_check.check_claims()`: sentences without figures: a named source must be cited, agreement
  claims need two backing sources, a cited sentence must share content words with its passage, and
  everything else goes to the judge.
- `judge.judge()`: a second model (`AGRIREACH_JUDGE_MODEL`, default
  `meta-llama/llama-3.3-70b-instruct`) returns per-sentence verdicts; `parse()` is strict and the
  judge fails closed. Offline there is no judge, so judged lines become `assessment_unavailable`.

## 9. Safety gate (`safety_gate.py`, `instruction_policy.py`, `relevance.py`)

`safety_gate.assess(text, passages, question=...)` returns an `Assessment` with `Finding`s.
`POLICY_VERSION = "chemical-5"`. Lines copied from a cited passage or matching a fixed template
(`REFERRALS`, `PROTECTIVE`, `NO_ADVICE`) pass on provenance.

- **S1**: a cited chemical passage (registered in `SOURCE_FINGERPRINTS`, topic-checked by
  `applicable()`) requires its AEA consultation line or a fixed referral.
- **S2**: a line that steers away from the officer or reverses label/glove advice
  (`instruction_policy.skips_officer()`).
- **S3**: unsourced products, doses, vague materials, things put on plants, cure claims
  (`unsourced_input()`), repeat applications (`REPEAT`), spraying, and chemical mixing:
  `_MIX_PESTICIDE`, generic "products" in chemical context (`_product_instruction()`), and
  noun-free mix-and-apply in chemical context (`_affirmative_mix_and_apply()`); a plain ban
  ("Never mix pesticides.") passes via `_reliable_mix_prohibition()`. S3 is per sentence.
- **S4**: burning without a source mentioning it (`burns_land()`).
- **LANGUAGE**, **RELEVANCE** (`relevance.classify()`: a chemical referral that does not answer a
  harvest, planting or storage question is held) and evidence-gap handling.

Outcomes: `pass`, `acknowledgement_required`, `assessment_unavailable`, `review_required`,
`safety_blocked`; the last two cannot be acknowledged.

## 10. Officer approval and revision integrity (`approval.py`, `db.py`)

- Officers authenticate with tokens from `scripts/add_officer.py`; only the SHA-256 is stored
  (`db.add_officer()`, `officer_for_token()`). A farmer access code cannot act as an officer token.
- `approval.decide()` requires a named officer, a known decision and `expected_revision` equal to
  the case revision. `context()` snapshots the case, full source texts, contact and policy;
  `assess_candidate()` runs the gate and source checks (SOURCE_CONFLICT, SOURCE_FIGURES,
  SOURCE_SUPPORT, judge).
- Inside `BEGIN IMMEDIATE` it re-reads the case and the officer credential; any change raises
  "stale_revision". It writes `advisory_submissions` and `safety_assessments` even when blocked,
  then, only for `pass` (or a valid single-use acknowledgement), writes an `approvals` row whose
  payload holds farmer text, officer text, context, assessment and a `binding` fingerprint over all
  of them plus the credential hash. The case revision is incremented.
- `validated_approval()` at release and at every farmer view recomputes the context and payload
  fingerprints, re-runs `safety_gate.assess()` and the evidence-gap rule. Any change needs a fresh
  approval. `release()` is idempotent and never resends an accepted delivery.

## 11. SQLite persistence (`db.py`, `migrations.py`)

`db.connect()` uses `DATABASE_URL` (default `sqlite:///agrireach.db`) and runs
`migrations.ensure_schema()`, which takes a verified backup before upgrading an existing file.
Main tables: `cases` (with a `revision` trigger), `officers`, `tool_log`, `advisory_submissions`,
`safety_assessments`, `approvals`, `acknowledgement_challenges`, `audit_events`, `delivery_jobs`,
`delivery_attempts`, `farmer_case_access`, `channel_inbox`, `farmer_sms_contacts`,
`acknowledgement_jobs`, `acknowledgement_attempts`. Database triggers make approvals,
submissions, assessments and audit events immutable (`IMMUTABLE_TRIGGERS`).
`schema_migrations` is a checksum ledger: v1 base evidence tables, v2 approval/delivery storage,
v3 farmer case access tokens, v4 durable inbound ledger, v5 sender-scoped erasure and
reconciliation reasons, v6 SMS consent and acknowledgement storage. Checksums v1 to v6 were
re-verified on 15 Nov 2026 (`migrations._valid_ledgers()`).

## 12. Farmer interface (`ui.py: farmer_screen()`)

Section 1 sends the question (`POST /ask`) with optional, unchecked-by-default SMS consent.
Section 2, "Your question", keeps the active question number and private code in Streamlit
session state for that browser tab only and offers **Check for updates**, which calls
`GET /farmer/cases/{id}` with the code in a header each time (`_check_case()`). **Forget this
question on this device** clears it. **Check a different question** is the manual lookup. A
clarifying question shows an "Add the missing detail" form bound to the case revision
(`_bind_supplement()`). The farmer never sees drafts, sources or officer notes.

The officer portal (`officer_screen()`, `render_case()`) shows the queue (refreshing every
10 s), the cited draft with numbered sources, the farmer text with a live hold preview
(`show_holds()` via `/assess`), and decision controls that stay disabled until the officer confirms.

## 13. Simulated messaging (`channels/`)

`channels/simulator.py` is a farmer phone simulated on disk: sender ids must look like
`sim:<name>` (so no real number can be typed), and sends append to `<AGRIREACH_OUTBOX>/outbox.jsonl`.
`channels/service.py` handles inbound messages (consent prompt, STOP erasure, durable inbox) and
`deliver()` sends approved text through configured channels with atomic delivery claims
(`delivery.claim()`). An uncertain send becomes `unknown` and needs officer reconciliation; it is
never retried automatically. SMS (`sms.py`, `mnotify.py`) and WhatsApp are disabled unless
explicitly configured (`SMS_ENABLED=1`, `WHATSAPP_ENABLED=1`, `MNOTIFY_SMS_MODE=live` with valid
settings); the demo launcher removes those settings.
