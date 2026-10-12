# ARCHITECTURE.md

**Status:** one-page design note for the AgriReach submission. No application code exists yet. Selections that depend on the build (model, third-party MCP server, orchestration library) are marked planned.

## Agent shape

AgriReach is a draft-and-escalate agent for soybean extension support in Ghana. A farmer question enters through a Streamlit UI and FastAPI case API. A Python orchestration layer (planned: LangGraph or Pydantic AI) interprets the request, asks for missing crop or location context when needed, calls MCP tools for evidence, drafts a sourced advisory, sets review priority (urgent or routine), and stops. A named extension officer must approve, edit, reject, or request more information before anything reaches a farmer. No advisory, input order, or credit action is sent autonomously.

## MCP servers: built versus borrowed

**Built (Agricultural Knowledge MCP server, planned):** local server over a curated, licence-clear starter corpus and case operations.

| Tool | Role |
|---|---|
| `search_guidance` | Ranked passages with source identifiers |
| `get_crop_calendar` | Season and region calendar guidance |
| `retrieve_reference` | Fetch one reference by id (never invent) |
| `create_or_update_case` | Draft or pending-review case writes only; approval reserved for the officer |

At least one of these is an action tool (case create/update or draft advisory filing), not read-only lookup.

**Borrowed (planned during build):** one third-party MCP server (for example weather or filesystem) chosen because a maintained community or vendor server beats reimplementing that integration under a seven-day window. The exact server and a one-line justification will be recorded here once selected and wired.

## Human gate and logging

Every irreversible step (release to farmer) requires a named officer approval with timestamp. Planned logs: tool name, inputs/outputs (redacted), source ids, case id, priority, officer identity, and decision. The LLM never executes arbitrary commands; tools are allowlisted and schema-validated.

## Why this shape

Extension officers already sit between signals and households. The agent compresses retrieval and drafting; the officer keeps accountability. Narrow soybean scope keeps the corpus and evals honest for the build window.
