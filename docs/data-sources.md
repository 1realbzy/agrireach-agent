# Data sources and evidence policy

**Status:** four sources integrated: two soybean guides (13 Oct 2026), and a maize guide and an aflatoxin study (25 Oct 2026, added for the field-evidence evals). Every passage is a verbatim excerpt, re-checked against the source document with `python scripts/verify_corpus.py` (26/26 OK on 25 Oct 2026).

| Id | Document | Licence | URL |
|---|---|---|---|
| APNI-SARI-2023 | Soybean Cropping Guide, 4R Nutrient Management, Northern Ghana (APNI & CSIR-SARI, 2023) | CC BY 4.0 | https://www.apni.net/wp-content/uploads/2023/06/4R-Soybean-Guide-N-Ghana.pdf |
| IITA-SSPING-2022 | Training Manual on GAPs for Soyabean Production for Agricultural Extension Agents (IITA SSPiNG, with MoFA; 2022) | Not stated; short attributed excerpts only | https://cgspace.cgiar.org/bitstreams/cfc71dfe-5804-4f06-9617-7165a8e44cf9/download |
| APNI-SARI-2023-MAIZE | Maize Cropping Guide, 4R Nutrient Management, Northern Ghana (APNI & CSIR-SARI, 2023) | CC BY 4.0 | https://www.apni.net/wp-content/uploads/2023/06/4R-Maize-Guide-N-Ghana.pdf |
| AGBETIAMEH-2018 | Prevalence of Aflatoxin Contamination in Maize and Groundnut in Ghana (Plant Disease, 2018; doi:10.1094/PDIS-05-17-0749-RE). One mid-sentence excerpt: the Ghana Standards Authority limit of 15 ppb for maize | CC BY 4.0 | https://pmc.ncbi.nlm.nih.gov/articles/PMC7779968/ (verified against the Europe PMC full-text XML) |

Coverage: Northern Ghana soybean; Northern Ghana maize (planting window, fertilizer timing, fall armyworm, drying and storage); the national maize aflatoxin limit. No other crops, no prices, no contact details. The two sources genuinely differ on the planting window end (late July vs mid-July), within-row spacing (15 cm vs 10 cm), seed rate (50-60 vs 40-45 kg/ha) and planting depth. AgriReach surfaces these differences to the officer instead of picking one.

## Place names (25 Oct 2026)

`data/gazetteer.json`: Ghana's 16 regions and 261 districts with their capitals, parsed from Wikipedia's "Districts of
Ghana" (revision 1359154973, 13 June 2026), CC BY-SA 4.0; attribution is in the file's `_source` field. Used only to
recognise place names (to keep them out of the judge's input, and on the voice branch to recognise the farmer's
location), never as agricultural evidence.

## Selection criteria

- Prefer Ghanaian public agricultural institutions, recognised research bodies, and qualified extension material.
- Capture publisher, title, URL or document identifier, publication date, crop, region, and licence where available.
- Do not include copyrighted material unless use is permitted.
- Do not imply that general guidance is tailored to a locality unless the source supports that claim.
- Weather information should include provider, location, retrieval timestamp, and forecast period.
- If sources disagree or evidence is stale, surface the uncertainty and escalate.

## Initial scope

Start with a small, verified set of soybean extension references relevant to Ghana. Avoid scraping or ingesting large collections before source quality and reuse rights have been checked.

## Deliberately not added (25 Oct 2026)

The field-evidence evals (see EVALS.md) also cite news reports and studies. These were not turned into corpus passages:
- Prices (cocoa producer price, tomato market prices): time-sensitive and not extension guidance. AgriReach should decline price questions rather than quote a dated figure.
- The MoFA 2024 dry-spell advice: known only from a newspaper report (Ghanaian Times), not a MoFA document; licence unclear.
- Storage loss and fall armyworm studies: they describe farmer losses, not guidance to give.
- Product names and doses (e.g. the maize guide's stem borer spray rate and storage fumigants): AgriReach never prescribes products or doses, so those lines were not excerpted.
