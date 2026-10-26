# AgriReach

**An MCP enabled agricultural extension agent for Ghana**

> **Build status (26 Oct 2026):** a working MVP runs locally. The MCP server, LangGraph agent, case database, officer approval with its safety gate, API, UI and tests have been run and verified. LLM drafting has been run with the open-weights model `mistralai/mistral-small-3.2-24b-instruct` via OpenRouter (see [EVALS.md](EVALS.md), which includes real LLM failures). Tests and CI run in offline stub mode. Nothing is deployed. See the status table below and [ARCHITECTURE.md](ARCHITECTURE.md).

## Problem statement

Smallholder farmers in Ghana can struggle to access timely, reliable agricultural guidance. Agricultural extension officers serve many farmers across dispersed communities, making it difficult to respond promptly to every question about planting, crop management, pest and disease concerns, and weather risks. Delayed or unreliable guidance can contribute to poor decisions, crop losses, and lower productivity.

## Solution overview

AgriReach is designed to help agricultural extension officers handle routine farmer enquiries more efficiently. A farmer submits a question. The agent identifies missing context, retrieves relevant guidance from curated agricultural references through tools, synthesises a draft advisory with its evidence, and places it in a review queue. A named extension officer must approve every advisory before it reaches a farmer. Uncertain or high-risk cases are flagged as urgent, but no case skips review. The agent should state uncertainty rather than guess.

The initial scope is a narrow soybean advisory workflow in Ghana; on 25 Oct 2026 a small set of verified Northern Ghana maize passages and the Ghana maize aflatoxin limit were added for the field-evidence evals, then MoFA's and IITA's maize planting windows for every agroecological zone, with guidance matched to the farmer's zone. Questions about other crops go straight to the officer. A local MVP runs with an open-weights model or in offline stub mode (see status below); nothing is deployed.

## Project objectives

These are the objectives for the MVP. Stub-mode and real-model evals for several of them are recorded in [EVALS.md](EVALS.md). Field validation with extension officers and farmers is still outstanding.

- Help extension officers handle routine farmer enquiries more efficiently, while keeping a named officer responsible for approving every advisory.
- Ground every response in curated, Ghana-relevant agricultural references and show the sources used.
- Ask for missing context, and state uncertainty instead of guessing.
- Route every draft advisory to a human extension officer for approval, and flag insufficient, conflicting, or high-risk cases as urgent.
- Record case status and review outcomes for traceability.
- Start with a narrow soybean advisory workflow, and expand only after it has been evaluated.

## Target users

- Smallholder farmers seeking practical crop guidance.
- Agricultural extension officers who review cases and support farmers.
- Agricultural organisations that coordinate extension services.

## African context

The project focuses on Ghana's smallholder farming context, where agricultural advice must be practical, understandable, relevant to the local crop and season, and usable where connectivity or access to specialists may be limited. The first prototype will use a limited, curated knowledge set rather than claim nationwide coverage.

## Proposed workflow

This is the workflow the local MVP implements (model or offline stub drafting; officer approval enforced). The full version is in [the workflow document](docs/workflow.md).

1. A farmer submits a question and selects the crop and locality if known.
2. The agent checks whether it has enough context and, if needed, asks a short clarifying question.
3. The agent retrieves relevant guidance and source details through MCP tools.
4. It drafts a plain-language advisory that separates source-supported information from uncertainty.
5. Every draft goes into the officer review queue. Insufficient or conflicting evidence, or a high-risk case, marks it as urgent. Risk sets priority only and never bypasses review.
6. A named extension officer approves, edits, rejects, or requests more information. Only approved advice reaches the farmer.
7. The outcome, approver, and status are recorded so that follow-up can be tracked.

## Architecture

Flow as built (rules route the case; the LLM only writes the draft and a second model judges it):

1. A farmer submits a question through the web interface, the API or the local voice-note simulator.
2. Rule-based intake detects crop, place and language, and asks a clarifying question if something is missing.
3. An MCP client calls tools exposed by our agricultural knowledge MCP server.
4. Tools retrieve verbatim extension guidance with source metadata, the planting windows for the farmer's zone, and a past-30-days rainfall record for planting and top-dressing questions. There is no forecast tool.
5. The agent drafts an advisory with source references, and code checks every figure and claim against the cited passages.
6. Every draft is queued for a named extension officer. Uncertain, conflicting, or high-impact cases go to the urgent queue.
7. The officer approves the exact farmer text, which first passes a safety gate. Nothing reaches the farmer without approval.
8. Case status, review outcomes and deliveries are recorded for traceability.

