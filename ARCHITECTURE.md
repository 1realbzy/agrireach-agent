# ARCHITECTURE.md

**Status (25 Oct 2026):** as built on branch `fix/review-findings` at `f5d5990` (local, the frozen version; the code is unchanged since `e79c43c`, and later commits only touch docs). Runs locally with the open-weights model `mistralai/mistral-small-3.2-24b-instruct` (drafting) and `meta-llama/llama-3.3-70b-instruct` (judge) via an OpenAI-compatible endpoint, or in a labelled offline stub mode. Nothing is deployed. Measured results are in [EVALS.md](EVALS.md); the original pre-build design is in [docs/architecture.md](docs/architecture.md).

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
- **Farmer text** (`farmer_reply.py`): every SMS sentence is checked against the case's own passages the same way. A model-written SMS that fails is replaced by a rule-based one; text the officer writes or keeps is warned about and logged (`approval_warning`), not blocked. Regulatory limits (ppb) never go to the farmer, the zone caveat and "your officer will confirm which to follow" are added in code, punctuation is kept SMS-plain, and over-length SMS is refused at approval.
- **Pesticide safety line** (`farmer_reply.ensure_safety_line`): when a case passage has a pesticide safety sentence (preferably the referral to the local AEA), it goes into the farmer SMS word for word, with its source named, right after the zone caveat. It is never reworded or shortened. A model SMS is never trimmed: if it no longer fits, the rule-based text is used, and that text drops only whole advice sentences, each of which is named to the officer. If the officer removes the source's own sentence, or replaces it with a different pesticide sentence, approval gives a warning (`drops_safety_line`). The officer still decides, so it is not blocked. See EVALS.md for the known limits.

## Human gate, delivery and logging

Officers sign in with a Bearer token (stored only as a sha256 hash). Approval requires `confirmed: true` and covers exactly the farmer text that will be sent; decisions are conditional updates, so two officers racing get one 200 and one 409. Case states: `pending_review` (or `needs_info`), then `approved`, then `released` when the channel accepted the text, or `not_delivered` (back in the officer queue with the reason) when a send fails, or `undeliverable` (final, listed in `GET /officer/cases?status=undeliverable`, not in the queue) when the farmer opted out or the number was removed by the retention purge. For a web-form case with no phone contact, `released` means the answer is readable at `/farmer/cases/{id}`. Full table: [docs/workflow.md](docs/workflow.md#case-statuses-as-built-25-oct-2026). The farmer sees nothing before release. The phone simulator routes return 404 unless `AGRIREACH_SIMULATOR=1` (local demo only).

Logged in SQLite `tool_log`: every tool call with redacted inputs and outputs, source ids, case id, priority, check and judge results, officer identity, decisions, warnings and delivery outcomes. Every farmer-text proposal (agent or officer re-propose) writes a `farmer_text_proposal` entry: the path (model, rule or officer), why a model SMS was rejected or failed, the sentences dropped to fit, and `draft_mode` / `offline_draft`, so an offline stub run can be told apart from a real model run. Every model call, including failed ones, writes a `model_usage` cost row. A channel case (SMS or voice note) is queued in the same transaction as the farmer's contact, so it is never queued without one. Model calls run off the event loop, so one farmer's slow call can't time out another farmer's tool calls. Sender numbers are masked. The model never executes commands; tools are allowlisted and schema-validated.

## Why this shape

Extension officers already sit between information and households. The agent compresses retrieval and drafting; the officer keeps accountability. Every check fails towards the officer, never towards the farmer.
