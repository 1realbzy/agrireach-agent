# AgriReach

**An MCP enabled agricultural extension agent for Ghana**

> **Build status:** This repository currently contains the project proposal, documentation, and planned architecture. It is not yet a working or deployed agent. The repository structure and design documents may be prepared before the official build window; the implementation intended for evaluation will be developed during the official seven day window.

## Problem statement

Smallholder farmers in Ghana can struggle to access timely, reliable agricultural guidance. Agricultural extension officers serve many farmers across dispersed communities, making it difficult to respond promptly to every question about planting, crop management, pest and disease concerns, and weather risks. Delayed or unreliable guidance can contribute to poor decisions, crop losses, and lower productivity.

## Solution overview

AgriReach is designed to help agricultural extension officers handle routine farmer enquiries more efficiently. A farmer submits a question. The agent identifies missing context, retrieves relevant guidance from curated agricultural references through tools, synthesises a draft advisory with its evidence, and places it in a review queue. A named extension officer must approve every advisory before it reaches a farmer. Uncertain or high-risk cases are flagged as urgent, but no case skips review. The agent should state uncertainty rather than guess.

The initial scope is a narrow soybean advisory workflow in Ghana. This is a proposed MVP, not a claim that the workflow is already implemented.

## Project objectives

These are the objectives for the proposed MVP. None of them has been achieved or measured yet.

- Help extension officers handle routine farmer enquiries more efficiently, while keeping a named officer responsible for approving every advisory.
- Ground every response in curated, Ghana-relevant agricultural references and show the sources used.
- Ask for missing context, and state uncertainty instead of guessing.
- Route every draft advisory to a human extension officer for approval, and flag insufficient, conflicting, or high-risk cases as urgent.
- Record case status and review outcomes for traceability.
- Start with a narrow soybean advisory workflow, and expand only after it has been evaluated.

## Target users

- Smallholder farmers seeking practical crop guidance.
- Agricultural extension officers who review cases and support farmers.
- Agricultural organisations that coordinate extension services.

## African context

The project focuses on Ghana's smallholder farming context, where agricultural advice must be practical, understandable, relevant to the local crop and season, and usable where connectivity or access to specialists may be limited. The first prototype will use a limited, curated knowledge set rather than claim nationwide coverage.

## Proposed workflow

This is a proposed workflow, not a working application. The full version is in [the workflow document](docs/workflow.md).

1. A farmer submits a question and selects the crop and locality if known.
2. The agent checks whether it has enough context and, if needed, asks a short clarifying question.
3. The agent retrieves relevant guidance and source details through MCP tools.
4. It drafts a plain-language advisory that separates source-supported information from uncertainty.
5. Every draft goes into the officer review queue. Insufficient or conflicting evidence, or a high-risk case, marks it as urgent. Risk sets priority only and never bypasses review.
6. A named extension officer approves, edits, rejects, or requests more information. Only approved advice reaches the farmer.
7. The outcome, approver, and status are recorded so that follow-up can be tracked.

## Architecture

![AgriReach proposed architecture](docs/architecture.png)

Planned flow:

1. A farmer submits a question through a lightweight web interface.
2. A Python agent uses an LLM to interpret the request and identify missing information.
3. An MCP client calls tools exposed by a dedicated agricultural knowledge MCP server.
4. Tools retrieve relevant extension guidance and source metadata. A weather tool may be added if a suitable source is verified.
5. The agent produces a grounded draft advisory with source references and uncertainty notes.
6. Every draft is queued for a named extension officer to approve. Uncertain, conflicting, or high-impact cases go to the urgent queue. Nothing reaches the farmer without approval.
7. Case status and review outcomes are recorded for traceability.

See the one-page [ARCHITECTURE.md](ARCHITECTURE.md), [the detailed architecture](docs/architecture.md), and [MCP design](docs/mcp-design.md).

## Setup and installation instructions

This repository is currently a proposal and documentation scaffold. A runnable application has not yet been implemented, so there are no working application installation or launch commands at this stage.

During the official seven day build window, the planned implementation will use Python. The repository already includes an environment file example (`.env.example`, placeholder names only) and a list of planned dependencies (`requirements.txt`, not yet installed or tested). The build will add application entry points, tests, and verified setup commands. Never put API keys or credentials in the repository.

## Usage instructions

There is no functioning application to use yet. The intended usage flow is described in [the workflow document](docs/workflow.md). Instructions will be updated after the implementation is built and tested during the official build window.

## Technology stack

Planned stack, subject to verification during implementation:

- Python for application and agent logic.
- FastAPI for the backend API.
- Streamlit for the initial user interface.
- Python MCP SDK for MCP client and server components.
- An LLM API for request interpretation and response synthesis. The provider and model are not yet selected.
- SQLite for local case records in the MVP.
- Curated Ghana relevant agricultural extension documents as the initial knowledge source.
- An external weather API only if its coverage, access terms, and reliability are verified.

These are proposed technologies. This README does not claim that they have been integrated or tested.

## Agent architecture

