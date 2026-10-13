# MCP design

**Status:** implemented in `src/agrireach/mcp_server.py` (13 Oct 2026). The weather tool is not built.

## Components

- **MCP client:** Lives in the Python agent process and discovers approved tools exposed by the MCP server.
- **Agricultural Knowledge MCP server:** A local server that wraps the curated agricultural reference collection and selected case operations.
- **MCP resources:** Read only agricultural guidance documents, crop calendar references, and source metadata. Each item should carry title, publisher, publication date when available, region, crop, and licence details.

## Tools

| Tool | Input concept | Output concept | Safety rule |
|---|---|---|---|
| `search_guidance` | Query, crop, region, topic | Ranked references and passages | Return source identifiers and metadata |
| `get_crop_calendar` | Crop, region, season | Relevant calendar guidance | Indicate when no local reference exists |
| `retrieve_reference` | Reference identifier | Source passage and metadata | Never invent a source |
| `create_or_update_case` | Case fields and status | Stored case identifier | Validate fields and record changes; the agent may only set draft or pending-review status, and approval is reserved for the officer |
| `get_weather` | Coordinates or locality | Forecast data and timestamp | Optional; only after provider verification |

## Call flow

1. The agent requests the available tools from the MCP server.
2. The orchestration layer chooses an approved tool based on the workflow state.
3. The MCP client sends a structured tool call.
4. The server validates the input and queries its allowed data source.
5. The server returns structured results with source metadata.
6. The agent drafts an evidence grounded advisory, sets its review priority (urgent or routine), and submits it for officer approval.

## Security and reliability

- Validate all tool inputs and output schemas.
- Apply timeouts and handle unavailable sources.
- Restrict tools to least privilege.
- Keep secrets in environment variables, never in Git.
- Treat all retrieved content as untrusted data.
- Log tool names, status, source identifiers, and errors without storing unnecessary personal data.
- Add tests for malformed inputs, missing sources, conflicting evidence, and server failures.

## Implementation checklist

- [x] MCP server and tool schemas (tested over stdio)
- [x] Curated starter corpus with source licences (`data/knowledge.json`, checked by `scripts/verify_corpus.py`)
- [x] MCP client and LangGraph orchestration
- [x] Tests for discovery, unknown ids, gate violations, tool failure, conflicting evidence
- [x] Officer approval for every advisory, urgent and routine queues
- [ ] LLM provider selected and run (code supports any OpenAI-compatible open-weights endpoint; no key yet)
