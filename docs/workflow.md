> Current local safety branch, 26 October 2026: approval uses a shared deterministic gate, revision/context binding, immutable approval records, single use acknowledgements and claimed delivery jobs. See [the safety walkthrough](safety-architecture.md) and the implementation progress record. Historical descriptions below remain preserved; their warning only approval and prehardening release semantics do not describe this branch. Acceptance is pending the historical compatibility decision and independent review.

# Intended user workflow

**Status: workflow proposal, not a working application.**

1. A farmer submits a question and selects the crop and locality if known.
2. The agent checks whether it has enough context to search responsibly.
3. If needed, it asks a short clarification question.
4. The agent retrieves relevant guidance and supporting source details through MCP.
5. It synthesises a plain language draft advisory, clearly separating source supported information from uncertainty.
6. The agent creates a review case for every draft. If the evidence is insufficient or conflicting, or the case is high risk, the case is marked urgent. Otherwise it is routine. Priority never bypasses review.
7. A named extension officer reviews the question, evidence, and draft advisory, then approves, edits, rejects, or requests more information. Only approved advice is released to the farmer.
8. The final outcome, approving officer, and status are recorded so follow up can be tracked.

## Planned acceptance tests

- A routine question produces a draft advisory that cites retrieved references and waits in the routine review queue.
- Missing crop or location context triggers clarification where it matters.
- No matching reference results in an explicit uncertainty message, not a fabricated answer.
- Conflicting references mark the case as urgent.
- High risk cases are placed in the urgent review queue.
- No advisory can be released to a farmer without a recorded officer approval.
- MCP errors are handled without inventing results.
- Officer decisions are recorded and distinguishable from agent suggestions.

## Case statuses (as built, 25 Oct 2026)

| Status | Meaning | Who moves it on | In the officer queue? | Farmer view |
|---|---|---|---|---|
| `draft` | The agent asked the farmer a clarifying question, so there's no review case yet | the agent | no | waiting |
| `pending_review` | The draft and proposed farmer text are waiting for an officer | officer: approve, edit, reject or request info | **yes** | waiting |
| `approved` | An officer approved the exact farmer text. This is a brief state, released straight away | release | no | waiting |
| `released` | **Channel case** (simulator, WhatsApp, SMS): the channel accepted the approved text. For SMS and WhatsApp that means the provider took it, not that the phone has it, because delivery reports aren't handled yet. **Web-form case** (`/ask`, no phone contact): AgriReach sends nothing, so it means the answer is now readable at `/farmer/cases/{id}` | none (final) | no | the approved answer |
| `not_delivered` | Released, but the send failed: provider error, network error, outcome unknown, the SMS length backstop, or the channel not configured. The reason is in `delivery_problem` | officer: approve again (after editing if needed), or retry with `POST /cases/{id}/release` | **yes**, tagged NOT DELIVERED | "not sent yet", no text |
| `undeliverable` | Approved, but it can never be sent, because the farmer sent STOP or the number was removed by the retention purge. The reason is in `delivery_problem`, and the officer's decision and text stay on the record | none (final). Further decisions and releases get a 409 | no. Listed in `GET /officer/cases?status=undeliverable` and the "Case history" panel | "no answer was sent", no text |
| `rejected` | The officer rejected the draft | none (final) | no | waiting |
| `needs_info` | The officer asked for more information | none yet (no follow-up flow built) | no | waiting |

`GET /officer/cases[?status=...]` (signed-in officers) lists every case with its status and `delivery_problem`.
`/officer/queue` lists only the actionable ones: `pending_review` and `not_delivered`.