The full design, including every safety stop, is in [ARCHITECTURE.md](ARCHITECTURE.md). The original proposed design, drawn before the build, is [docs/architecture.png](docs/architecture.png).

## Setup and installation instructions

Requires Python 3.11+ (tested on 3.13). From a clean clone:

```bash
./run.sh          # creates .venv, installs pinned deps, starts API on :8000 and UI on :8501
./run.sh test     # runs the pytest suite
# or: make run / make test  (thin wrappers around run.sh)
```

To use a model, copy `.env.example` to `.env` and set `LLM_BASE_URL`, `LLM_MODEL` and `LLM_API_KEY` for any OpenAI-compatible endpoint serving an open-weights model. If these are left empty, the app runs in a clearly labelled OFFLINE STUB mode. Never commit `.env`.

### Three-step demo

1. **Start the app.** Run `./run.sh`, then open http://127.0.0.1:8501. With no `.env`, it runs in offline stub mode.
2. **Sign in as an officer.** In a second terminal, from the repo root, run `.venv/bin/python scripts/add_officer.py "Ama Mensah"`. It prints `Officer 'Ama Mensah' registered. Sign-in token (shown once, keep it private):` and the token on the next line. Paste the token into **Officer sign in token** on the **Extension officer** tab. Running the script again for the same name issues a new token, and the old one stops working. If your `.env` sets `DATABASE_URL`, run `set -a; . ./.env; set +a` first, so the script uses the same database as the app.
3. **Ask, then approve.** On the **Farmer** tab, ask "When should I harvest soybean in Tamale?" and click **Send**. Note the case number. On the **Extension officer** tab, click **Reload cases** and open the case. Check the draft and farmer text against the sources, tick **Required for approval: I checked every advice line against the cited sources**, and click **Approve and release**. Back on the **Farmer** tab, enter the case number and click **Check answer** to see the approved text.

The Farmer tab's default question, "When should I plant soybean in Tamale?", shows a hold instead. The guides give different planting windows, so approval returns a SOURCE_CONFLICT hold. The officer can reject or request info, or approve farmer text with no figures that keeps the line "Your extension officer will confirm which to follow."

## Usage instructions

- UI: as in the demo. Urgent cases are listed first. The officer can edit the draft and the farmer text, re-propose the farmer text, approve, reject or request info. When a case opens, any hold on the farmer text is shown with the line it applies to and the reason. The farmer only sees an answer after it is approved.
- CLI: `PYTHONPATH=src .venv/bin/python -m agrireach.agent "When should I harvest soybean in Tamale?"`
- API: `POST /ask`, `GET /farmer/cases/{id}`. Officer routes need `Authorization: Bearer <token>`: `GET /officer/queue`, `GET /officer/cases/{id}` (with its tool log), `POST /officer/cases/{id}/assess` (read-only safety check), `POST /officer/cases/{id}/decision`, and `POST /cases/{id}/release`, which refuses any case without a valid officer approval.

## Technology stack

Verified in this build: Python 3.13, official MCP Python SDK (`mcp` 1.30, FastMCP, stdio), LangGraph 1.2, `mcp-server-fetch` (third-party reference MCP server), SQLite, FastAPI, Streamlit, pytest. The OpenAI-compatible client (`openai` package) has been run against `mistralai/mistral-small-3.2-24b-instruct` (open weights) via OpenRouter.

## Agent architecture

