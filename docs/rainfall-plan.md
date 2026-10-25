# Rainfall signal: plan (25 Oct 2026, not built yet)

Goal: show the extension officer recent and forecast rainfall for the farmer's place, next to the cited planting
guidance, so the officer can judge whether the guide's onset condition looks met. The tool informs the officer. It
never decides, never changes the guide's window, and never reaches the farmer without the officer's approval.

## What the cited guides say about onset (verbatim)

- IITA 2025 maize guide, p. 15 (`IITA-MAIZE-2025:p15-three-good-rains`): "It is recommended to plant after three good
  rains within the planting window to ensure enough soil moisture to support germination and early growth."
- MoFA Maize Production Guide, p. 10 (`MOFA-MAIZE:p10-when-to-plant`): "Sow after the rains have stabilized to avoid
  wilting. Planting time should be informed by local weather information."
- APNI/CSIR-SARI maize guide, p. 5 (`APNI-SARI-2023-MAIZE:p5-planting-window`): "... between early June and July 10th
  based on the onset of rains."

None of them defines a "good rain" in millimetres or says how to tell that rains "have stabilized". So AgriReach
must not compute "onset reached: yes/no". It shows daily amounts and lets the officer apply the guide. Agronomic onset
definitions from the literature (e.g. a rainfall total over a few days with no long dry spell after) are not in the
corpus; adding one would need its own verified source and an officer's agreement.

## Source options (checked 25 Oct 2026)

| Source | What | Licence / terms | Fit |
|---|---|---|---|
| Open-Meteo | Forecast API (up to 16 days) with `past_days`; daily `precipitation_sum`; no key | Data CC BY 4.0 with an attribution link; the free API is for non-commercial use only (10,000 calls/day), commercial use needs a paid plan (open-meteo.com/en/terms, /en/license) | Best for "rain in the last 14 days + next 3 days". Model output, not gauge data |
| CHIRPS (Climate Hazards Center, UCSB) | Satellite + station rainfall, ~5 km, pentad/dekad/daily | Public domain (copyright waived; CHIRPS3 also listed as CC BY 4.0). Preliminary data about 2 days after each pentad, final monthly | Best for "was this a normal season", not for this week. Large raster files; needs a point-extraction step |
| NASA POWER | Daily point API, `PRECTOTCORR` (mm/day), community `AG`, no key | "No restrictions on the use, access, and/or download"; NASA asks to be cited with service version and access date | Easy point API; 0.5° grid, coarse; ~2-3 days delay |

Quick access check from the box on 25 Oct 2026 for Kumasi (6.69 N, 1.62 W): both Open-Meteo and NASA POWER answered
without a key. They disagreed sharply: Open-Meteo gave 5.6 mm for 11 Oct, NASA POWER 71.28 "mm/day", with POWER values
up to 367.92 on 7 Oct and fill values (-999) for the last 3 days. This was not investigated further; it is a reason
to show the provider and never treat one provider's number as ground truth.

Proposed first source: **Open-Meteo**, because it covers both the last 14 days and a short forecast in one call. Its
free tier is non-commercial; if AgriReach is used by a commercial operator, it needs the paid plan or another source.
Herbert should decide this before any code.

## Tool interface (MCP, read-only)

`get_recent_rainfall(place: str, past_days: int = 14, forecast_days: int = 3) -> json`

Returns:
- `place`, `zone`, and the coordinates used, with where they came from (see risks: the gazetteer has no coordinates)
- `provider`, `provider_url`, `licence`, `attribution` ("Weather data by Open-Meteo.com"), `retrieved_at` (UTC)
- `daily`: `[{date, mm, kind: "observed-model" | "forecast"}]`
- `cache`: `{hit: bool, age_minutes}`
- on failure: `{"available": false, "reason": ...}`; never an estimate

No crop, no advice, no "onset reached" field.

## Where it shows up

- Officer screen: a "Rainfall (input, not guidance)" box under the cited passages: the daily amounts, provider,
  licence, retrieval time, and a fixed line: "The guides say to plant after the rains have stabilized / after three
  good rains. Rainfall data is model output; check local conditions."
- Not sent to the drafting model in the first version, so it can't turn numbers into advice. The citation check only
  accepts corpus passages, so a draft can't cite rainfall data as a source.
- Not in the farmer reply. The officer may mention it in their own words.

## Caching and offline behaviour

- Cache in SQLite keyed by (provider, rounded lat/lon, date), 6 h time-to-live for the forecast part, 24 h for past
  days. One call per district per 6 h at most: well under the free-tier limits.
- No network or a provider error: return the cached data marked with its age (and "stale" after 24 h), or
  `available: false`. The case still files normally; the rainfall box says "no rainfall data".
- The offline stub mode and the test suite never call the network: tests use recorded responses.

## Risks

- **Coordinates:** `data/gazetteer.json` has names only. A coordinates source is needed (e.g. district capitals from
  a licensed gazetteer such as GeoNames, CC BY 4.0) and must be verified per district.
- **Model data at a point is not the farmer's field.** Gridded/model rain can miss local storms; the providers
  disagreed by an order of magnitude in the quick check above.
- **No numeric onset rule in the cited guides.** Any threshold would be AgriReach's invention; not allowed.
- **Licence:** Open-Meteo's free API is non-commercial only; attribution must be shown wherever the data is shown.
- **Over-trust:** the officer could read "lots of rain" as "plant now". The fixed line and the officer-only display are
  the guard; an officer should review the wording.
- **Privacy:** the request sends only district-level coordinates, never a phone number or the farmer's exact location.

## Next steps (if approved)

1. Herbert picks the provider (Open-Meteo proposed) and confirms non-commercial use.
2. Add verified district coordinates.
3. Tests first: recorded provider responses, cache hit/miss, offline stale and unavailable paths, and that rainfall
   never enters the draft or the farmer reply.
4. Then the MCP tool and the officer-screen box.
