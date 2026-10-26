"""Translate API dispositions to public workflow messages without exception text."""


def auth_headers(token: str) -> dict:
    """Never create an empty bearer value; whitespace is not a credential."""
    return {"Authorization": f"Bearer {token.strip()}"} if token.strip() else {}


def feedback(status: int, data: dict) -> tuple[str, str]:
    """Return severity and actionable public text; diagnostics stay in audit/logs."""
    detail = data.get("detail", {})
    outcome = detail.get("outcome") if isinstance(detail, dict) else None
    if outcome == "assessment_unavailable" or status == 503:
        return "warning", "Assessment unavailable. Nothing was approved or sent. Retry assessment, revise the advice, request information or reject the case."
    if outcome == "acknowledgement_required":
        return "warning", "Approval is waiting for your acknowledgement of the source concerns below. Nothing was sent. Review each concern before acknowledging."
    if status == 422:
        return "error", "Approval was blocked or held for additional review. Nothing was approved or sent. Check the highlighted advice and sources, then revise, request information or reject."
    if status == 401:
        return "info", "Sign in with a valid officer token to continue."
    if status == 409:
        return "warning", "The action could not proceed with the current case or delivery state. Reload the case; reconcile any uncertain delivery before retrying."
    if status == 400 and isinstance(detail, str) and detail:
        return "error", f"The action could not be completed: {detail}. Nothing was approved or sent."
    if status >= 400:
        return "error", "The action could not be completed. Check the required fields and try again. If the problem continues, contact the operator with the case number."
    delivery = data.get("delivery")
    if delivery and delivery.get("outcome") == "definitely_failed":
        return "warning", "Advice approved, but the send failed and nothing went out. The case is back in the queue; fix the contact or channel, then retry."
    if delivery:
        if delivery.get("ok"):
            return "success", "Approved and released. Sent: the channel accepted the advisory."
        return "warning", "Advice approved, but delivery has not been confirmed. Check the delivery record before retrying; an uncertain send must be reconciled."
    state = data.get("status")
    messages = {"rejected": "Case rejected. Your decision and note were recorded. Nothing new was sent.",
                "needs_info": "Information requested. Your note was recorded. Nothing new was sent.",
                "released": "Advice approved and released for the farmer to read.",
                "approved": "Advice approved. Release and delivery are still pending.",
                "pending_review": "The case is waiting for officer review. Nothing has been approved.",
                "not_delivered": "Delivery was not confirmed. Check the delivery record before retrying."}
    return "success", messages.get(state, "Action recorded. No message was sent by this action.")
