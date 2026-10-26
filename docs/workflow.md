# Intended user workflow

**Status: implemented locally; automated tests do not show field readiness.** How the approval gate works is in [ARCHITECTURE.md](../ARCHITECTURE.md).

1. A farmer submits a question and selects the crop and locality if known.
2. The agent checks whether it has enough context to search responsibly.
3. If needed, it asks a short clarification question.
4. The agent retrieves relevant guidance and supporting source details through MCP.
5. It synthesises a plain language draft advisory, clearly separating source supported information from uncertainty.
6. The agent creates a review case for every draft. If the evidence is insufficient or conflicting, or the case is high risk, the case is marked urgent. Otherwise it is routine. Priority never bypasses review.
7. A named extension officer reviews the question, evidence, and draft advisory, then approves, edits, rejects, or requests more information. Only approved advice is released to the farmer.
8. The final outcome, approving officer, and status are recorded so follow up can be tracked.

## Workflow regression requirements

- A routine question produces a draft advisory that cites retrieved references and waits in the routine review queue.
- Missing crop or location context triggers clarification where it matters.
- No matching reference results in an explicit uncertainty message, not a fabricated answer.
- Conflicting references mark the case as urgent.
- High risk cases are placed in the urgent review queue.
- No advisory can be released to a farmer without a recorded officer approval.
- MCP errors are handled without inventing results.
- Officer decisions are recorded and distinguishable from agent suggestions.

## Case statuses

| Status | Meaning | Who moves it on | In the officer queue? | Farmer view |
|---|---|---|---|---|
| `draft` | The agent asked the farmer a clarifying question, so there's no review case yet | the agent | no | waiting |
| `pending_review` | The draft and proposed farmer text are waiting for an officer | officer: approve, edit, reject or request info | **yes** | waiting |
| `approved` | An officer approved the exact farmer text. This is a brief state, released straight away | release | no | waiting |
| `released` | An immutable approval is published. Channel jobs separately track pending, sending, accepted, definitely_failed and unknown outcomes; accepted does not prove handset receipt. Web cases expose the approved answer. | delivery service | no | approved answer only when web release or channel acceptance is recorded |
| `not_delivered` | Sending failed or its outcome is unknown. The reason is in delivery_problem; job state determines recovery. | definitely_failed: revise/reject/retry; unknown: authenticated evidence reconciliation before retry | **yes** | no answer exposed as delivered |
| `undeliverable` | Approved, but it can never be sent, because the farmer sent STOP or the number was removed by the retention purge. The reason is in `delivery_problem`, and the officer's decision and text stay on the record | none (final). Further decisions and releases get a 409 | no. Listed in `GET /officer/cases?status=undeliverable` and the "Case history" panel | "no answer was sent", no text |
| `rejected` | The officer rejected the draft | none (final) | no | waiting |
| `needs_info` | The officer asked for more information | authenticated reopen with information and expected revision | no until reopened | waiting |

`GET /officer/cases[?status=...]` (signed-in officers) lists every case with its status and `delivery_problem`.
`/officer/queue` lists only the actionable ones: `pending_review` and `not_delivered`.
