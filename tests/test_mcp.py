import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import os


async def _session_calls(calls):
    p = StdioServerParameters(command=sys.executable, args=["-m", "agrireach.mcp_server"], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            return names, [await s.call_tool(n, a) for n, a in calls]


def test_tools_discoverable_and_gate_enforced_over_mcp():
    names, res = asyncio.run(_session_calls([
        ("search_guidance", {"query": "soybean seed rate per hectare"}),
        ("retrieve_reference", {"passage_id": "does-not-exist"}),
        ("create_or_update_case", {"status": "approved", "question": "x"}),
        ("get_crop_calendar", {"crop": "maize"}),
    ]))
    assert names == ["create_or_update_case", "get_crop_calendar", "retrieve_reference", "search_guidance"]
    hits = json.loads(res[0].content[0].text)
    assert {h["source_id"] for h in hits} == {"APNI-SARI-2023", "IITA-SSPING-2022"}
    assert all(h["source"]["url"].startswith("https://") for h in hits)
    assert res[1].isError  # unknown reference is an error, never invented
    assert res[2].isError and "may only set" in res[2].content[0].text
    assert json.loads(res[3].content[0].text) == []  # no local reference for maize
