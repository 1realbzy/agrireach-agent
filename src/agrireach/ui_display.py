"""Officer and farmer display rules for the verified API.

These functions only format fields the server already returned. They do not
classify emergencies, invent tool calls, or turn an unknown model cost into zero.
"""
import re

EMERGENCY_PREFIX = "EMERGENCY:"
_CITATION = re.compile(r"\[[A-Z0-9][A-Z0-9-]*:[^\]]+\]")
_SECRET = re.compile(
    r"(?i)(bearer\s+\S+|password\s*[:=]\s*\S+|api[_-]?key\s*[:=]\s*\S+"
    r"|session_token\s*[:=]\s*\S+|token\s*[:=]\s*\S{8,})"
)


def redact(text) -> str:
    """Hide credential-shaped fragments before any recorded text is shown."""
    return _SECRET.sub("[redacted]", str(text or ""))


def is_emergency_case(case: dict) -> bool:
    """True only when the server already stored an EMERGENCY reason."""
    return any(isinstance(reason, str) and reason.startswith(EMERGENCY_PREFIX)
               for reason in case.get("urgent_reasons") or [])


def emergency_reasons(case: dict) -> list[str]:
    return [reason for reason in case.get("urgent_reasons") or []
            if isinstance(reason, str) and reason.startswith(EMERGENCY_PREFIX)]


def other_routing_notes(case: dict) -> list[str]:
    return [reason for reason in case.get("urgent_reasons") or []
            if isinstance(reason, str) and not reason.startswith(EMERGENCY_PREFIX)]


def queue_actions(case: dict) -> str:
    status = case.get("status")
    if status == "not_delivered":
        return "Open the question to retry release, or reject it."
    if status == "pending_review":
        return "Open the question to approve, reject, or request information."
    if status == "needs_info":
        return "Open the question to read the requested information."
    return "Open the question to read its recorded status."


def classify_login(status: int, data) -> dict:
    """Turn a login response into a result that never includes the password."""
    body = data if isinstance(data, dict) else {}
    token = body.get("session_token")
    if status == 200 and isinstance(token, str) and token.strip():
        return {"ok": True, "token": token, "email": body.get("email"),
                "expires_at": body.get("expires_at"), "officer": body.get("officer")}
    if status == 401:
        detail = body.get("detail")
        message = detail if isinstance(detail, str) and detail else "Invalid email or password."
        return {"ok": False, "message": message}
    if status == 429:
        detail = body.get("detail")
        message = detail if isinstance(detail, str) and detail else (
            "Too many failed sign-in attempts. Wait a few minutes and try again.")
        return {"ok": False, "message": message}
    return {"ok": False, "message": "Sign-in could not be completed. No password was stored."}


def _cost_text(block: dict) -> str:
    if block.get("cost_usd") is None or block.get("cost_complete") is False:
        return "cost unknown"
    return f"cost ${block['cost_usd']:.6f}"


def _usage_line(name: str, block) -> str | None:
    if not isinstance(block, dict):
        return None
    calls = block.get("attempted_calls")
    if calls is None:
        calls = block.get("model_calls")
    tokens = (block.get("prompt_tokens") or 0) + (block.get("completion_tokens") or 0)
    if not calls and not tokens and block.get("cost_usd") is None:
        return None
    return (f"{name}: {calls or 0} model calls, {block.get('prompt_tokens') or 0} prompt tokens, "
            f"{block.get('completion_tokens') or 0} completion tokens, {_cost_text(block)}.")


def generation_presentation(generation, draft: str, offline_marker: str) -> dict:
    """Choose the banner from generation metadata when the server sent it.

    A draft that still contains the offline marker must not be described as
    'no model' when the same payload records model calls.
    """
    gen = generation if isinstance(generation, dict) else {}
    attempted = gen.get("attempted_calls")
    if attempted is None:
        attempted = gen.get("model_calls") or 0
    model_used = bool(gen.get("model_used")) or bool(attempted)
    state = gen.get("state")
    label = gen.get("label") if isinstance(gen.get("label"), str) else ""
    usage = [line for line in (
        _usage_line("Drafting", gen.get("drafting_usage")),
        _usage_line("Officer review", gen.get("review_usage")),
    ) if line]
    if not usage and (attempted or gen.get("prompt_tokens") or gen.get("completion_tokens") or gen.get("cost_usd") is not None):
        usage.append(
            f"Recorded usage: {attempted or 0} model calls, {gen.get('prompt_tokens') or 0} prompt tokens, "
            f"{gen.get('completion_tokens') or 0} completion tokens, {_cost_text(gen)}."
        )
    models = gen.get("models") or []
    if models:
        usage.append("Models: " + ", ".join(str(model) for model in models))
    if state or label:
        headline = label or str(state)
        denies_model = bool(re.search(r"no (language )?model", headline, re.I))
        if model_used and denies_model and state != "offline_source_draft":
            headline = {
                "live_model_draft": "LIVE MODEL DRAFT",
                "model_draft_rejected_source_fallback":
                    "SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT",
                "model_error_source_fallback": "SOURCE DRAFT AFTER MODEL ERROR",
                "source_draft_with_model_calls":
                    "SOURCE DRAFT: model calls were recorded",
                "officer_written": "OFFICER-WRITTEN RESPONSE",
            }.get(state, "A language model call was recorded for this question.")
        return {"headline": headline, "model_used": model_used, "usage": usage, "known": True}
    if offline_marker and offline_marker in (draft or ""):
        return {
            "headline": (
                "The draft text is marked as an offline source draft. "
                "This response did not include generation metadata, so model calls cannot be confirmed here."
            ),
            "model_used": False,
            "usage": [],
            "known": False,
        }
    if (draft or "").strip():
        return {"headline": "How this draft was produced was not included in the response.",
                "model_used": False, "usage": [], "known": False}
    return {"headline": "NO DRAFT (clarification, emergency or not yet drafted)",
            "model_used": False, "usage": [], "known": False}


