"""LangGraph orchestration. All tool use goes through MCP clients:
  - own server: agrireach.mcp_server (search_guidance, get_crop_calendar, get_zone_planting_guidance,
    retrieve_reference, create_or_update_case)
  - third-party server: mcp-server-fetch (reference MCP server, not written by us) to check cited source pages are reachable.
The graph ends after filing the case as pending_review. It has no path to approve or release.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from datetime import datetime
from contextlib import AsyncExitStack
from dataclasses import asdict
from typing import TypedDict

from langgraph.graph import END, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agrireach import citation_check, claim_check, farmer_reply, knowledge, language, llm, places, rainfall, season, zones

RISK_TERMS = {
    "chemical": ["spray", "herbicide", "pesticide", "insecticide", "fungicide", "chemical", "glyphosate", "paraquat",
                 "atrazine", "dose", "poison"],
    "disease_or_pest": ["disease", "yellow", "spots", "wilting", "dying", "rot", "insects", "pest", "caterpillar",
                        "worms", "leaves turning", "armyworm", "army worm", "weevil", "borer", "larvae", "turning black"],
    "food_safety": ["mould", "mold", "aflatoxin", "fungus"],
}
# A farmer asking how to reach an officer: AgriReach holds no contact details, so the officer answers.
CONTACT_RE = re.compile(r"\bwho\s+(?:should|can|do|could)\s+i\s+(?:call|contact|phone|see|talk\s+to|ask)\b"
                        r"|\b(?:phone|contact)\s+(?:number|details)\b|\bno\s+extension\s+(?:officer|agent)\b", re.I)
# "two months after planting" dates an event; it does not ask about planting, so it should not trigger the
# region clarification. Nor does "when" used as a conjunction ("arrived when the maize is knee-high").
AFTER_PLANTING = re.compile(r"\b(?:after|since)\s+(?:planting|sowing)\b")
ASKS_WHEN = re.compile(r"^\W*when\b|\bwhen\s+(?:should|can|could|do|does|is|to|will|must)\b")
# Questions about when or how to plant get the farmer's zone's planting windows ("when to harvest" does not).
PLANTING_Q = re.compile(r"\b(?:plant|planting|sow|sowing)\b", re.I)
# Top dressing depends on soil moisture ("if the soil is very dry, delay"), so it gets the rainfall record too.
TOPDRESS_Q = re.compile(r"\btop[\s-]?dress(?:ing|ed)?\b", re.I)
# Code-built lines added to the officer draft after the checks; never part of the farmer SMS.
OFFICER_FACT = "Note: (officer only)"
REGION_DEPENDENT = {"planting", "spacing", "seed"}
NORTHERN = ["northern", "north", "tamale", "savannah", "upper east", "upper west", "north east", "bolgatanga",
            "wa", "yendi", "nyankpala", "damongo", "walewale"]
# One model draft plus one regeneration with the citation check's feedback; then fall back to verbatim passages.
MAX_DRAFT_ATTEMPTS = 2
# Cap on the citation-check problems copied into an urgent reason, so the officer's queue stays readable
# (the full list is kept in the result's citation_check.attempts).
MAX_REASON_CHARS = 600
OTHER_REGIONS = ["brong ahafo", "brong-ahafo", "ashanti", "kumasi", "volta", "accra", "greater accra", "eastern", "western", "central", "bono",
                 "ahafo", "oti", "cape coast", "takoradi", "ho", "adaklu"]


def _place_in_question(place: str, q: str) -> bool:
    """Match a place name as a whole token (or contiguous phrase), not a substring of another word."""
    place = place.strip().lower()
    if not place:
        return False
    if " " in place:
        return place in q
    return re.search(rf"(?<![a-z0-9]){re.escape(place)}(?![a-z0-9])", q) is not None


def _is_northern(region: str) -> bool:
    """True if the region is covered by the Northern Ghana corpus (whole-token match, so 'Kwahu' is not 'Wa')."""
    if any(_place_in_question(n, region.lower()) for n in NORTHERN):
        return True
    g = places.gazetteer().get(region.strip().lower())  # any of Ghana's 261 districts, regions or their capitals
    return bool(g and places.is_northern(g["region"]))


def _fit_to_zone(passages: list[dict], zone: dict | None, season: str) -> list[dict]:
    """Keep the farmer's zone's guidance. A passage for other zones is dropped only when a passage on the same topic
    written for the farmer's zone is present (so nothing is silently lost); window rows for the season not asked are
    dropped."""
    if season:
        passages = [p for p in passages if not p.get("season") or p["season"] == season]
    if not zone:
        return passages
    local_topics = {p["topic"] for p in passages if zones.covers(p, zone["zones"]) and zones.zone_specific(p)}
    return [p for p in passages if zones.covers(p, zone["zones"]) or p["topic"] not in local_topics]


def _same_figures(group: list[dict]) -> bool:
    """True if every passage states exactly the same figures and dates (e.g. MoFA "End of March-end of April" and
    IITA "End of March - End of April"): different sources, same advice, so not a conflict for the officer."""
    sets = {frozenset(f.value for f in citation_check.extract_figures(p["text"])) for p in group}
    return len(sets) == 1 and bool(next(iter(sets)))


async def _attach_rainfall(tools, region: str, zone: dict | None, passages: list, notes: list, facts: list) -> dict:
    """Planting and top-dressing questions: the district's rainfall record (MCP get_recent_rainfall) as a citable
    record for the officer, never as guidance. No district or unavailable -> an officer fact saying why, no claim."""
    if not region:
        why = "the question names no district; ask the farmer which district they farm in"
    elif not (zone and zone.get("district")):
        why = (f"rainfall is looked up per district and '{region.title()}' is not a district AgriReach knows; ask the "
               "farmer which district they farm in")
    else:
        why = ""
    if why:
        facts.append(f"{OFFICER_FACT} No rainfall record: {why}.")
        return {"available": False, "reason": f"rainfall unavailable: {why}"}
    try:
        rain = await tools.call("get_recent_rainfall", {"district": region})
    except Exception as e:
        rain = {"available": False, "reason": f"rainfall unavailable: {str(e)[:120]}"}
    if rain.get("available"):
        passages.append(rainfall.as_passage(rain, zone["zone"]))
        notes.append("A rainfall record is attached for the officer. The guides give no rainfall amount that marks "
                     "onset, so AgriReach does not say whether the guides' condition is met; the officer decides.")
        p = rain["period"]
        facts.append(f"{OFFICER_FACT} Rainfall record [{rain['record_id']}] for {rain['district']}, {p['start']} to "
                     f"{p['end']}: {rain['rain_days']} rain days (at least {rain['threshold_mm']:g} mm), "
                     f"{rain['total_mm']:g} mm in total, {rain['missing_days']} days missing ({rain['provider']}). "
                     f"{rain['caveat']}")
    else:
        facts.append(f"{OFFICER_FACT} Rainfall unavailable ({rain.get('reason', '').removeprefix('rainfall unavailable: ')}); "
                     "no claim about recent rain is made.")
    return rain


def _crops_covered() -> list[str]:
    """Crops in the corpus. Empty if the corpus can't be read; retrieval then reports the tool error itself."""
    try:
        return knowledge.crops_covered()
    except Exception:
        return []


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _crop_pattern(crop: str) -> str:
    """Regex used to confirm a fetched source page is about the passage's crop."""
    return r"soy(a)?bean" if crop == "soybean" else re.escape(crop)


