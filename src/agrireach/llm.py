"""Draft writer. Uses an open-weights model behind any OpenAI-compatible endpoint when
LLM_BASE_URL and LLM_MODEL are set; otherwise a deterministic OFFLINE STUB (no model)."""
from __future__ import annotations

import contextvars
import os

# --- Every model call (drafter, farmer text, judge) sends max_tokens and records its usage.
# Without max_tokens OpenRouter reserves the model's whole output window and can answer 402 on a small balance.
MAX_TOKENS = {"draft": 800, "farmer_text": 400, "judge": 1500}
_usage: contextvars.ContextVar[list | None] = contextvars.ContextVar("agrireach_usage", default=None)


def max_tokens(role: str) -> int:
    return int(os.getenv(f"AGRIREACH_MAX_TOKENS_{role.upper()}") or MAX_TOKENS[role])


def extra_body(base_url: str | None) -> dict:
    """OpenRouter reports the price of each call only when asked."""
    return {"usage": {"include": True}} if base_url and "openrouter" in base_url else {}


def start_usage() -> list:
    """Collect usage for every model call made from here on in this context (one agent run)."""
    calls: list = []
    _usage.set(calls)
    return calls


def record_usage(role: str, model: str, response) -> dict:
    u = getattr(response, "usage", None)
    entry = {"role": role, "model": model, "ok": True,
             "prompt_tokens": getattr(u, "prompt_tokens", None), "completion_tokens": getattr(u, "completion_tokens", None),
             "cost_usd": getattr(u, "cost", None) if u is not None else None}
    calls = _usage.get()
    if calls is not None:
        calls.append(entry)
    return entry


def create(role: str, model: str, client, **kw):
    """client.chat.completions.create with the role's max_tokens, recording the attempt whether or not it succeeds
    (a 402 or timeout is recorded as a failed call, then re-raised)."""
    try:
        r = client.chat.completions.create(model=model, max_tokens=max_tokens(role), **kw)
    except Exception as e:
        calls = _usage.get()
        if calls is not None:
            calls.append({"role": role, "model": model, "ok": False, "error": type(e).__name__,
                          "prompt_tokens": None, "completion_tokens": None, "cost_usd": None})
        raise
    record_usage(role, model, r)
    return r


def usage_summary(calls: list) -> dict:
    """Totals for one run. cost_usd is the provider's own figure; None if it didn't report one for every call."""
    by_role: dict = {}
    failed = [c for c in calls if c.get("ok") is False]
    calls = [c for c in calls if c.get("ok") is not False]
    for c in calls:
        r = by_role.setdefault(c["role"], {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
        r["calls"] += 1
        r["prompt_tokens"] += c["prompt_tokens"] or 0
        r["completion_tokens"] += c["completion_tokens"] or 0
    costs = [c["cost_usd"] for c in calls]
    return {"attempted": len(calls) + len(failed), "calls": len(calls), "failed": len(failed),
            "errors": sorted({c["error"] for c in failed}), "by_role": by_role,
            "cost_usd": round(sum(costs), 6) if costs and all(isinstance(x, (int, float)) for x in costs) else None}

STUB_LABEL = "[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]"

SYSTEM = (
    "You are AgriReach, drafting advice for a Ghanaian extension officer to review (never sent directly to a farmer). "
    "Use ONLY the numbered passages provided. Cite with one passage id per bracket, e.g. [ID], right after the words "
    "it supports. Every number and date you write must be copied exactly from the passage you cite right after it; "
    "never add, round, merge or move figures between passages. "
    "If a CONFLICTS section is given, the sources disagree: state each source's figure in its own sentence with only "
    "that source's citation, do not pick one, do not merge them into one range, and do not count sources "
    "(never write 'two sources say'). Say the officer should choose. "
    "Every sentence that gives advice must be supported by the passage cited right after it; if no passage says "
    "it, leave it out rather than adding your own conclusion. Only say sources agree if you cite each of them and "
    "each one says it. "
    "A RAINFALL-... passage is a data record, not a guide: cite it only for a sentence reporting the record's own "
    "figures (mm, rain days, period, missing days). Every guide sentence, including 'three good rains' and 'after the "
    "rains have stabilized', must cite the guide passage it comes from, never the record. "
    "Good: 'Plant after three good rains within the planting window [IITA-MAIZE-2025:p15-three-good-rains].' "
    "Good: 'Sow after the rains have stabilized to avoid wilting [MOFA-MAIZE:p10-when-to-plant].' "
    "Bad: 'Plant after three good rains within the planting window [RAINFALL-OPEN-METEO:...].' "
    "Do not say whether the rains are enough or whether onset has been reached; the officer decides. "
    "If the passages do not answer the question, say you do not know. "
    "Never prescribe pesticide/herbicide products or doses and never confirm a disease diagnosis. "
    "Write in English for the officer. Plain language, at most 150 words."
)


def mode() -> str:
    return "llm" if os.getenv("LLM_BASE_URL") and os.getenv("LLM_MODEL") else "stub"


def stub_draft(question: str, passages: list[dict], notes: list[str]) -> str:
    lines = [STUB_LABEL]
    if not passages:
        lines.append("I could not find guidance on this in the curated sources, so I cannot give a grounded answer. "
                     "An extension officer needs to answer this case.")
    else:
        lines.append("What the curated sources say:")
        for p in passages:
            lines.append(f'- "{p["text"]}" [{p["id"]}]')
    lines += [f"Note: {n}" for n in notes]
    return "\n".join(lines)


def _conflict_block(conflicts: dict | None) -> str:
    if not conflicts:
        return ""
    lines = ["CONFLICTS (detected by code; show every side separately):"]
    for key, group in conflicts.items():
        lines.append(f"- {key.replace('_', ' ')}: " + " | ".join(f"[{p['id']}] says: \"{p['text']}\"" for p in group))
    return "\n".join(lines) + "\n\n"


def draft(question: str, passages: list[dict], notes: list[str], conflicts: dict | None = None,
          feedback: list[str] | None = None) -> tuple[str, str]:
    """Returns (text, mode_used). `feedback` lists citation-check problems from a previous attempt."""
    if mode() == "stub":
        return stub_draft(question, passages, notes), "stub"
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["LLM_BASE_URL"], api_key=os.getenv("LLM_API_KEY", "none"),
                    timeout=float(os.getenv("LLM_TIMEOUT", "60")))
    ctx = "\n".join(f"[{p['id']}] {p['text']}" for p in passages) or "(no passages found)"
    msg = (f"Farmer question: {question}\n\nPassages:\n{ctx}\n\n{_conflict_block(conflicts)}"
           f"Reviewer notes: {'; '.join(notes) or 'none'}")
    if feedback:
        msg += ("\n\nYour previous draft failed the automatic citation check:\n- " + "\n- ".join(feedback) +
                "\nRewrite it so every figure is copied from the passage cited right after it, every conflict "
                "side is stated with its own citation, and every sentence is supported by the passage it cites "
                "(remove any sentence no passage supports).")
    r = create("draft", os.environ["LLM_MODEL"], client, temperature=0, extra_body=extra_body(os.environ["LLM_BASE_URL"]),
               messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}])
    return r.choices[0].message.content.strip(), f"llm:{os.environ['LLM_MODEL']}"
