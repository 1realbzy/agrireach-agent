> Current safety branch, 26 October 2026: approval uses S1–S3, immutable evidence, single use acknowledgements and atomic delivery claims. See [the safety walkthrough](docs/safety-architecture.md) and [QA remediation progress](docs/remediation-progress.md). Independent acceptance remains pending.

# ARCHITECTURE.md

**Status (26 Oct 2026):** QA remediation on `work/safety-hardening`. Drafting supports an OpenAI compatible endpoint or labelled offline stub mode. Deterministic complete source sentences and registered templates can be approved without a model. Other uncertain claims require a successful judge assessment or additional review. Nothing is deployed. Historical measurements remain in [EVALS.md](EVALS.md).

## Agent shape

AgriReach is a draft-and-escalate agent for Ghanaian extension officers. A farmer question arrives through the Streamlit UI, the FastAPI case API, WhatsApp, SMS (Africa's Talking) or a voice note. A LangGraph graph in `agent.py` runs six nodes:

| Node | What it does |
|---|---|
| `intake` | Detects crop (including Twi names such as *aburo*), place, district and language; decides whether to ask the farmer a clarifying question. |
| `clarify` | Files the clarifying question and stops. |
| `retrieve` | Calls MCP tools: corpus search, crop calendar, zone planting windows for the farmer's agroecological zone, recent rainfall when a district is known. |
| `check_sources` | Uses the borrowed fetch server to confirm each cited source page is reachable and about the crop. |
| `write` | Drafts the officer advisory with the model, then runs the code checks (below). One regeneration with the checks' feedback; if it still fails, or the judge can't run, the officer gets the verbatim passages and the case is urgent. |
| `file_case` | Adds officer-only notes (zone caution, season date against the cited windows, rainfall record), proposes the farmer-facing text, sets priority and files the case through the MCP action tool. |

Routing and the decision to escalate are rule-based; the model drafts the advisory and the farmer text, and a second model judges it. The agent stops at the officer queue. No advisory, input order or credit action is sent autonomously.

## MCP servers: built versus borrowed

**Built (`mcp_server.py`, Agricultural Knowledge MCP server):** a local server over a curated, licence-checked corpus (`data/knowledge.json`, see [docs/data-sources.md](docs/data-sources.md)) and the case database.

| Tool | Role |
|---|---|
| `search_guidance` | Ranked passages with source identifiers |
| `get_crop_calendar` | Season and region calendar guidance |
| `get_zone_planting_guidance` | MoFA and IITA planting windows for the farmer's agroecological zone |
| `get_recent_rainfall` | Cached daily rainfall for a district (Open-Meteo by default), cited as a record; never says whether the rains have started |
| `retrieve_reference` | Fetch one passage by id (never invent) |
| `create_or_update_case` | **Action tool:** writes draft or pending-review cases only; approval and release are reserved for the officer |

**Borrowed:** `mcp-server-fetch`, the reference fetch server from the modelcontextprotocol project, used by `check_sources`. It is a maintained, sandboxed HTTP fetch server, better than writing our own HTTP tool.

## Checks before an officer sees a draft

- **Citation check** (`citation_check.py`): every date, number and limit ("up to", "not deeper than") must appear in the passage the sentence cites; where sources differ, each figure must be attributed to its own source.
- **Claim check** (`claim_check.py`): sentences without figures get code checks (named sources, agreement claims, shared content words), including uncited sentences and lines addressed to the officer.
- **Judge** (`judge.py`): a second model reads every sentence of a model draft against its passages. Always on, and it **fails closed**: no verdict means the draft is rejected. Place names the passages don't contain are masked, because zone fit is decided in code.
- **Farmer proposal** (`farmer_reply.py`): the agent proposes text for officer review. Failed model proposals fall back to labelled source based proposals. This proposal path does not authorise release.
- **Approval safety** (`safety_gate.py`, `approval.py`): S1 requires applicable source safeguards, S2 blocks bounded harmful reversals, and S3 holds unsupported chemical/material instructions. Unknown source topics retain S1. Registered templates share one policy across deterministic checks and model exemptions. SMS length is enforced without truncation. Critical holds cannot be acknowledged away. Noncritical model warnings require a case, officer, revision, exact text and warning identity bound challenge, valid for ten minutes and single use. HTTP 409 represents this application workflow conflict; 428 is reserved for HTTP preconditions and is not used.

## Human gate, delivery and logging

Officers sign in with a bearer token stored only as a SHA256 hash. Approval requires explicit farmer text, confirmation, current revision and an unchanged assessment context. Assessment occurs before the write lock; persistence rechecks the context under BEGIN IMMEDIATE and commits approval and audit evidence atomically. Release validates the immutable approval and creates a unique delivery job. Channel transport follows an atomic claim; provider acceptance is recorded separately from release. Definite preflight refusal can be retried or rejected. Ambiguous/interrupted sends remain unknown until an authenticated officer records verified provider evidence. Reconciliation never sends. Concurrent claims and repeated releases cannot send the same job twice within the tested workflow. Web cases expose only released approval text. Legacy published text remains labelled legacy_unvalidated and cannot be newly sent. Simulator HTTP routes remain disabled by default.

Logged in SQLite `tool_log`: every tool call with redacted inputs and outputs, source ids, case id, priority, check and judge results, officer identity, decisions, warnings and delivery outcomes. Every farmer-text proposal (agent or officer re-propose) writes a `farmer_text_proposal` entry: the path (model, rule or officer), why a model SMS was rejected or failed, the sentences dropped to fit, and `draft_mode` / `offline_draft`, so an offline stub run can be told apart from a real model run. Every model call, including failed ones, writes a `model_usage` cost row. A channel case (SMS or voice note) is queued in the same transaction as the farmer's contact, so it is never queued without one. Model calls run off the event loop, so one farmer's slow call can't time out another farmer's tool calls. Sender numbers are masked. The model never executes commands; tools are allowlisted and schema-validated.

## Why this shape

Extension officers already sit between information and households. The agent compresses retrieval and drafting; the officer keeps accountability. Every check fails towards the officer, never towards the farmer.