The planned agent workflow consists of request intake, context collection, evidence retrieval, recommendation synthesis, confidence and risk checks, and hand-over of every draft to the officer review queue. The agent never sends advice to a farmer itself. Tool selection will be constrained to a small set of approved operations. The first version should use explicit workflow states rather than unrestricted autonomous action.

## MCP implementation

MCP is planned as the standard interface between the agent and agricultural tools. The intended architecture includes a Python MCP client and a local Agricultural Knowledge MCP server. The server is expected to expose tools such as `search_guidance`, `get_crop_calendar`, `retrieve_reference`, and `create_or_update_case`. These are proposed tool names and are **not implemented yet**.

The server may expose resources containing curated extension documents, crop calendar material, and source metadata. An external weather service may be wrapped as a tool after an appropriate provider is selected. See [MCP design](docs/mcp-design.md).

## MCP tools and servers

| Component | Purpose | Status |
|---|---|---|
| Agricultural Knowledge MCP server | Expose approved agricultural reference material | Planned |
| `search_guidance` | Search the curated knowledge set | Planned |
| `get_crop_calendar` | Retrieve crop and season reference information | Planned |
| `retrieve_reference` | Return supporting passages and source metadata | Planned |
| `create_or_update_case` | Record a case and its review status | Planned |
| Weather API tool | Retrieve local forecast data if verified | Optional, not selected |

No live MCP server or external API integration is currently claimed.

## Human in the loop workflow

No advice ever reaches a farmer without approval from a named extension officer. The agent drafts, and the officer decides. Every draft advisory enters a review queue. Risk and uncertainty only set its priority: cases where sources conflict, the location or crop context is missing, confidence is low, or advice could have material consequences go to the urgent queue, and all other cases go to the routine queue. The extension officer can review the original question, retrieved references, draft advisory, and reason for any urgent flag. The officer can approve, edit, reject, or request more information, and each decision is recorded with the officer's name and a timestamp. The agent must not autonomously prescribe hazardous chemical use or present a suspected plant disease as a confirmed diagnosis.

## Development roadmap

**Before the official build window (current stage):** problem framing, proposed architecture and diagram, MCP tool design, workflow and human review design, data-source policy, the one-page architecture note, the planned evals sheet, and the repository scaffold. No application code has been written.

**During the official seven day build window (planned):**

1. Select and document the LLM provider and a small, verified starter corpus of soybean references with clear licences.
2. Implement the Agricultural Knowledge MCP server and its tool schemas.
3. Implement the MCP client and the agent orchestration workflow, including escalation rules.
4. Add the SQLite case records, the FastAPI backend, and the Streamlit interface, including officer review.
5. Test discovery, tool calls, error handling, source traceability, and escalation against the planned acceptance tests in [the workflow document](docs/workflow.md).
6. Update this README with verified setup commands, usage instructions, and honest results.

Design scaffolds already in this repository (no application code yet): a one-page [ARCHITECTURE.md](ARCHITECTURE.md) and an [EVALS.md](EVALS.md) with nine planned test tasks (results not run). Still planned for the build window: one third-party MCP server alongside our own, an open-source orchestration framework (for example LangGraph or Pydantic AI), honest pass/fail results in `EVALS.md`, and at least one full task run on an open-weights model.

**After the challenge:** see Future improvements.

## Limitations

- No working agent or deployed application exists in this initial scaffold.
- Coverage will be limited to the selected crop, knowledge documents, and region.
- The quality of recommendations depends on the authority and freshness of source material.
- Text based advice may not be enough to diagnose a plant health issue.
- Local language support, offline access, and accessibility require further work.
- Weather coverage and API access have not yet been verified.
- The system is decision support and does not replace qualified agricultural advice.

## Future improvements

- Validate the MVP with agricultural extension officers and farmers.
- Add carefully evaluated local language support.
- Add image based crop issue triage only after collecting suitable validation data.
- Add low bandwidth and offline friendly interaction.
- Expand beyond soybean after evaluating the first workflow.
- Add monitoring for follow up cases and referral outcomes.
- Evaluate factual grounding, escalation quality, response time, and farmer usability.

## Evaluation plan

The prototype should be evaluated on whether it retrieves relevant evidence, cites the source used, asks for missing context, abstains when evidence is insufficient, sends every draft to officer review, flags risky cases as urgent, and records a traceable case history. The planned task list is in [EVALS.md](EVALS.md). Performance claims will only be added after tests or user evaluation support them.

## Repository structure

```text
.
├── README.md
├── ARCHITECTURE.md
├── EVALS.md
├── LICENSE
├── .env.example
├── .gitignore
├── requirements.txt
├── docs/
│   ├── architecture.md
│   ├── architecture.png
│   ├── mcp-design.md
│   ├── workflow.md
│   └── data-sources.md
├── src/README.md
├── tests/README.md
└── data/README.md
```

## Build window integrity

The proposal and repository scaffold are documented before implementation. The evaluated application code is intended to be developed during the official seven day build window. The build window dates must be confirmed by the challenge organisers. This repository should not be represented as a working agent until the implementation has been completed and tested.

## Licence

This project is released under the MIT License (see [LICENSE](LICENSE)). Do not add third party datasets or documents unless their licence permits the intended use.
