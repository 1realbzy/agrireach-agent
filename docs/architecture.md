# AgriReach architecture

**Status: original pre-build design (written before implementation).** The as-built design is in [ARCHITECTURE.md](../ARCHITECTURE.md).

## Components

1. **User interface:** Streamlit form for farmer question, crop, region, season, and optional context.
2. **API layer:** FastAPI validates requests and manages case records.
3. **Agent orchestration:** Python workflow controls the sequence of request interpretation, missing information checks, retrieval, synthesis, and escalation.
4. **LLM:** Interprets the request and drafts a response using retrieved evidence. Provider and model remain to be selected.
5. **MCP client:** Discovers and calls explicitly approved tools on the agricultural knowledge MCP server.
6. **MCP server:** Exposes the curated reference collection and case operations as tools and resources.
7. **Data store:** SQLite is proposed for case metadata, state, reviewer actions, and audit events.
8. **Human review:** A named extension officer reviews every draft advisory (urgent and routine queues), approves, edits, or rejects it, and records the outcome. Nothing reaches a farmer without approval.

## Intended sequence

1. Validate the farmer's request and gather crop and location context.
2. Ask a clarifying question when required information is missing.
3. Retrieve relevant passages through MCP tools.
4. Generate a response grounded in the returned passages and preserve source identifiers.
5. Apply explicit priority rules: insufficient evidence, conflicting sources, or high impact advice mark the case as urgent.
6. Route every draft advisory and its evidence to the officer review queue. Priority never bypasses review.
7. Store the case state and reviewer outcome.

## Architecture boundaries

The LLM does not directly execute arbitrary commands. Tool calls are limited to an allowlist and validated by the application. The system should treat retrieved documents as data, not as instructions. No external write action should occur without validation; every recommendation requires approval from a named extension officer before it reaches a farmer.

## Proposed stack

Python, FastAPI, Streamlit, Python MCP SDK, an LLM API, SQLite, and curated agricultural references. All dependencies and provider selections are subject to implementation and testing during the official build window.