def tool_execution_view(evidence, log=None) -> dict:
    """Show recorded tool rows only. Missing evidence stays missing."""
    rows = []
    recorded = isinstance(evidence, dict) and bool(evidence.get("mcp_recorded"))
    note = None
    if recorded:
        for run in evidence.get("mcp_runs") or []:
            if not isinstance(run, dict):
                continue
            for call in run.get("calls") or []:
                if not isinstance(call, dict):
                    continue
                error = call.get("error")
                rows.append({
                    "order": call.get("seq"),
                    "tool": str(call.get("tool") or "unrecorded tool"),
                    "server": call.get("server"),
                    "ok": call.get("ok"),
                    "error": redact(error) if error else None,
                    "ms": call.get("ms") if isinstance(call.get("ms"), (int, float)) else None,
                })
    elif isinstance(evidence, dict):
        note = "MCP tool calls were not recorded for this question."
    else:
        note = "No tool execution record was returned for this question."
    timeline = []
    source = (evidence or {}).get("timeline") if isinstance(evidence, dict) else None
    if source is None and log:
        source = [{"seq": index, "tool": entry.get("tool"), "ok": entry.get("ok"),
                   "summary": entry.get("result_summary")}
                  for index, entry in enumerate(log, 1) if isinstance(entry, dict)]
        if source and not recorded:
            note = (note or "") + " The case log is shown instead."
    for item in source or []:
        if not isinstance(item, dict):
            continue
        timeline.append({
            "order": item.get("seq"),
            "tool": str(item.get("tool") or "check"),
            "ok": item.get("ok"),
            "summary": redact(item.get("summary") or "")[:300],
        })
    return {"recorded": recorded, "rows": rows, "timeline": timeline, "note": note}


def acknowledgement_text(ack) -> str | None:
    """Use the server message. Never present a blank status as a delivery."""
    if not isinstance(ack, dict):
        return None
    message = str(ack.get("message") or "").strip()
    if message:
        return message
    if ack.get("simulated"):
        return "A simulated confirmation was recorded. No message was sent to a phone."
    status = str(ack.get("status") or ack.get("state") or "").replace("_", " ").strip()
    if status:
        return f"Question acknowledgement: {status}."
    return "Question acknowledgement was returned without a status."


def unique_labels(labels) -> list[str]:
    seen = []
    for label in labels:
        if label not in seen:
            seen.append(label)
    return seen


def citation_groups(cites, label_for) -> list[tuple[str, list[int]]]:
    """Group footnote numbers that resolve to the same title and page."""
    groups: list[tuple[str, list[int]]] = []
    index = {}
    for number, cite in enumerate(cites, 1):
        inner = cite[1:-1] if cite.startswith("[") and cite.endswith("]") else cite
        label = label_for(inner)
        if label not in index:
            index[label] = len(groups)
            groups.append((label, []))
        groups[index[label]][1].append(number)
    return groups


def readable_advice(text: str, label_for) -> str:
    """Replace raw source tags with the title and page, preserving the words."""
    def replace(match):
        return label_for(match.group(0)[1:-1])
    return _CITATION.sub(replace, text or "")


def provenance_caption(data: dict) -> str:
    who = data.get("approved_by")
    when = data.get("approved_at")
    if who and when:
        return (f"An extension officer ({who}) approved this answer at {when}. "
                "This page is not a text-message delivery receipt.")
    if who:
        return (f"An extension officer ({who}) approved this answer. "
                "This page is not a text-message delivery receipt.")
    return ("An extension officer approved this answer before it could be shown. "
            "This page is not a text-message delivery receipt.")
