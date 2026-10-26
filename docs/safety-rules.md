# Safety rule reference

Policy version: chemical-2. Authoritative implementation: safety_gate.py. Accepted templates and source fingerprints are explicit in that module. Changing them requires a policy version change and regression review.

| Rule | Enforcement | Recovery |
| :--- | :--- | :--- |
| S1 | Preserve applicable chemical consultation guidance or a registered referral alternative | Revise, reject or request information |
| S2 | Block recognised reversals of consultation, label and protection obligations | Revise, reject or request information |
| S3 | Chemical instructions must be complete source sentences or complete accepted templates | Revise; unrecognised formulations require review |

“Consult your local agricultural extension officer before choosing or applying a pesticide.” is accepted. “Do not use unapproved pesticides.” and “Do not spray without gloves.” are protective accepted templates. “Do not consult your local AEA before spraying.” is a recognised reversal. A safe referral followed by weekly pesticide spraying instructions does not pass.

Comparison normalization does not rewrite stored text. It normalizes case and whitespace and removes only recognised source attributions. Numbers, conditions and negation remain significant. Similar words do not prove equivalent meaning.

The three baseline chemical passages are registered by ID and text fingerprint. Unknown or changed chemical sources require review. S1 relevance uses both the immutable question and submitted reply. Only classified incidental topics can be excluded; ambiguous case topics keep all safeguards. Storage, grain, sacks and bagging trigger storage relevance. Field scouting of cobs alone does not establish a storage topic. S2 and S3 inspect all sentences regardless of S1 relevance.

Unsupported material instruction grammar (use/apply/mix plus object, or treat/drench/dust with a material) requires review even for lowercase unfamiliar names and cases without chemical sources. It can conservatively hold legitimate unsupported nonchemical material advice. It cannot identify every product or meaning reversal. Registered complete referral and protective templates remain accepted. English replies can be assessed even when the proposal was Twi. Twi word markers and unsupported scripts still hold; Unicode punctuation, temperature symbols and a place name alone do not establish language. This bounded language heuristic is not a multilingual semantic assessment.

Noncritical probabilistic support concerns can produce a 10 minute acknowledgement challenge. The challenge is bound to the exact candidate, source context, officer credential and warning set. Critical findings, unsupported chemical wording and a failed judge cannot be acknowledged away.

Unknown products, indirect instructions, sentence combinations and inaccurate sources remain limitations. The frozen fixture set is bounded and dominated by source quotations. Its pass rate is not evidence of field safety. Report deterministic blocks separately from review holds.
