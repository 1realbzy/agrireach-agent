"""Draft writer. Uses an open-weights model behind any OpenAI-compatible endpoint when
LLM_BASE_URL and LLM_MODEL are set; otherwise a deterministic OFFLINE STUB (no model)."""
from __future__ import annotations

import contextlib
import contextvars
import os

# --- Every model call (drafter, farmer text, judge) sends max_tokens and records its usage.
# Without max_tokens OpenRouter reserves the model's whole output window and can answer 402 on a small balance.
MAX_TOKENS = {"draft": 800, "farmer_text": 400, "judge": 1500}
_usage: contextvars.ContextVar[list | None] = contextvars.ContextVar("agrireach_usage", default=None)
# App draft attempt (1, then 2). None for assess, approval, and the farmer-text rewrite.
# The OpenAI client defaults to two hidden HTTP retries inside one create(); those are not separate records.
_attempt: contextvars.ContextVar[int | None] = contextvars.ContextVar("agrireach_model_attempt", default=None)
_ENTRY_KEYS = ("role", "model", "ok", "error", "prompt_tokens", "completion_tokens", "cost_usd", "attempt")
# Longer than the longest catalog model id (56) and the longest chat-client error class (30).
# model_usage rows are not passed through the shared 2000-character tool-log slice.
_MODEL_CHARS = 256
_ERROR_CHARS = 64


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


def begin_attempt(number: int):
    """Mark the application draft attempt. Does not change the model request."""
    return _attempt.set(number)


def end_attempt(token) -> None:
    _attempt.reset(token)


def _call_record(role: str, model: str, *, ok: bool, error: str | None, prompt_tokens, completion_tokens, cost_usd) -> dict:
    """One application invocation. Unknown tokens and cost stay None; a failed request is never priced at 0."""
    return {"role": role, "model": model, "ok": ok, "error": error, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens, "cost_usd": cost_usd, "attempt": _attempt.get()}


def record_usage(role: str, model: str, response) -> dict:
    u = getattr(response, "usage", None)
    entry = _call_record(
        role, model, ok=True, error=None,
        prompt_tokens=getattr(u, "prompt_tokens", None), completion_tokens=getattr(u, "completion_tokens", None),
        cost_usd=getattr(u, "cost", None) if u is not None else None)
    calls = _usage.get()
    if calls is not None:
        calls.append(entry)
    return entry


def create(role: str, model: str, client, **kw):
    """client.chat.completions.create with the role's max_tokens, recording the attempt whether or not it succeeds
    (a 402 or timeout is recorded as a failed call, then re-raised). One record is one application call. HTTP retries
    made inside the client stay inside that call and are not listed separately."""
    try:
        r = client.chat.completions.create(model=model, max_tokens=max_tokens(role), **kw)
    except Exception as e:
        calls = _usage.get()
        if calls is not None:
            calls.append(_call_record(role, model, ok=False, error=type(e).__name__,
                                      prompt_tokens=None, completion_tokens=None, cost_usd=None))
        raise
    record_usage(role, model, r)
    return r


def log_usage(case_id, calls: list, actor: str = "agent", path: str | None = None) -> dict:
    """Tokens and provider-reported cost of these model calls, logged on the case as a model_usage row."""
    summary = usage_summary(calls)
    if calls and case_id:
        from agrireach import db
        cost = "unknown" if summary["cost_usd"] is None else f"${summary['cost_usd']}"
        payload = summary | ({"path": path} if path else {})
        db.log(db.connect(), actor, "model_usage", _bounded_usage(payload),
               f"{summary['calls']} of {summary['attempted']} model calls succeeded, cost {cost}",
               ok=not summary["failed"], case_id=case_id, args_limit=None)
    return summary


def _clip(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit]


def _bounded_usage(payload: dict) -> dict:
    """Keep a model-usage row complete for real model ids and error classes, and bounded past that."""
    entries = []
    shortened = False
    for entry in payload.get("entries") or []:
        model, error = entry.get("model"), entry.get("error")
        clipped_model, clipped_error = _clip(model, _MODEL_CHARS), _clip(error, _ERROR_CHARS)
        shortened = shortened or clipped_model != model or clipped_error != error
        entries.append(entry | {"model": clipped_model, "error": clipped_error})
    errors = [_clip(error, _ERROR_CHARS) for error in payload.get("errors") or []]
    shortened = shortened or errors != list(payload.get("errors") or [])
    return payload | {"entries": entries, "errors": errors, "identifiers_complete": not shortened}


@contextlib.contextmanager
def usage_logged(case_id, actor: str, path: str):
    """Record and log the model calls made inside the block (officer re-propose, approval-time source check). Live
    run 6: only the agent run logged model_usage, so these calls were missing from the app's cost figure."""
    calls: list = []
    token = _usage.set(calls)
    try:
        yield calls
    finally:
        _usage.reset(token)
        log_usage(case_id, calls, actor=actor, path=path)


def usage_summary(calls: list) -> dict:
    """Totals for one run. cost_usd is the provider's own figure; None if a successful call did not report one.

    Failed requests stay in entries with cost_usd None. They are not added to the total as 0, and a known success
    price is kept (the total is then only the reported successes)."""
    recorded = list(calls)
    failed = [c for c in recorded if c.get("ok") is False]
    succeeded = [c for c in recorded if c.get("ok") is not False]
    grouped: dict = {}
    for entry in succeeded:
        grouped.setdefault(entry["role"], []).append(entry)
    by_role = {}
    for role, group in grouped.items():
        by_role[role] = {"calls": len(group),
                         "prompt_tokens": _total(entry.get("prompt_tokens") for entry in group),
                         "completion_tokens": _total(entry.get("completion_tokens") for entry in group)}
    costs = [entry.get("cost_usd") for entry in succeeded]
    # Success prices only. Unknown failure usage stays null in entries and is not added as 0.
    # cost_usd remains that known sum so one unknown failure does not erase a reported price.
    return {"attempted": len(succeeded) + len(failed), "calls": len(succeeded), "failed": len(failed),
            "errors": sorted({c["error"] for c in failed}), "by_role": by_role,
            "entries": [{key: entry.get(key) for key in _ENTRY_KEYS} for entry in recorded],
            "tokens_complete": all(_known_number(entry.get("prompt_tokens")) and _known_number(entry.get("completion_tokens"))
                                   for entry in recorded),
            "cost_complete": all(_known_number(entry.get("cost_usd")) for entry in recorded),
            "cost_usd": round(sum(costs), 6) if costs and all(_known_number(cost) for cost in costs) else None}


def _known_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _total(values) -> int | float | None:
    values = list(values)
    if not values or any(not _known_number(value) for value in values):
        return None
    return sum(values)

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
