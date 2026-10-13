# Data sources and evidence policy

**Status:** two sources integrated (13 Oct 2026). Every passage is a verbatim excerpt, re-checked against the PDF with `python scripts/verify_corpus.py` (14/14 OK).

| Id | Document | Licence | URL |
|---|---|---|---|
| APNI-SARI-2023 | Soybean Cropping Guide, 4R Nutrient Management, Northern Ghana (APNI & CSIR-SARI, 2023) | CC BY 4.0 | https://www.apni.net/wp-content/uploads/2023/06/4R-Soybean-Guide-N-Ghana.pdf |
| IITA-SSPING-2022 | Training Manual on GAPs for Soyabean Production for Agricultural Extension Agents (IITA SSPiNG, with MoFA; 2022) | Not stated; short attributed excerpts only | https://cgspace.cgiar.org/bitstreams/cfc71dfe-5804-4f06-9617-7165a8e44cf9/download |

Coverage: Northern Ghana soybean only. The two sources genuinely differ on the planting window end (late July vs mid-July), within-row spacing (15 cm vs 10 cm), seed rate (50-60 vs 40-45 kg/ha) and planting depth. AgriReach surfaces these differences to the officer instead of picking one.

## Selection criteria

- Prefer Ghanaian public agricultural institutions, recognised research bodies, and qualified extension material.
- Capture publisher, title, URL or document identifier, publication date, crop, region, and licence where available.
- Do not include copyrighted material unless use is permitted.
- Do not imply that general guidance is tailored to a locality unless the source supports that claim.
- Weather information should include provider, location, retrieval timestamp, and forecast period.
- If sources disagree or evidence is stale, surface the uncertainty and escalate.

## Initial scope

Start with a small, verified set of soybean extension references relevant to Ghana. Avoid scraping or ingesting large collections before source quality and reuse rights have been checked.
