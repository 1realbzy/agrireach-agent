"""AgriReach Agricultural Knowledge MCP server (official Python MCP SDK, stdio).

Tools: search_guidance, get_crop_calendar, get_zone_planting_guidance, get_recent_rainfall, retrieve_reference,
create_or_update_case.
create_or_update_case is the acting tool; it can only set 'draft' or 'pending_review'.
"""
from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from agrireach import db, knowledge, rainfall, zones

mcp = FastMCP("agrireach-knowledge")


def _con():
    return db.connect()


@mcp.tool()
def search_guidance(query: str, crop: str = "soybean", region: str = "") -> str:
    """Search the curated extension corpus (see data/knowledge.json for the crops covered). Returns verbatim passages with source ids and URLs.
    Returns an empty list when nothing matches; never invents guidance."""
    hits = knowledge.search(query, crop=crop or None, region=region or None)
    con = _con()
    db.log(con, "agent", "search_guidance", {"query": query, "crop": crop, "region": region},
           f"{len(hits)} hits: {[h['id'] for h in hits]}")
    return json.dumps([{k: h[k] for k in ("id", "crop", "topic", "claim_key", "text", "page", "source_id", "source")}
                       | ({"also_claims": h["also_claims"]} if h.get("also_claims") else {})
                       | ({"risk": h["risk"]} if "risk" in h else {}) for h in hits], ensure_ascii=False)


@mcp.tool()
def get_crop_calendar(crop: str, region: str = "") -> str:
    """Return cited crop-calendar activities. Empty list means no local reference exists."""
    rows = knowledge.calendar(crop, region or None)
    db.log(_con(), "agent", "get_crop_calendar", {"crop": crop, "region": region}, f"{len(rows)} rows")
    return json.dumps(rows, ensure_ascii=False)


@mcp.tool()
def get_zone_planting_guidance(crop: str, place: str, season: str = "") -> str:
    """Planting-time passages (verbatim, with source and page) that apply in the agroecological zone of a Ghana
    region, district or town: the zone's planting-window rows, only for the season asked ('major' or 'minor') if one
    is given, plus national planting rules. Read-only. Unknown place or crop: {"zone": null, "passages": []}."""
    out = zones.planting_passages(crop, place, season if season in ("major", "minor") else "")
    db.log(_con(), "agent", "get_zone_planting_guidance", {"crop": crop, "place": place, "season": season},
           f"zone {(out['zone'] or {}).get('zone')}: {[p['id'] for p in out['passages']]}")
    return json.dumps(out, ensure_ascii=False)


@mcp.tool()
def get_recent_rainfall(district: str, days: int = 30, threshold_mm: float = 1.0) -> str:
    """Daily rainfall for a Ghana district (or district capital) over the last `days` complete days: daily mm,
    days with at least `threshold_mm`, missing days, provider, licence and retrieval time. Read-only and cached.
    A model/satellite estimate, not a rain gauge, and not advice: it never says whether onset has been reached.
    Offline or unknown district: {"available": false, "reason": "rainfall unavailable: ..."}."""
    r = rainfall.recent(district, days=max(1, min(int(days), 92)), threshold_mm=threshold_mm)
    db.log(_con(), "agent", "get_recent_rainfall", {"district": district, "days": days},
           f"{r.get('district')}: " + (f"{r['rain_days']} rain days, {r['missing_days']} missing"
                                         if r.get("available") else r.get("reason", "")))
    return json.dumps(r, ensure_ascii=False)


@mcp.tool()
def retrieve_reference(passage_id: str) -> str:
    """Fetch one passage and its source metadata by id. Errors if the id is unknown."""
    ref = knowledge.reference(passage_id)
    db.log(_con(), "agent", "retrieve_reference", {"passage_id": passage_id}, "found" if ref else "NOT FOUND", ok=bool(ref))
    if ref is None:
        raise ValueError(f"unknown reference id: {passage_id}")
    return json.dumps(ref, ensure_ascii=False)


@mcp.tool()
def create_or_update_case(status: str, question: str = "", case_id: int = 0, crop: str = "", region: str = "",
                          draft: str = "", source_ids: list[str] | None = None, priority: str = "routine",
                          urgent_reasons: list[str] | None = None, farmer_draft: str = "") -> str:
    """Create or update a farmer case. status must be 'draft' or 'pending_review'.
    farmer_draft is only a proposal for the officer (JSON); the officer approves the text that is sent.
    Approval is reserved for a named extension officer and cannot be set here."""
    con = _con()
    cid = db.agent_upsert_case(con, status=status, question=question, case_id=case_id or None, crop=crop or None,
                               region=region or None, draft=draft or None, sources=source_ids or [],
                               priority=priority, urgent_reasons=urgent_reasons or [],
                               farmer_draft=farmer_draft or None)
    db.log(con, "agent", "create_or_update_case",
           {"status": status, "priority": priority, "urgent_reasons": urgent_reasons, "sources": source_ids},
           f"case {cid} -> {status}", case_id=cid)
    return json.dumps({"case_id": cid, "status": status, "priority": priority})


def main():
    mcp.run()


if __name__ == "__main__":
    main()
