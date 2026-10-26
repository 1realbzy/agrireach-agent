# Safety rule reference

Policy version: chemical-1. Authoritative implementation: safety_gate.py. Accepted templates and source fingerprints are explicit in that module. Changing them requires a policy version change and regression review.

| Rule | Enforcement | Recovery |
| :--- | :--- | :--- |
| S1 | Preserve applicable chemical consultation guidance or a registered referral alternative | Revise, reject or request information |
| S2 | Block recognised reversals of consultation, label and protection obligations | Revise, reject or request information |
| S3 | Chemical instructions must be complete source sentences or complete accepted templates | Revise; unrecognised formulations require review |

“Consult your local agricultural extension officer before choosing or applying a pesticide.” is accepted. “Do not use unapproved pesticides.” and “Do not spray without gloves.” are protective accepted templates. “Do not consult your local AEA before spraying.” is a recognised reversal. A safe referral followed by weekly pesticide spraying instructions does not pass.

Comparison normalization does not rewrite stored text. It normalizes case and whitespace and removes only recognised source attributions. Numbers, conditions and negation remain significant. Similar words do not prove equivalent meaning.

The three baseline chemical passages are registered by ID and text fingerprint. Unknown or changed chemical sources require review. Storage chemicals are included. The English policy deliberately holds unsupported language assessment. Current language heuristics can also hold valid English containing unfamiliar characters; this remains a limitation.

Noncritical probabilistic support concerns can produce a 10 minute acknowledgement challenge. The challenge is bound to the exact candidate, source context, officer credential and warning set. Critical findings, unsupported chemical wording and a failed judge cannot be acknowledged away.

Unknown products, indirect instructions, sentence combinations and inaccurate sources remain limitations. The frozen fixture set is bounded and dominated by source quotations. Its pass rate is not evidence of field safety. Report deterministic blocks separately from review holds.
