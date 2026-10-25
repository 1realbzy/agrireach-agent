# Rainfall signal: plan (25 Oct 2026) and what was built

**Status (25 Oct 2026, later):** built on branch `feat/rainfall-signal` as the read-only MCP tool `get_recent_rainfall`
(`src/agrireach/rainfall.py`). What differs from the plan below:
- Licence decision: on 25 Oct 2026 Herbert approved Open-Meteo for non-commercial use (CC BY 4.0, credited as
  `RAINFALL-OPEN-METEO` in every draft that uses it). If AgriReach ever charges users, it needs a paid Open-Meteo plan.
- Provider: Herbert first chose NASA POWER, then asked to keep it off the default path. Default is **Open-Meteo**
  (CC BY 4.0; free API for non-commercial use, which fits a non-commercial challenge entry). NASA POWER is an opt-in
  cross-check (`AGRIREACH_RAINFALL_CROSSCHECK=nasa_power`) that only uses days at least 7 days old and only
  MERRA2-only responses: responses that mix in near-real-time GEOSIT days came back 24 times larger for the same day.
- Window: the last 30 complete days (UTC), not 14 days plus a forecast. No forecast is shown.
- Coordinates: `data/district_coords.json` (GeoNames CC BY 4.0, 5 points from OpenStreetMap Nominatim, ODbL).
- The record IS shown to the drafting model, as a citable record (`RAINFALL-OPEN-METEO:<district>:<date>`), because
  the challenge brief asks recommendations to cite a rainfall record. A code check rejects any draft that says onset
  has been reached; the farmer text leaves the record out.
- The "~10x disagreement" below came from such a mixed NASA POWER response (71.28 / 24 = 2.97 mm); see
  [rainfall-live-2026-10-25.md](rainfall-live-2026-10-25.md).

The original plan follows.

Goal: show the extension officer recent and forecast rainfall for the farmer's place, next to the cited planting
guidance, so the officer can judge whether the guide's onset condition looks met. The tool informs the officer. It
never decides, never changes the guide's window, and never reaches the farmer without the officer's approval.


**Update (25 Oct 2026, after review):** top-dressing questions now get the rainfall record too, because the guide says to delay top dressing when the soil is very dry (APNI-SARI-2023-MAIZE p13). When the question gives only a region, or no place, no record is attached. Instead an officer-only line says why and asks the officer to get the district from the farmer. Planting questions also get an officer-only line with the case's received date next to the cited windows, plus a flag when the date is outside all of them (`src/agrireach/season.py`). These lines start with `Note: (officer only)`, are added after the citation checks, and are stripped before the SMS is proposed. A proposed SMS that reads as "rains are good, plant now" is withheld, so the officer writes it. When every cited window can be read and none contains the received date, the officer also gets an approval prompt next to the farmer text, in the same list as "sources differ": "season check: the question was received on 25 Oct 2026, which is outside every planting window cited in the draft; check the timing before approving". The prompt is stored with the proposal, so it stays when the SMS is re-proposed. It is never SMS text. When the place field is empty (as on SMS) or names only a region, the question text is searched for a known district (`rainfall.districts_in_text`, using the names in `data/district_coords.json` and `data/gazetteer.json`). Names are matched as whole words in any case. Names of 3 letters or fewer (Ho, Wa, La, Osu) and names that are also ordinary words (`places.AMBIGUOUS`: Bole, Sang, Tease and others) count only directly after "in", "at", "from" or "near". The record is attached only when exactly one district matches. In that case the officer line says "District Tamale taken from the question text." When several districts match, or the district is in a different region from the one given, nothing is attached and the officer line says why. The detected district is used only for the rainfall record: region, zone and zone_mismatch are unchanged, and a test covers this. A live check with the real model is in [season-fact-live-2026-10-25.md](season-fact-live-2026-10-25.md).

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
