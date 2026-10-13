# ARCHITECTURE.md

**Status (13 Oct 2026):** built and tested in offline stub mode; LLM drafting not yet run (no key). See README status table.

## Agent shape

AgriReach is a draft-and-escalate agent for soybean extension support in Ghana. A farmer question enters through a Streamlit UI and FastAPI case API. A Python orchestration layer (LangGraph) interprets the request, asks for missing crop or location context when needed, calls MCP tools for evidence, drafts a sourced advisory, sets review priority (urgent or routine), and stops. A named extension officer must approve, edit, reject, or request more information before anything reaches a farmer. No advisory, input order, or credit action is sent autonomously.

## MCP servers: built versus borrowed

**Built (Agricultural Knowledge MCP server, working):** local server over a curated, licence-clear starter corpus and case operations.

| Tool | Role |
|---|---|
| `search_guidance` | Ranked passages with source identifiers |
| `get_crop_calendar` | Season and region calendar guidance |
| `retrieve_reference` | Fetch one reference by id (never invent) |
| `create_or_update_case` | Draft or pending-review case writes only; approval reserved for the officer |

At least one of these is an action tool (case create/update or draft advisory filing), not read-only lookup.

**Borrowed:** `mcp-server-fetch`, the reference fetch MCP server from the modelcontextprotocol project. The agent uses it to check that every cited source page is reachable and is about soybean before a case is queued. We used it because it is a maintained, sandboxed HTTP fetch server, which is better than writing our own HTTP tool in a five-day build.

## Human gate and logging

Every irreversible step (release to farmer) requires a named officer approval with timestamp. Logged (SQLite `tool_log`): tool name, inputs/outputs (redacted), source ids, case id, priority, officer identity, and decision. The LLM never executes arbitrary commands; tools are allowlisted and schema-validated.

## Why this shape

Extension officers already sit between signals and households. The agent compresses retrieval and drafting; the officer keeps accountability. Narrow soybean scope keeps the corpus and evals honest for the build window.
