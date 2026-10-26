# Approval architecture walkthrough

The LangGraph agent still handles intake, clarification, retrieval, source checking, drafting and filing. Its custom MCP server provides corpus and case tools. Its case action cannot approve or release advice. The external fetch MCP server checks source reachability and topic relevance, not agricultural accuracy.

Officer requests enter api.py with the registered bearer identity. The simulator CLI now requires a registered officer credential through AGRIREACH_OFFICER_TOKEN. Both call db.officer_decide, which delegates to approval.decide. Direct Python callers remain trusted local execution, not a remote authentication boundary.

The safety gate performs deterministic assessment without I/O. The approval service snapshots the case and resolved source contents. If a model assessment is needed, it happens before the SQLite write transaction. Inside BEGIN IMMEDIATE, the service verifies that the snapshot and credential have not changed, records the submission and assessment, consumes an eligible acknowledgement and records approval and audit together. Immutable evidence triggers prevent ordinary updates and deletes.

Release validates the approval fingerprint and reruns deterministic rules. delivery.claim atomically reserves a unique job before external sending. A second caller cannot send the same active job. Dispatch results update the matching claim. A crash can still leave an unresolved provider outcome; exactly once external delivery is not claimed.

Source support, agricultural correctness and actual farmer receipt are separate questions. Neither an exact quote nor a positive judge establishes all three. Current QA corrections and limitations are in remediation-progress.md; the original implementation evidence remains in implementation-progress.md.
