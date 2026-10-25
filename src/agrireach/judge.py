"""Model judge for the claim check: is each sentence supported by the passage(s) it cites?

Runs on every model-written draft (code-built offline drafts quote passages verbatim and are not judged). The model
is AGRIREACH_JUDGE_MODEL, default DEFAULT_MODEL; it should differ from the drafting model so the drafter doesn't
grade itself. The endpoint and key default to LLM_BASE_URL / LLM_API_KEY and can be overridden with
AGRIREACH_JUDGE_BASE_URL / AGRIREACH_JUDGE_API_KEY.

One call per draft, temperature 0, JSON out. It FAILS CLOSED: if the call fails or the reply is unparseable, the
result records the error and the claim check fails, so the officer gets the verbatim passages and an urgent flag
("source check couldn't run") instead of an unchecked model draft.
"""
from __future__ import annotations

import json
import os

PROMPT = (
    "You check an agricultural advisory draft against its sources. For each numbered item you get one sentence "
    "from the draft and the source passage(s) it cites. Answer 'supported' if the passages state or directly imply "
    "what the sentence claims (paraphrase is fine; a sentence that only tells the officer to check, choose or "
    "refer, or says which language to reply in, is supported; a sentence telling the officer what to tell the farmer "
    "is judged on what the farmer would be told; a sentence that states only part of what a passage says is supported, so don't reject it for "
    "leaving other details out). Answer 'not_supported' if the sentence adds a claim, conclusion, recommendation or "
    "reassurance the passages do not make, says sources agree when they don't, or cites a passage about "
    "something else. The passages come from Northern Ghana guides: do not judge whether they apply to the farmer's "
    "location (code adds that caveat separately), and naming the farmer's own crop, pest or place from the question "
    "is fine when the action itself is in the passage. Reply with JSON only: {\"verdicts\": [{\"n\": 1, \"verdict\": \"supported\" or "
    "\"not_supported\", \"why\": \"<10 words\"}]}"
)


DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"


def enabled() -> bool:
    """Always on: a model draft is never released for review without the judge having read it."""
    return True


def model() -> str:
    return os.getenv("AGRIREACH_JUDGE_MODEL") or DEFAULT_MODEL


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
    start = raw.find("{")
    if start < 0:
        raise ValueError("no JSON object in judge reply")
    data, _end = json.JSONDecoder().raw_decode(raw[start:])  # the first object; ignore anything after it
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
    except Exception as e:  # never crash a case; record why it didn't run (claim_check then fails closed)
        return {"model": model(), "error": f"{type(e).__name__}: {e}"[:300], "verdicts": []}
