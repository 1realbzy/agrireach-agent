"""LangGraph orchestration. All tool use goes through MCP clients:
  - own server: agrireach.mcp_server (search_guidance, get_crop_calendar, retrieve_reference, create_or_update_case)
  - third-party server: mcp-server-fetch (reference MCP server, not written by us) to check cited source pages are reachable.
The graph ends after filing the case as pending_review. It has no path to approve or release.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from typing import TypedDict

from langgraph.graph import END, StateGraph
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agrireach import llm

RISK_TERMS = {
    "chemical": ["spray", "herbicide", "pesticide", "insecticide", "fungicide", "chemical", "glyphosate", "paraquat",
                 "atrazine", "dose", "poison"],
    "disease_or_pest": ["disease", "yellow", "spots", "wilting", "dying", "rot", "insects", "pest", "caterpillar",
                        "worms", "leaves turning"],
}
REGION_DEPENDENT = {"planting", "spacing", "seed"}
NORTHERN = ["northern", "north", "tamale", "savannah", "upper east", "upper west", "north east", "bolgatanga",
            "wa ", "yendi", "nyankpala", "damongo", "walewale"]
OTHER_REGIONS = ["ashanti", "kumasi", "volta", "accra", "greater accra", "eastern", "western", "central", "bono",
                 "ahafo", "oti", "cape coast", "takoradi", "ho "]


class S(TypedDict, total=False):
    question: str
    crop: str
    region: str
    case_id: int
    passages: list
    calendar: list
    urgent_reasons: list
    notes: list
    clarification: str
    draft: str
    draft_mode: str
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
        crop = s.get("crop") or ("soybean" if re.search(r"soy(a)?bean", q) else "")
        region = s.get("region") or ""
        if not region:
            for r in NORTHERN + OTHER_REGIONS:
                if r in q + " ":
                    region = r.strip()
                    break
        reasons = [f"{k.replace('_', ' ')} terms in question" for k, terms in RISK_TERMS.items()
                   if any(t in q for t in terms)]
        topics = {w for w in re.findall(r"[a-z]+", q)}
        clar = ""
        if not crop:
            clar = "Which crop is this about? AgriReach currently covers soybean only."
        elif not region and topics & {"plant", "planting", "sow", "when", "spacing", "seed", "seeds"}:
            clar = "Which district or region is your farm in? Planting guidance differs by region."
        case = await tools.call("create_or_update_case", {"status": "draft", "question": s["question"], "crop": crop,
                                                          "region": region})
        return {"crop": crop, "region": region, "urgent_reasons": reasons, "clarification": clar,
                "case_id": case["case_id"], "notes": [], "errors": []}

    async def retrieve(s: S) -> S:
        errors, notes, reasons = list(s["errors"]), list(s["notes"]), list(s["urgent_reasons"])
        region = s["region"]
        if region and not any(n.strip() in region for n in NORTHERN):
            reasons.append(f"no local reference for region '{region}' (corpus covers Northern Ghana only)")
            notes.append(f"The curated sources are for Northern Ghana; they may not apply in {region}.")
        passages, cal = [], []
        try:
            passages = await tools.call("search_guidance", {"query": s["question"], "crop": s["crop"], "region": ""})
            verified = []
            for p in passages:
                verified.append(await tools.call("retrieve_reference", {"passage_id": p["id"]}))
            passages = verified
            if re.search(r"\b(when|calendar|season)\b", s["question"].lower()):
                cal = await tools.call("get_crop_calendar", {"crop": s["crop"], "region": "northern"})
        except Exception as e:  # tool failure: never invent results
            errors.append(str(e))
            passages = []
            reasons.append("tool error during retrieval")
        if not passages and not errors:
            reasons.append("no grounded evidence found in corpus")
        by_key: dict = {}
        for p in passages:
            by_key.setdefault(p["claim_key"], set()).add(p["source_id"])
        for k, srcs in by_key.items():
            if len(srcs) > 1:
                reasons.append(f"sources differ on {k.replace('_', ' ')}: {', '.join(sorted(srcs))}")
                notes.append(f"Sources give different figures for {k.replace('_', ' ')}; officer should choose.")
        if any(p.get("risk") == "chemical" for p in passages) or any("chemical" in r for r in reasons):
            notes.append("Chemical use: AgriReach does not recommend products or doses. Refer to the label and the officer.")
        if any("disease" in r for r in reasons):
            notes.append("Possible pest/disease: this is not a diagnosis. Officer should inspect or refer.")
        return {"passages": passages, "calendar": cal, "errors": errors, "notes": notes,
                "urgent_reasons": sorted(set(reasons), key=reasons.index)}

    async def check_sources(s: S) -> S:
        checks = []
        if tools.fetch is None or not s["passages"]:
            return {"source_checks": checks}
        seen = set()
        for p in s["passages"]:
            src = p["source"]
            if p["source_id"] in seen:
                continue
            seen.add(p["source_id"])
            try:
                r = await asyncio.wait_for(tools.fetch.call_tool("fetch", {"url": src["landing_url"], "max_length": 20000,
                                                                          "raw": True}), timeout=30)
                body = r.content[0].text if r.content else ""
                ok = (not r.isError) and bool(re.search(r"soy(a)?bean", body, re.I))
                checks.append({"source_id": p["source_id"], "url": src["landing_url"], "reachable": ok,
                               "detail": "" if ok else body[:160]})
            except Exception as e:
                checks.append({"source_id": p["source_id"], "url": src["landing_url"], "reachable": False,
                               "detail": f"fetch error: {e}"[:160]})
        return {"source_checks": checks}

    async def write(s: S) -> S:
        notes = list(s["notes"])
        if s["errors"]:
            notes.append("A tool failed during retrieval; no guidance is shown rather than guessing.")
        try:
            text, used = llm.draft(s["question"], s["passages"], notes)
        except Exception as e:
            text, used = llm.stub_draft(s["question"], s["passages"], notes + [f"LLM call failed: {e}"]), "stub(llm-error)"
        return {"draft": text, "draft_mode": used}

    async def file_case(s: S) -> S:
        reasons = s["urgent_reasons"]
        r = await tools.call("create_or_update_case", {
            "status": "pending_review", "case_id": s["case_id"], "draft": s["draft"],
            "source_ids": [p["id"] for p in s["passages"]], "priority": "urgent" if reasons else "routine",
            "urgent_reasons": reasons})
        return {"status": r["status"]}

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


async def run(question: str, crop: str = "", region: str = "", use_fetch: bool | None = None) -> dict:
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
        out = await graph.ainvoke({"question": question, "crop": crop, "region": region})
    return {k: out.get(k) for k in ("case_id", "status", "crop", "region", "clarification", "draft", "draft_mode",
                                     "urgent_reasons", "source_checks", "errors")} | {
        "priority": "urgent" if out.get("urgent_reasons") else "routine",
        "sources": [p["id"] for p in out.get("passages") or []]}


def main():
    q = " ".join(sys.argv[1:]) or "When should I plant soybean in Tamale?"
    print(json.dumps(asyncio.run(run(q)), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