A LangGraph state graph (`src/agrireach/agent.py`): `intake` (crop/region detection, risk terms, opens a `draft` case) → either `clarify` (end) or `retrieve` (MCP: `search_guidance`, `retrieve_reference` for each hit, `get_zone_planting_guidance` for planting questions, `get_recent_rainfall` for planting and top-dressing questions, `get_crop_calendar`; guidance for other agroecological zones is dropped when the farmer's zone has its own, otherwise kept with a caution, an urgent reason and `zone_mismatch`; conflict and risk flags) → `check_sources` (third-party fetch MCP server checks the cited source pages are reachable) → `write` (LLM or stub draft, then the code citation check below) → `file_case` (MCP: `create_or_update_case` to `pending_review`, urgent or routine) → end. The graph has no node that can approve or release. Intake and routing are rule-based; the LLM only words the draft and the farmer text.

## Citation check

Before a draft is filed for the officer, `src/agrireach/citation_check.py` (plain code, no model) checks it against the retrieved passages:

- Every number (with its unit if given, e.g. `2.5 cm`, `50kg`, `1,000`, `two weeks`) and every date (`15 March`, `March 15`, `mid-June`, `late July`) must appear in a passage cited for it. Figures attach to the next citation bracket; a figure with no citation, or a citation to a passage that was not retrieved, fails.
- A figure's limit counts too: "up to 5 cm" and "not deeper than 5 cm" are upper limits, "at least 50 kg" a lower limit, otherwise a plain value. A draft that swaps limits ("up to 5 cm but not deeper than 3 cm" for "recommended 3 cm; not deeper than 5 cm") or states a maximum as the recommendation fails.
- When code has detected that sources disagree (same claim, different sources), each source's figure must be stated with that source's own citation. A draft that merges the sources into one range or cites both for one figure fails. That was the task 10/11 failure.
- If the model's draft fails, it is regenerated once with the list of problems. If it fails again, the officer gets the verbatim passages instead, the case is marked urgent with `citation check failed: ...`, and the rejected draft is kept in the result for review. A failing draft is never filed as if it were clean, and nothing is released without officer approval either way.
- Retrieval is conflict-complete: if any passage on a claim is retrieved, every other source's passage on that claim is retrieved too, so a disagreement can't be hidden by ranking.

Sentences without figures are checked by `src/agrireach/claim_check.py`, through the same regenerate-then-fallback path:

- Named sources (code): a sentence that names a source ("IITA says…") must cite a passage from it.
- Agreement claims (code): "both sources agree…" must cite at least two sources, each of which backs the sentence on its own (its figures, or at least 60% of the sentence's content words). Calling a disagreement that code detected "agreement" fails.
- Support (code): a cited sentence must share at least one content word with the passages it cites. This catches an unrelated citation; it can't tell a paraphrase from a contradiction.
- Judge: a second model (`AGRIREACH_JUDGE_MODEL`, default `meta-llama/llama-3.3-70b-instruct`; use one different from the drafter) asked whether each sentence of a model draft is supported, including uncited sentences and lines addressed to the officer. It is always on (it cannot be switched off), so each model draft costs one extra model call. It uses `LLM_BASE_URL` and `LLM_API_KEY` unless `AGRIREACH_JUDGE_BASE_URL` and `AGRIREACH_JUDGE_API_KEY` are set. It fails closed: if the judge can't run or gives no verdict, the draft is rejected, the error is recorded on the case, and the officer gets the verbatim passages. Offline stub drafts quote passages verbatim and are not judged. The judge also checks the officer's farmer text at approval (see below).

Measured (EVALS "Latest"): on 69 recorded real drafts, the code layers reject 0 of 59 clean drafts and catch 5 known defects; the judge catches 5 more. Before place names were masked from the judge it also rejected 8 of 59 clean drafts (13.6%, mostly a recurring Kumasi draft); with masking and a prompt rule for partial statements it rejects 1 of 59. In live runs, false rejects caused 0 of 34 fallbacks with the judge off, 2 of 47 with it on before masking, and 0 of 51 with it on after (three runs).

Limits: figures are matched by a fixed word list next to each number. Uncited sentences are checked lexically against the passages the draft cites, except notes and lines about the reply's language, and all of them go to the judge. Without a judge (offline stub mode), an unsupported sentence that shares words with its passage passes (e.g. "mouldy maize is harmful to humans and animals" citing the aflatoxin-limit passage). False positives fail closed: the officer gets the verbatim passages and an urgent flag. See EVALS.

## Approval safety gate

When the officer approves, the exact farmer text is checked again before anything is released (`safety_gate.py`, `instruction_policy.py`, `approval.py`). There are four stops. S1 checks the whole text. S2 to S4 check each line, except lines copied from a cited source and the fixed referral and protective lines, which pass on provenance.

- S1: a cited pesticide passage needs its AEA consultation line, or a fixed referral line.
- S2: a line may not steer the farmer away from the officer or reverse label or glove advice.
- S3: no unsourced product, dose, vague material, spraying or repeat application.
- S4: no burning advice unless a cited source mentions burning.

Then the figures must match the cited sources (SOURCE_FIGURES), sources that disagree must be resolved by the officer (SOURCE_CONFLICT), text that isn't English is held for a reader of that language (LANGUAGE), and the judge reads the remaining lines (SOURCE_SUPPORT). The outcome is `pass`, `acknowledgement_required` (only for a non-critical judge concern), `assessment_unavailable` (the judge couldn't run; retry), `review_required` or `safety_blocked`. The last two can't be acknowledged: the officer must revise, reject or request info. The approval is bound to the exact text, sources, policy version and officer, and is checked again at release. Details are in [ARCHITECTURE.md](ARCHITECTURE.md).

## MCP implementation

`src/agrireach/mcp_server.py` is our own MCP server, built with the official Python SDK (FastMCP over stdio). The agent connects to it and to `mcp-server-fetch` as MCP clients. Every tool call is logged to the `tool_log` table, with actor, arguments, result summary and ok/blocked.

## MCP tools and servers

| Component | Purpose | Status |
|---|---|---|
| AgriReach Knowledge MCP server (ours) | Curated corpus + case actions | **Working** (tested over MCP stdio) |
| `search_guidance` | Search curated verbatim passages (soybean, maize) | **Working** |
| `get_crop_calendar` | Cited calendar activities; empty when no local reference | **Working** |
| `get_zone_planting_guidance` | Planting-window rows and national planting rules for the zone of a Ghana place, for the season asked (read-only) | **Working** (tested over MCP stdio) |
| `get_recent_rainfall` | Last 30 days of daily rainfall for a district (Open-Meteo model estimate, CC BY 4.0), rain days, missing days, provider, licence, retrieval time; cached; offline says "rainfall unavailable". Attached to planting and top-dressing cases as a cited record for the officer, plus an officer-only line with the figures; with only a region or no place, the officer line says why there is no record and to ask the farmer for the district. Never says onset has been reached or "rains are good, plant now" (draft and SMS are both checked) | **Working** (recorded-response tests; one live run on 25 Oct 2026, [docs/evidence/rainfall-live-2026-10-25.md](docs/evidence/rainfall-live-2026-10-25.md)) |
| `retrieve_reference` | One passage + source metadata; errors on unknown id | **Working** |
| `create_or_update_case` (acting tool) | File case as `draft`/`pending_review` only; `approved` is rejected. Returns the case's `created_at`, which the agent puts next to the cited planting windows as an officer-only fact ("Question received 25 Oct 2026. Windows cited: … The date is outside the cited windows."); no next window is inferred | **Working** |
| `mcp-server-fetch` (third-party, not ours) | Check that cited source pages are reachable | **Working** (needs `--allow-private-ips` on networks with fake-IP DNS; runs with `raw=true` because its HTML extractor failed on Node 20) |
| Weather forecast tool | Forecasts | Not built (`get_recent_rainfall` covers past rainfall only) |

**Status of other parts**

| Part | Status |
|---|---|
| LangGraph agent, stub drafting | **Working** |
| LLM drafting via open-weights model | **Working** with Mistral Small 3.2 24B (open weights) via OpenRouter. Every draft passes the citation check, and sentences without figures go through the claim check and the judge (`claim_check.py`; the original gap is EVALS task 12, runs C and E) |
| Citation check (dates, numbers and their limits vs cited passage) | **Working** (unit tests + real-model eval runs, 23 Oct; regeneration and fallback both exercised in run D) |
| Twi questions | **Partial**: detected and routed to the officer as urgent with a keyword gloss; no translation and no Twi replies |
| SQLite cases + officer gate + release block | **Working** (tests) |
| Approval safety gate (S1 to S4, figure, conflict, language and judge checks) | **Working** (tests, plus the strict replay of recorded live cases in CI) |
| CI | **Working**: GitHub Actions runs the offline suite, the strict safety replay, the legacy migration check and the speech tests |
| FastAPI + Streamlit | **Working** locally (API calls verified; UI page served, HTTP 200) |
| One-command run `./run.sh` from clean clone | **Working** (verified) |
| Deployment / public demo | Not done |

## Human in the loop workflow

No advice ever reaches a farmer without approval from a named extension officer. The agent drafts, and the officer decides. Every draft advisory enters a review queue. Risk and uncertainty only set its priority: cases where sources conflict, the location or crop context is missing, confidence is low, or advice could have material consequences go to the urgent queue, and all other cases go to the routine queue. The extension officer can review the original question, retrieved references and draft advisory. The reason for an urgent flag is in the case record (`urgent_reasons` in `GET /officer/cases/{id}`); the officer screen lists urgent cases first but does not show the reason yet. The officer can approve, edit, reject, or request more information, and each decision is recorded with the officer's name and a timestamp. Approval covers the exact text the farmer receives: the officer sees the cited draft and a short plain-language farmer version, can edit either, and the approved farmer text is what is sent. The agent must not autonomously prescribe hazardous chemical use or present a suspected plant disease as a confirmed diagnosis.

## Development roadmap

Done (13 Oct): verified corpus, MCP server, LangGraph agent, case DB and gate, API/UI, tests, evals in stub mode and with an open-weights model.
Done (23 Oct): citation check for dates and numbers, conflict-complete retrieval, Twi detection and officer routing (EVALS tasks 10-12).
Done (23 Oct, review): the check also compares each figure's limit ("not deeper than", "up to", "at least"), so swapped bounds fail.
Done (25 Oct): 14 field-evidence evals (EVALS F1-F14) from public reports, verified maize and aflatoxin passages, routing of uncovered crops and contact requests to the officer.
Done (25 Oct): claim check for sentences without figures (named sources, agreement claims, lexical support) and a separate judge model (optional at first, now always on), with measured false-reject rates.
Done (25 Oct, local only): voice-note channel. A voice note or text with a sender id goes through local speech-to-text (faster-whisper) into a case; the officer-approved answer goes back through the same channel as text, optionally with a Piper voice. A local simulator (CLI and Streamlit tab) stands in for the phone. A WhatsApp Cloud API adapter exists as code only, off by default and never registered or deployed. See [docs/voice-channel.md](docs/voice-channel.md) and [docs/whatsapp-setup.md](docs/whatsapp-setup.md).
Done (25 Oct, local only): an SMS adapter for Africa's Talking, code only and off by default. There is no account, it has only been tested against mocked responses, and it has never sent or received a real SMS. Over-long texts are refused for the officer to shorten, never cut. See [docs/sms-setup.md](docs/sms-setup.md).
Done (25 Oct, local only): farmer-facing reply (the officer approves the exact plain text that is sent; citations stay in the officer view), place-name confirm-back after speech-to-text using a gazetteer of Ghana's 261 districts, first-contact consent, STOP and a retention purge.

Done (26 Oct): approval safety gate (S1 to S4, the repeat rule, figure, conflict, language and judge checks), officer sign-in tokens, immutable approvals bound to the exact text, single-claim delivery jobs, and CI.

Next: test speech-to-text on real, consented voice notes, record the demo video, then consider a forecast tool and real Twi support with native-speaker review.

## Limitations

- No public deployment yet; the MVP runs locally only.
- Coverage is limited to the curated documents: Northern Ghana soybean and maize, maize planting windows for every agroecological zone, plus the national maize aflatoxin limit. The district-to-zone map (`data/zones.json`) is approximate and not yet checked by an extension officer.
- Rainfall is a model estimate for one point per district (Open-Meteo), not a gauge reading, and the guides give no rainfall amount for onset, so AgriReach shows the record and the officer decides. Open-Meteo's free API is for non-commercial use only. Other crops, prices and contact details are always passed to the officer.
- The quality of recommendations depends on the authority and freshness of source material.
- Text based advice may not be enough to diagnose a plant health issue.
- Voice notes: speech-to-text was tested on synthetic US-English clips and on 10 Ghanaian broadcast-English clips (run S1: 52.5% word error rate with Whisper "base", language mis-detected in 7/10; all 10 flagged for the officer). It is not tested on real farmer voice notes, and Whisper does not support Twi, Dagbani or Wali; such notes are flagged for the officer to listen to. Misheard place names ("Wa" -> "war") are confirmed back with the farmer, not corrected silently. The consent wording has had no legal review. The WhatsApp and SMS adapters have never sent or received a real message.
- Twi support is detection plus a keyword gloss only: AgriReach cannot translate or reply in Twi, so Twi cases go to the officer as urgent. Other local languages are not handled. Offline access and accessibility require further work.
- The citation check confirms that every date and number in a draft, and any limit on it ("up to", "not deeper than", "at least"), appears in the passage it cites. Sentences without figures get code checks (named sources, agreement claims, at least one shared word) and a judge model that fails closed; without it (offline stub mode), a sentence that shares words with its passage but says something the passage doesn't will pass.
- The repeat rule (`instruction_policy.REPEAT`) is a word list. A repeat line ("Apply twice a week.") is held unless copied word for word from the cited source, and the officer can't acknowledge the hold. It misses lines with no apply, spray or treat word ("Put more on after a week.", "Go over the field twice."), "Apply now and next week.", "Apply through the season.", "Keep applying through the season." and "once at … and once at …" ("Apply once at dawn and once at dusk."). The officer must rewrite its over-holds: "Apply compost each season." and "Apply the first dose at planting and the second dose at 6 weeks." ("Apply once at planting and once at 6 weeks." passes). The judge and the officer are the check on its misses.
- A line that says to spray is blocked even when it limits spraying ("Spray only once, in the evening."); the officer rewrites it.
- An officer can record a blank note on a case that was not delivered (only cases waiting for review need a note).
- Past rainfall from Open-Meteo was checked in one live run (25 Oct 2026). There is no weather forecast.
- In offline stub mode there is no judge, so approving a line that isn't a source quote, a fixed line or a greeting returns "assessment unavailable" until a model is configured.
- The system is decision support and does not replace qualified agricultural advice.

## Future improvements

- Validate the MVP with agricultural extension officers and farmers.
- Add carefully evaluated local language support.
- Add image based crop issue triage only after collecting suitable validation data.
- Add low bandwidth and offline friendly interaction.
- Expand beyond soybean and maize after evaluating the current workflow.
- Add monitoring for follow up cases and referral outcomes.
- Evaluate factual grounding, escalation quality, response time, and farmer usability.

## Evaluation plan

The prototype should be evaluated on whether it retrieves relevant evidence, cites the source used, asks for missing context, abstains when evidence is insufficient, sends every draft to officer review, flags risky cases as urgent, and records a traceable case history. Results from real runs (stub and open-weights LLM) are in [EVALS.md](EVALS.md). Performance claims will only be added after tests or user evaluation support them.

## Repository structure

```text
src/agrireach/
  agent.py            LangGraph agent: intake, clarify, retrieve, check_sources, write, file_case
  mcp_server.py       our Agricultural Knowledge MCP server (FastMCP, stdio)
  knowledge.py        read-only access to data/knowledge.json
  zones.py            agroecological zone of a Ghana place, and which passages apply there
  places.py           Ghana regions, districts and capitals (data/gazetteer.json)
  rainfall.py         past-30-days rainfall record for a district (Open-Meteo by default)
  season.py           the question's received date next to the cited planting windows
  llm.py              draft writer: open-weights model, or the offline stub
  citation_check.py   every date and number must appear in the passage it cites
  claim_check.py      sentences without figures: named sources, agreement claims, word overlap, judge
  judge.py            second-model judge; always on, fails closed
  farmer_reply.py     the plain farmer-facing text the officer approves
  safety_gate.py      deterministic approval gate (S1 chemical safeguard, S2, S3, S4, LANGUAGE); POLICY_VERSION
  instruction_policy.py  the hard-stop word lists: unsourced input, REPEAT, skips officer, burning
  approval.py         approval assessment, binding, immutable approvals and release
  delivery.py         atomic delivery claims; unknown outcomes are never retried automatically
  db.py               SQLite case store, officer tokens and the approval gate entry points
  migrations.py       versioned SQLite upgrades
  language.py         Twi detection and keyword gloss (not a translator)
  voice_script.py     short spoken script for an approved answer
  api.py              FastAPI backend
  ui.py, ui_feedback.py  Streamlit farmer and officer screens, and plain workflow messages
  evalset.py          field-evidence eval set loading and routing checks
src/agrireach/channels/
  base.py  service.py  simulator.py  stt.py  tts.py  location.py  retention.py
  whatsapp.py  sms.py   (both code only, off by default)
scripts/
  add_officer.py              register an officer and print their sign-in token once
  run_evals.py                run the EVALS task set against the real agent and MCP servers
  verify_corpus.py            check every passage appears verbatim in its source document
  replay_safety.py            deterministic replay of recorded live cases through the gate (CI, --strict)
  verify_legacy_migration.py  upgrade a legacy fixture copy and verify preserved data (CI)
  cache_speech_models.py      download pinned public speech models (CI speech job)
  replay_drafts.py            replay recorded real-model drafts through the citation and claim checks
  replay_retrieval.py         replay recorded eval questions through the agent in stub mode
  officer_regrade.py          build the officer re-grade pack for the field-evidence questions
  stt_ghana_check.py          speech-to-text check on Ghanaian-accented English clips
  verify_ui_browser.py        opt-in Chromium acceptance check against a synthetic demo database
data/knowledge.json   verbatim cited passages (APNI/CSIR-SARI 2023 soybean and maize guides, IITA SSPiNG 2022,
                      IITA 2025 maize guide, MoFA Maize Production Guide, Agbetiameh et al. 2018)
data/                 zones.json, gazetteer.json, district_coords.json (see Credits)
evals/                field_evidence.json: eval questions F1-F14 with sources and expected routing
tests/                pytest suite (offline stub mode)
docs/                 workflow, data sources, safety testing and decisions, voice, SMS and WhatsApp setup,
                      rainfall plan, recorded eval runs; dated evidence in docs/evidence/
.github/workflows/    regression.yml: CI
run.sh  Makefile  requirements.txt  requirements-voice.txt  .env.example  EVALS.md  ARCHITECTURE.md
```

## Credits

AgriReach quotes short, attributed extracts from these sources. Each passage in `data/knowledge.json` names its source, and [docs/data-sources.md](docs/data-sources.md) gives the licences and links.

- **MoFA:** *Maize Production Guide*, Ministry of Food and Agriculture, Ghana, Directorate of Agricultural Extension Services (DAES), © 2020. The guide names no authors. Its acknowledgement thanks the MoFA staff who reviewed and edited it (Dr. Solomon Gyan, Theophilus Osei Owusu, Michael Owusu, Paul Siameh, Paulina Addy, Emmanuel A. Odame, Esther Agyekum, Collins Oppong, Daniel Ninson, Kwesi Abaka-Quansah, Hannah Serwaa Nuamah, John Lovelace Kpodoviah, Prosper Akpablah and Portia Tandoh). The guide allows short extracts in non-advertising, non-profit contexts with the source acknowledged.
- **APNI and CSIR-SARI:** *Soybean Cropping Guide* and *Maize Cropping Guide: 4R Nutrient Management and Best Agronomic Practices, Northern Ghana* (African Plant Nutrition Institute and CSIR-Savanna Agricultural Research Institute, 2023; maize guide by S. Njoroge, A. Haruna, A. M. Mohammed, A.L.A. Aziz and S. Zingore). CC BY 4.0.
- **IITA:** *Guide for sustainable maize production in Ghana* (N. Abdul Rahman, B. Kotu, A. Ortega-Beltran, S. Adjei-Nsiah, D. Agbetiameh and S.S.J. Buah; IITA, 2025), CC BY 4.0. *Training Manual on GAPs for Sustainable Intensification of Soyabean Production for Agricultural Extension Agents* (M. Kermah, S. Adjei-Nsiah and A. Ofosu; IITA Ghana SSPiNG project, 2022), short attributed extracts.
- **Agbetiameh et al. 2018:** *Prevalence of Aflatoxin Contamination in Maize and Groundnut in Ghana*, Plant Disease, doi:10.1094/PDIS-05-17-0749-RE. CC BY 4.0.
- **Open-Meteo:** rainfall data, "Weather data by Open-Meteo.com", CC BY 4.0. The free API is for non-commercial use only.
- **NASA POWER:** the optional rainfall cross-check (off by default).
- **GeoNames** (CC BY 4.0) and **OpenStreetMap** contributors (ODbL 1.0): district coordinates in `data/district_coords.json`.
- **Wikipedia**, "Districts of Ghana" (CC BY-SA 4.0): place names in `data/gazetteer.json`.

## Build window integrity

The design documents were prepared earlier. The application code was written from 13 October 2026, after the organiser confirmed the submission deadline (15 Oct 2026, 23:59 EAT). Commit timestamps are real.

## Licence

This project is released under the MIT License (see [LICENSE](LICENSE)). Do not add third party datasets or documents unless their licence permits the intended use.
