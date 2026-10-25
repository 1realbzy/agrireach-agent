"""Optional model judge for the claim check: is each cited sentence supported by the passage it cites?

Off by default. Turn on with AGRIREACH_JUDGE_MODEL (any OpenAI-compatible chat model; it should differ from the
drafting model so the drafter doesn't grade itself). The endpoint and key default to LLM_BASE_URL / LLM_API_KEY
and can be overridden with AGRIREACH_JUDGE_BASE_URL / AGRIREACH_JUDGE_API_KEY.

One call per draft, temperature 0, JSON out. If the judge call fails or returns something unparseable, the result
records the error and NO sentence is rejected by the judge (the deterministic checks still apply). Failing closed
here would turn every provider outage into a verbatim-passages fallback; the officer reviews every case anyway.
"""
from __future__ import annotations

import json
import os
import re

PROMPT = (
    "You check an agricultural advisory draft against its sources. For each numbered item you get one sentence "
    "from the draft and the source passage(s) it cites. Answer 'supported' if the passages state or directly imply "
    "what the sentence claims (paraphrase is fine; a sentence that only tells the officer to check, choose or "
    "refer is supported). Answer 'not_supported' if the sentence adds a claim, conclusion, recommendation or "
    "reassurance the passages do not make, says sources agree when they don't, or cites a passage about "
    "something else. The passages come from Northern Ghana guides: do not judge whether they apply to the farmer's "
    "location (code adds that caveat separately), and naming the farmer's own crop, pest or place from the question "
    "is fine when the action itself is in the passage. Reply with JSON only: {\"verdicts\": [{\"n\": 1, \"verdict\": \"supported\" or "
    "\"not_supported\", \"why\": \"<10 words\"}]}"
)


def enabled() -> bool:
    return bool(os.getenv("AGRIREACH_JUDGE_MODEL"))


def model() -> str:
    return os.getenv("AGRIREACH_JUDGE_MODEL", "")


def build_user_message(items: list[tuple[str, list[dict]]]) -> str:
    lines = []
    for n, (sentence, ps) in enumerate(items, 1):
        src = " | ".join(f"[{p['id']}] {p['text']}" for p in ps)
        lines.append(f"{n}. SENTENCE: {sentence}\n   PASSAGES: {src}")
    return "\n".join(lines)


def _call(user: str) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("AGRIREACH_JUDGE_BASE_URL") or os.environ["LLM_BASE_URL"],
                    api_key=os.getenv("AGRIREACH_JUDGE_API_KEY") or os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    r = client.chat.completions.create(model=model(), temperature=0,
                                       messages=[{"role": "system", "content": PROMPT},
                                                 {"role": "user", "content": user}])
    return r.choices[0].message.content or ""


def parse(raw: str, items: list[tuple[str, list[dict]]]) -> list[dict]:
    """Verdicts in item order. Raises ValueError if the reply doesn't cover every item with a valid verdict."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("no JSON object in judge reply")
    data = json.loads(m.group(0))
    by_n = {int(v["n"]): v for v in data.get("verdicts", [])}
    out = []
    for n, (sentence, ps) in enumerate(items, 1):
        v = by_n.get(n)
        if not v or v.get("verdict") not in ("supported", "not_supported"):
            raise ValueError(f"judge reply has no valid verdict for item {n}")
        out.append({"n": n, "sentence": sentence, "cited": [p["id"] for p in ps], "verdict": v["verdict"],
                    "why": str(v.get("why", ""))[:160]})
    return out


def judge(items: list[tuple[str, list[dict]]], call=None) -> dict:
    """Returns {"model", "verdicts"} or {"model", "error"}; `call` replaces the network call (tests, fixtures)."""
    call = call or _call
    try:
        raw = call(build_user_message(items))
        return {"model": model(), "verdicts": parse(raw, items), "raw": raw}
    except Exception as e:  # never let the judge crash a case; record why it didn't run
        return {"model": model(), "error": f"{type(e).__name__}: {e}"[:300], "verdicts": []}
