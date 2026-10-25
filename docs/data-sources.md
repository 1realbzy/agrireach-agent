# Data sources and evidence policy

**Status:** six sources integrated: two soybean guides (13 Oct 2026); a Northern Ghana maize guide and an aflatoxin study (25 Oct 2026, added for the field-evidence evals); and two national maize guides with planting windows for every agroecological zone (25 Oct 2026, later). Every passage is a verbatim excerpt, re-checked against the source document with `python scripts/verify_corpus.py` (42/42 OK on 25 Oct 2026; table rows are checked cell by cell).

| Id | Document | Licence | URL |
|---|---|---|---|
| APNI-SARI-2023 | Soybean Cropping Guide, 4R Nutrient Management, Northern Ghana (APNI & CSIR-SARI, 2023) | CC BY 4.0 | https://www.apni.net/wp-content/uploads/2023/06/4R-Soybean-Guide-N-Ghana.pdf |
| IITA-SSPING-2022 | Training Manual on GAPs for Soyabean Production for Agricultural Extension Agents (IITA SSPiNG, with MoFA; 2022) | Not stated; short attributed excerpts only | https://cgspace.cgiar.org/bitstreams/cfc71dfe-5804-4f06-9617-7165a8e44cf9/download |
| APNI-SARI-2023-MAIZE | Maize Cropping Guide, 4R Nutrient Management, Northern Ghana (APNI & CSIR-SARI, 2023) | CC BY 4.0 | https://www.apni.net/wp-content/uploads/2023/06/4R-Maize-Guide-N-Ghana.pdf |
| MOFA-MAIZE | Maize Production Guide (Ministry of Food and Agriculture, Directorate of Agricultural Extension Services; no year printed, PDF created 2020). Table 5.1 "Recommended planting periods for different agro-ecological zones in Ghana" (pp. 11-12) and section 5.1 "When to plant" (p. 10) | Not open. The guide says: "Shorts extracts of this publication may be reproduced in any non-advertising, non-profit-making context provided that the source is acknowledged" | https://mofa.gov.gh/site/images/pdf/production_guides/GUIDE_TO_MAIZE_PRODUCTION.pdf |
| IITA-MAIZE-2025 | Guide for sustainable maize production in Ghana (Abdul Rahman, Kotu, Ortega-Beltran, Adjei-Nsiah, Agbetiameh, Buah; IITA, 2025). Table 4 planting windows (p. 16) and section 1.4 "Planting" (p. 15) | CC BY 4.0 (CGSpace metadata) | https://cgspace.cgiar.org/items/e9c5bd9a-4669-4b3d-aa0c-a13394baf389 |
| AGBETIAMEH-2018 | Prevalence of Aflatoxin Contamination in Maize and Groundnut in Ghana (Plant Disease, 2018; doi:10.1094/PDIS-05-17-0749-RE). One mid-sentence excerpt: the Ghana Standards Authority limit of 15 ppb for maize | CC BY 4.0 | https://pmc.ncbi.nlm.nih.gov/articles/PMC7779968/ (verified against the Europe PMC full-text XML) |

Coverage: Northern Ghana soybean; Northern Ghana maize (planting window, fertilizer timing, fall armyworm, drying and storage); maize planting windows for every agroecological zone (MoFA and IITA, major and minor season); the national maize aflatoxin limit. Outside planting time, all maize and soybean guidance is still from Northern Ghana guides. No other crops, no prices, no contact details. The two sources genuinely differ on the planting window end (late July vs mid-July), within-row spacing (15 cm vs 10 cm), seed rate (50-60 vs 40-45 kg/ha) and planting depth. AgriReach surfaces these differences to the officer instead of picking one.

MoFA and IITA also differ: forest major season "Early March-end of April" (MoFA) vs "End of March - End of April" (IITA); transition major season "Mid-March-end of April" vs "End of March - End of April"; and for Northern Ghana, APNI "between early June and July 10th", MoFA "End of May-early July" and IITA "End of May - Mid of July" (Sudan) or "End of May - End of July" (Guinea). These are flagged as conflicts for the officer.

Table rows are stored one row per passage: `text` is the row's cells, each quoted exactly, joined with " | " (for example `Minor season | Forest | Mid July-early Sept.`). Which period belongs to which zone is read from the printed table layout; `cells` and, where the PDF splits a cell across lines, `pdf_lines` let `verify_corpus.py` check every part. No cell was reworded; "Costal savannah" is IITA's spelling.

The CGSpace document already in the corpus (IITA-SSPING-2022) is a soybean manual; it has no maize windows. The IITA 2025 maize guide, also on CGSpace, was added for them.

## Agroecological zones (25 Oct 2026)

Every passage has a `zones` tag: the six zones (Sudan savannah, Guinea savannah, transition, deciduous forest, rain forest, coastal savannah) it applies to, taken from the zone the source itself names (Northern Ghana guides: Guinea and Sudan savannah; MoFA "Forest": deciduous and rain forest; national text: all six).

`data/zones.json` maps the 16 regions and 261 districts (and the old name "Brong Ahafo") to a zone. **It is AgriReach's own approximate curation**, not an official table: no published district-to-zone list was found. Each region has a default zone and some districts an override; districts that straddle two zones are marked `boundary`, and the officer is asked to confirm the zone for them. An extension officer should check this file before it is relied on.

## Rainfall and district coordinates (25 Oct 2026)

Rainfall is data, not guidance; it is never a corpus passage.
- **Open-Meteo** (default): daily `precipitation_sum` for the district's point, past 30 complete days, from the
  forecast API's past days (model-based). Data CC BY 4.0, attribution "Weather data by Open-Meteo.com"
  (https://open-meteo.com/en/license). The free API is for non-commercial use only (https://open-meteo.com/en/terms).
- **NASA POWER** (opt-in cross-check): daily `PRECTOTCORR`. "No restrictions on the use, access, and/or download";
  NASA asks to be cited. Only MERRA2-only responses for days at least 7 days old are used (see
  [rainfall-live-2026-10-25.md](rainfall-live-2026-10-25.md) for why).
- Not used: CHIRPS (public domain, but raster files; better for season comparisons than for the last 30 days).
- **District coordinates** (`data/district_coords.json`): one point per district, the district capital where found.
  256 from GeoNames (www.geonames.org, CC BY 4.0): 240 capitals matched by name in their region, 15 district (ADM2)
  points, 1 capital whose GeoNames region code is the old one (Likpe-Mate, Guan). 5 capitals not in GeoNames (Jinijini,
  Sagnarigu, Tatale, Ave-Dakpa, Essam-Debiso) were looked up once on OpenStreetMap Nominatim (data (c) OpenStreetMap
  contributors, ODbL 1.0). Each entry records its source and match method. Approximate and not checked on the ground.

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
