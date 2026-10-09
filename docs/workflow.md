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