def _detect_region(q: str) -> str:
    # Longer names first so "upper west" wins over "west" if both ever listed.
    for r in sorted(NORTHERN + OTHER_REGIONS, key=lambda s: (-len(s), s)):
        if _place_in_question(r, q):
            return r.strip()
    found = places.find(q)  # fall back to the full gazetteer (e.g. "Lawra", "Sawla", "Techiman")
    return found[0]["name"].lower() if found else ""


class S(TypedDict, total=False):
    question: str
    crop: str
    region: str
    case_id: int
    passages: list
    calendar: list
    urgent_reasons: list
    notes: list
    farmer_draft: dict
    clarification: str
    draft: str
    draft_mode: str
    language: str
    search_query: str
    skip_retrieval: bool
    extra_urgent_reasons: list
    conflicts: dict
    zone: dict
    zone_mismatch: bool
    mismatch_zones: str
    rainfall: dict
    officer_facts: list
    received: str
    season_prompt: str
    citation_check: dict
    source_checks: list
    status: str
    errors: list


def _server_params(own_only=False):
    env = {**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..")}
    own = StdioServerParameters(command=sys.executable, args=["-m", "agrireach.mcp_server"], env=env)
    fetch_args = ["-m", "mcp_server_fetch"] + os.getenv("FETCH_MCP_ARGS", "").split()
    fetch = StdioServerParameters(command=sys.executable, args=fetch_args, env=env)
    return own, fetch


class Tools:
    """Holds the MCP client sessions for one agent run."""

    def __init__(self, own: ClientSession, fetch: ClientSession | None):
        self.own, self.fetch = own, fetch

    async def call(self, name: str, args: dict):
        res = await asyncio.wait_for(self.own.call_tool(name, args), timeout=float(os.getenv("MCP_TIMEOUT", "20")))
        text = res.content[0].text if res.content else ""
        if res.isError:
            raise RuntimeError(f"{name} failed: {text}")
        return json.loads(text)


def build_graph(tools: Tools):
    async def intake(s: S) -> S:
        q = s["question"].lower()
        lang = "twi" if language.is_twi(s["question"]) else "en"
        search_query = s["question"]
        reasons = list(s.get("extra_urgent_reasons") or [])
        if lang == "twi":
            gl = language.gloss(s["question"])
            search_query = f"{gl} {s['question']}".strip()
            q = f"{gl} {q}"
            reasons.append("question appears to be in Twi: officer must confirm the meaning and reply in Twi "
                           f"(AgriReach keyword gloss, not a translation: '{gl or 'none'}')")
        crop = (s.get("crop") or language.detect_crop(q)).lower()
        covered = _crops_covered()
        region = s.get("region") or ""
        if not region:
            region = _detect_region(q)
        reasons += [f"{k.replace('_', ' ')} terms in question" for k, terms in RISK_TERMS.items()
                    if any(t in q for t in terms)]
        contact = bool(CONTACT_RE.search(q))
        uncovered = bool(crop and covered and crop not in covered)
        if uncovered:
            reasons.append(f"crop '{crop}' is not covered by the curated sources (covered: {_join(covered)}); "
                           "officer must answer")
        if contact:
            reasons.append("farmer asks how to reach an extension officer: officer should reply with local contact "
                           "details (AgriReach holds none)")
        topics = {w for w in re.findall(r"[a-z]+", AFTER_PLANTING.sub(" ", q))} - {"when"}
        if ASKS_WHEN.search(q):
            topics.add("when")
        clar = ""
        if not crop and not contact:
            clar = f"Which crop is this about? AgriReach currently covers {_join(covered or ['soybean'])} only."
        elif crop and not uncovered and not region and topics & {"plant", "planting", "sow", "when", "spacing",
                                                                   "seed", "seeds"}:
            clar = "Which district or region is your farm in? Planting guidance differs by region."
        if clar and lang == "twi":
            # Never answer a Twi speaker with an English question: route the case to an officer instead.
            reasons.append(f"could not ask the farmer a clarifying question in Twi; officer should ask: {clar}")
            clar = ""
        elif clar and s.get("extra_urgent_reasons"):
            # The question itself may be wrong (e.g. an unreliable voice-note transcript): don't ask the farmer an
            # automatic question about it; the officer checks first.
            reasons.append(f"no automatic clarifying question because of the flags above; officer should ask: {clar}")
            clar = ""
        case = await tools.call("create_or_update_case", {"status": "draft", "question": s["question"], "crop": crop,
                                                          "region": region})
        return {"crop": crop, "region": region, "urgent_reasons": reasons, "clarification": clar, "language": lang,
                "search_query": search_query, "case_id": case["case_id"], "notes": [], "errors": [],
                "received": case.get("created_at", ""),
                "skip_retrieval": uncovered or (contact and not crop)}

    async def retrieve(s: S) -> S:
        errors, notes, reasons = list(s["errors"]), list(s["notes"]), list(s["urgent_reasons"])
        region = s["region"]
        zone = zones.zone_for(region) if region else None
        if zone is None and region and _is_northern(region):
            zone = zones.zone_for("northern ghana")
        if region and zone is None:
            reasons.append(f"no local reference for region '{region}' (agroecological zone unknown; corpus covers "
                           "Northern Ghana only for most topics)")
            notes.append(f"AgriReach does not know which agroecological zone {region} is in; officer should confirm.")
        elif zone and zone["boundary"] and zone["district"]:
            notes.append(f"{region.title()} is near the edge of the {zones.label(zone['zone'])} zone (AgriReach's "
                         "approximate zone map): officer should confirm which zone's timing applies.")
        passages, cal = [], []
        if s.get("skip_retrieval"):
            # Uncovered crop or a contact request: searching another crop's guidance would only mislead.
            reasons.append("no grounded evidence found in corpus")
            return {"passages": [], "calendar": [], "errors": errors, "notes": notes, "conflicts": {},
                    "zone": zone, "zone_mismatch": False, "urgent_reasons": sorted(set(reasons), key=reasons.index)}
        query = s.get("search_query") or s["question"]
        try:
            passages = await tools.call("search_guidance", {"query": s.get("search_query") or s["question"],
                                                             "crop": s["crop"] or "soybean", "region": ""})
            verified = []
            for p in passages:
                verified.append(await tools.call("retrieve_reference", {"passage_id": p["id"]}))
            passages = verified
            if zone and PLANTING_Q.search(query):
                # The farmer's own zone's planting windows (verbatim table rows), whatever the keyword search found.
                got = await tools.call("get_zone_planting_guidance", {"crop": s["crop"] or "soybean", "place": region,
                                                                       "season": zones.detect_season(query)})
                have = {p["id"] for p in passages}
                passages += [p for p in got["passages"] if p["id"] not in have]
            if re.search(r"\b(when|calendar|season)\b", query.lower()):
                cal = await tools.call("get_crop_calendar", {"crop": s["crop"] or "soybean", "region": "northern"})
        except Exception as e:  # tool failure: never invent results
            errors.append(str(e))
            passages = []
            reasons.append("tool error during retrieval")
        if not passages and not errors:
            reasons.append("no grounded evidence found in corpus")
        passages = _fit_to_zone(passages, zone, zones.detect_season(query))
        mismatched = [p for p in passages if region and (zone is None or not zones.covers(p, zone["zones"]))]
        where = ""
        if zone and mismatched:
            where = _join(sorted({zones.label(z) for p in mismatched for z in p.get("zones") or zones.NORTHERN_ZONES}))
            if all(set(p.get("zones") or zones.NORTHERN_ZONES) <= zones.NORTHERN_ZONES for p in mismatched):
                where = ""  # Northern Ghana guides: the standing Northern Ghana caution applies
                reasons.append(f"no local reference for region '{region}' ({zones.label(zone['zone'])} zone; corpus "
                               "covers Northern Ghana only for this question)")
                notes.append(f"The curated sources are for Northern Ghana; they may not apply in {region}.")
            else:
                reasons.append(f"no local reference for region '{region}' ({zones.label(zone['zone'])} zone; the "
                               f"passages found are for the {where} zone)")
                notes.append(f"The passages found are for the {where} zone; they may not apply in {region}.")
        by_key: dict = {}
        for p in passages:
            for k in knowledge.claim_keys(p):
                by_key.setdefault(k, []).append(p)
        conflicts = {}
        for k, group in by_key.items():
            srcs = {p["source_id"] for p in group}
            if len(srcs) > 1 and not _same_figures(group):
                conflicts[k] = group
                reasons.append(f"sources differ on {k.replace('_', ' ')}: {', '.join(sorted(srcs))}")
                notes.append(f"Sources give different figures for {k.replace('_', ' ')}; officer should choose.")
        rain, facts = None, []
        topdress = TOPDRESS_Q.search(query) or any("topdress" in p.get("claim_key", "") for p in passages)
        if (PLANTING_Q.search(query) or topdress) and passages and not errors:
            rain = await _attach_rainfall(tools, region, zone, passages, notes, facts)
        season_prompt = ""
        if PLANTING_Q.search(query) and s.get("received"):
            received = datetime.fromisoformat(s["received"]).date()
            if fact := season.fact(received, passages):
                facts.insert(0, f"{OFFICER_FACT} {fact}")
            if season.outside(received, passages):
                season_prompt = season.prompt(received)
        if s.get("language") == "twi":
            notes.append("The farmer wrote in Twi. This draft is in English for the officer, who must reply in Twi.")
        if any(p.get("risk") == "chemical" for p in passages) or any("chemical" in r for r in reasons):
            notes.append("Chemical use: AgriReach does not recommend products or doses. Refer to the label and the officer.")
        if any("disease" in r for r in reasons):
            notes.append("Possible pest/disease: this is not a diagnosis. Officer should inspect or refer.")
        if any("food safety" in r for r in reasons):
            notes.append("Possible food-safety risk (mould/aflatoxin): AgriReach cannot clear produce for sale, food "
                         "or feed. Officer should advise.")
        return {"passages": passages, "calendar": cal, "errors": errors, "notes": notes, "conflicts": conflicts,
                "zone": zone, "zone_mismatch": bool(mismatched), "mismatch_zones": where, "rainfall": rain,
                "officer_facts": facts, "season_prompt": season_prompt,
                "urgent_reasons": sorted(set(reasons), key=reasons.index)}

    async def check_sources(s: S) -> S:
        checks = []
        if tools.fetch is None or not s["passages"]:
            return {"source_checks": checks}
        seen = set()
        for p in s["passages"]:
            src = p["source"]
            if p["source_id"] in seen or p.get("kind") == "record":  # a data record, not a guide page
                continue
            seen.add(p["source_id"])
            try:
                r = await asyncio.wait_for(tools.fetch.call_tool("fetch", {"url": src["landing_url"], "max_length": 20000,
                                                                          "raw": True}), timeout=30)
                body = r.content[0].text if r.content else ""
                ok = (not r.isError) and bool(re.search(_crop_pattern(p.get("crop") or "soybean"), body, re.I))
                checks.append({"source_id": p["source_id"], "url": src["landing_url"], "reachable": ok,
                               "detail": "" if ok else body[:160]})
            except Exception as e:
                checks.append({"source_id": p["source_id"], "url": src["landing_url"], "reachable": False,
                               "detail": f"fetch error: {e}"[:160]})
        return {"source_checks": checks}

    async def write(s: S) -> S:
        """Draft, then run the code citation check. One regeneration with the check's feedback; if the model still
        fails, the officer gets the verbatim passages instead and the case is flagged urgent. Never silent."""
        notes = list(s["notes"])
        reasons = list(s["urgent_reasons"])
        if s["errors"]:
            notes.append("A tool failed during retrieval; no guidance is shown rather than guessing.")
        conflicts = s.get("conflicts") or {}
        attempts = []
        feedback = None
        text, used = "", ""
        for _ in range(MAX_DRAFT_ATTEMPTS):
            try:
                text, used = llm.draft(s["question"], s["passages"], notes, conflicts=conflicts, feedback=feedback)
            except Exception as e:
                text, used = llm.stub_draft(s["question"], s["passages"], notes + [f"LLM call failed: {e}"]), "stub(llm-error)"
            # Only the code-built stub has trusted "Note:" lines (system notes such as an error message). A model
            # draft is checked in full, so it cannot slip an unchecked figure past the check behind "Note:".
            skip = ("Note:", llm.STUB_LABEL) if used.startswith("stub") else ()
            res = citation_check.check_draft(text, s["passages"], conflicts, ignore_prefixes=skip)
            # Sentences without figures: named sources, agreement claims, lexical support, model judge (always on, fails closed).
            # The code-built stub quotes passages verbatim, so it is not sent to the judge.
            claims = claim_check.check_claims(text, s["passages"], conflicts, ignore_prefixes=skip,
                                              judge=False if used.startswith("stub") else None)
            problems = res.problems + claims.problems + rainfall.draft_problems(text)
            attempts.append({"draft_mode": used, "ok": not problems, "problems": problems,
                             "figures_checked": res.checked, "sentences_checked": claims.checked,
                             **({"judge": {k: v for k, v in claims.judge.items() if k != "raw"}} if claims.judge else {})})
            if not problems or used.startswith("stub") or claims.judge_failed:
                break  # regenerating can't help when the source check itself couldn't run
            feedback = problems
        check = {"ok": attempts[-1]["ok"], "attempts": attempts}
        if not check["ok"]:
            rejected = text
            text = llm.stub_draft(s["question"], s["passages"], notes + [
                "The model draft failed the citation check, so the verbatim passages are shown instead."])
            used = f"stub(citation-check-fallback after {used})"
            check["rejected_draft"] = rejected
            reasons.append("citation check failed: " + "; ".join(attempts[-1]["problems"])[:MAX_REASON_CHARS])
        region = s.get("region") or ""
        if region and s.get("zone_mismatch"):
            # Added by code, not left to the model, and in offline mode too: name where the guidance is from.
            if s.get("mismatch_zones"):
                here = f" ({zones.label(s['zone']['zone'])} zone)" if s.get("zone") else ""
                caution = (f"Caution: some of the guidance below is from sources for the {s['mismatch_zones']} zone "
                           f"and may not apply in {region.title()}{here}; the officer should confirm local timing.")
            else:
                caution = (f"Caution: the curated sources cover Northern Ghana only. The guidance below comes from them "
                           f"and may not apply in {region.title()}; the officer should confirm local timing.")
            if text.startswith(llm.STUB_LABEL):  # keep the offline label first so the draft stays recognisable
                label, _, rest = text.partition("\n")
                text = f"{label}\n{caution}\n{rest}"
            else:
                text = f"{caution}\n\n{text}"
        if s.get("officer_facts"):  # code-built facts (date vs windows, rainfall), after the checks like the caution
            text = text.rstrip() + "\n\n" + "\n".join(s["officer_facts"])
        return {"draft": text, "draft_mode": used, "citation_check": check,
                "urgent_reasons": sorted(set(reasons), key=reasons.index)}

    async def file_case(s: S) -> S:
        reasons = s["urgent_reasons"]
        conflicts = any(n.startswith("Sources give different figures") for n in s.get("notes", []))
        # Keyed on the zone_mismatch flag, not on the caution's wording.
        caveat = (farmer_reply.zone_caveat(s["region"], s.get("mismatch_zones") or "")
                  if s.get("region") and s.get("zone_mismatch") else None)
        officer_text = "\n".join(l for l in s["draft"].splitlines() if not l.startswith(OFFICER_FACT))
        fd = farmer_reply.propose(officer_text, s["question"], s.get("language", "en"), conflicts=conflicts,
                                  zone_caveat=caveat)
        if fd.text and (go := rainfall.draft_problems(fd.text)):
            # Never "rains are good, plant now" in the SMS: withhold it and let the officer write it.
            fd.text, fd.needs_officer_text = "", True
            fd.problems = list(fd.problems) + [f"proposed SMS withheld: {'; '.join(go)}"]
        if s.get("season_prompt"):  # an approval prompt like "sources differ"; never SMS text
            fd.problems = list(fd.problems) + [s["season_prompt"]]
        # season_prompt is stored with the proposal so a re-proposed SMS (api.py) keeps the prompt.
        stored = asdict(fd) | ({"season_prompt": s["season_prompt"]} if s.get("season_prompt") else {})
        r = await tools.call("create_or_update_case", {
            "status": "pending_review", "case_id": s["case_id"], "draft": s["draft"],
            "source_ids": [p["id"] for p in s["passages"]], "priority": "urgent" if reasons else "routine",
            "urgent_reasons": reasons, "farmer_draft": json.dumps(stored, ensure_ascii=False)})
        return {"status": r["status"], "farmer_draft": stored}

    async def clarify(s: S) -> S:
        return {"status": "draft", "draft": s["clarification"], "draft_mode": "rule"}

    g = StateGraph(S)
    for name, fn in [("intake", intake), ("retrieve", retrieve), ("check_sources", check_sources),
                     ("write", write), ("file_case", file_case), ("clarify", clarify)]:
        g.add_node(name, fn)
    g.set_entry_point("intake")
    g.add_conditional_edges("intake", lambda s: "clarify" if s["clarification"] else "retrieve")
    g.add_edge("retrieve", "check_sources")
    g.add_edge("check_sources", "write")
    g.add_edge("write", "file_case")
    g.add_edge("file_case", END)
    g.add_edge("clarify", END)
    return g.compile()


async def run(question: str, crop: str = "", region: str = "", use_fetch: bool | None = None,
              extra_urgent_reasons: list[str] | None = None) -> dict:
    """extra_urgent_reasons: reasons found before the agent ran (e.g. an unreliable voice-note transcript)."""
    if use_fetch is None:
        use_fetch = os.getenv("AGRIREACH_SOURCE_CHECK", "1") == "1"
    own_p, fetch_p = _server_params()
    async with AsyncExitStack() as st:
        r, w = await st.enter_async_context(stdio_client(own_p))
        own = await st.enter_async_context(ClientSession(r, w))
        await own.initialize()
        fetch = None
        if use_fetch:
            try:
                fr, fw = await st.enter_async_context(stdio_client(fetch_p))
                fetch = await st.enter_async_context(ClientSession(fr, fw))
                await fetch.initialize()
            except Exception:
                fetch = None
        graph = build_graph(Tools(own, fetch))
        out = await graph.ainvoke({"question": question, "crop": crop, "region": region,
                                   "extra_urgent_reasons": list(extra_urgent_reasons or [])})
    return {k: out.get(k) for k in ("case_id", "status", "crop", "region", "clarification", "draft", "draft_mode",
                                     "urgent_reasons", "source_checks", "errors", "language",
                                     "citation_check", "farmer_draft")} | {
        # True when the farmer's place is known and some passage used is for another agroecological zone (or the
        # place's zone is unknown). The officer screen and the farmer reply use it.
        "zone_mismatch": bool(out.get("zone_mismatch")),
        "rainfall": out.get("rainfall"),
        "zone": (out.get("zone") or {}).get("zone"),
        "priority": "urgent" if out.get("urgent_reasons") else "routine",
        "sources": [p["id"] for p in out.get("passages") or []]}


def main():
    q = " ".join(sys.argv[1:]) or "When should I plant soybean in Tamale?"
    print(json.dumps(asyncio.run(run(q)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
