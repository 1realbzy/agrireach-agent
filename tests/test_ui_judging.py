"""Display rules for auth, emergencies, tool evidence and generation labels."""
from agrireach.ui_display import (
    acknowledgement_text, citation_groups, classify_login, emergency_reasons,
    generation_presentation, is_emergency_case, provenance_caption, queue_actions,
    readable_advice, tool_execution_view, unique_labels,
)

MARKER = "[OFFLINE STUB DRAFT - no language model was used; text is assembled from retrieved passages]"


def test_invalid_login_uses_the_server_message_and_drops_the_password():
    result = classify_login(401, {"detail": "Invalid email or password."})
    assert result == {"ok": False, "message": "Invalid email or password."}
    assert "password" not in result


def test_login_keeps_the_token_for_server_state_only():
    result = classify_login(200, {
        "session_token": "opaque-session", "token_type": "Bearer",
        "expires_at": "2026-11-17T06:00:00Z", "officer": "Ada", "email": "ada@example.com",
    })
    assert result["ok"] is True
    assert result["token"] == "opaque-session"
    assert result["expires_at"] == "2026-11-17T06:00:00Z"


def test_rate_limit_is_shown_and_unknown_failure_stores_nothing():
    locked = classify_login(429, {"detail": "Too many failed sign-in attempts. Wait a few minutes and try again."})
    assert locked["ok"] is False
    assert "Wait" in locked["message"]
    failed = classify_login(503, {})
    assert failed["message"].startswith("Sign-in could not be completed")


def test_emergency_flag_comes_from_the_server_reason():
    case = {"priority": "urgent", "urgent_reasons": [
        "EMERGENCY: chemical swallowed, inhaled or splashed (farmer wrote: 'gramoxone').",
        "chemical terms in question",
    ], "status": "pending_review"}
    assert is_emergency_case(case) is True
    assert emergency_reasons(case) == [case["urgent_reasons"][0]]
    assert "EMERGENCY:" not in " ".join(
        reason for reason in case["urgent_reasons"] if not reason.startswith("EMERGENCY:"))
    routine = {"priority": "routine", "urgent_reasons": ["chemical terms in question"]}
    assert is_emergency_case(routine) is False
    assert "approve, reject, or request information" in queue_actions(case)


def test_rejected_live_draft_is_not_labelled_as_no_model():
    draft = MARKER + "\nPlant after the rains."
    shown = generation_presentation({
        "state": "model_draft_rejected_source_fallback",
        "label": "SOURCE DRAFT AFTER REJECTED LIVE MODEL DRAFT: verbatim passages shown (2 model calls, cost unknown)",
        "model_used": True,
        "attempted_calls": 2,
        "drafting_usage": {"attempted_calls": 2, "prompt_tokens": 100, "completion_tokens": 40,
                           "cost_usd": None, "cost_complete": False},
        "review_usage": {"attempted_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
                         "cost_usd": None, "cost_complete": True},
        "models": ["example-model"],
    }, draft, MARKER)
    assert "no language model" not in shown["headline"].lower()
    assert "no model" not in shown["headline"].lower()
    assert shown["model_used"] is True
    assert any("cost unknown" in line for line in shown["usage"])
    assert any("example-model" in line for line in shown["usage"])
    assert not any("$0" in line for line in shown["usage"])


def test_known_zero_cost_stays_zero_and_offline_draft_says_no_calls():
    offline = generation_presentation({
        "state": "offline_source_draft",
        "label": "NO MODEL CALLS: offline source draft (verbatim passages)",
        "model_used": False, "attempted_calls": 0,
        "cost_usd": 0, "cost_complete": True,
    }, MARKER, MARKER)
    assert "NO MODEL CALLS" in offline["headline"]
    live = generation_presentation({
        "state": "live_model_draft", "label": "LIVE MODEL DRAFT", "model_used": True,
        "attempted_calls": 1, "cost_usd": 0.0, "cost_complete": True,
        "prompt_tokens": 3, "completion_tokens": 1,
    }, "Advice", MARKER)
    assert live["headline"] == "LIVE MODEL DRAFT"
    assert any("cost $0.000000" in line for line in live["usage"])


def test_missing_generation_does_not_claim_the_model_was_absent():
    shown = generation_presentation(None, MARKER + "\nPassage.", MARKER)
    assert "cannot be confirmed" in shown["headline"]
    assert "No language model was used" not in shown["headline"]


def test_tool_rows_keep_order_errors_and_duration_without_inventing_any():
    view = tool_execution_view({
        "mcp_recorded": True,
        "mcp_runs": [{"calls": [
            {"seq": 1, "server": "agrireach", "tool": "search_guidance", "ok": True, "ms": 12},
            {"seq": 2, "server": "fetch", "tool": "fetch", "ok": False, "error": "timeout", "ms": 20000},
        ]}],
        "timeline": [{"seq": 1, "tool": "mcp_tool_calls", "ok": False, "summary": "Bearer secret-value"}],
    })
    assert [row["tool"] for row in view["rows"]] == ["search_guidance", "fetch"]
    assert view["rows"][1]["error"] == "timeout"
    assert view["rows"][1]["ms"] == 20000
    assert view["rows"][0]["order"] == 1
    assert "secret-value" not in view["timeline"][0]["summary"]
    assert "[redacted]" in view["timeline"][0]["summary"]


def test_missing_tool_record_is_not_filled_in():
    view = tool_execution_view({"mcp_recorded": False, "mcp_runs": [], "timeline": []})
    assert view["recorded"] is False
    assert view["rows"] == []
    assert "not recorded" in view["note"]
    fallback = tool_execution_view(None, [{"tool": "search_guidance", "ok": True, "result_summary": "2 passages"}])
    assert fallback["rows"] == []
    assert fallback["timeline"][0]["tool"] == "search_guidance"


def test_acknowledgement_and_sources_and_farmer_provenance():
    assert acknowledgement_text({"simulated": True, "state": ""}) .startswith("A simulated confirmation")
    assert acknowledgement_text({"status": "accepted", "message": "The SMS provider accepted a confirmation. This does not mean your phone has received it."}).startswith("The SMS provider accepted")
    assert "without a status" in acknowledgement_text({"status": ""})
    assert unique_labels(["Maize guide, 4", "Maize guide, 4", "Maize guide, 5"]) == ["Maize guide, 4", "Maize guide, 5"]
    groups = citation_groups(["[MOFA:p4]", "[MOFA:p4b]"], lambda _id: "Maize guide, 4")
    assert groups == [("Maize guide, 4", [1, 2])]
    text = readable_advice("Harvest when pods are brown [MOFA-MAIZE:p10-harvest].", lambda _id: "Maize guide, page 10")
    assert "MOFA-MAIZE" not in text
    assert "Maize guide, page 10" in text
    caption = provenance_caption({"approved_by": "Ada", "approved_at": "2026-11-16T12:00:00Z"})
    assert "Ada" in caption
    assert "not a text-message delivery receipt" in caption
