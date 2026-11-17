"""Officer and farmer screens with explicit workflow feedback and safe sign in."""
import hashlib
import logging
import os
import re

import httpx
import streamlit as st

from agrireach import knowledge, llm
from agrireach.phone import PhoneError, normalize as normalize_phone
from agrireach.tab_recovery import tab_state
from agrireach.ui_display import (
    acknowledgement_text, citation_groups, classify_login, emergency_reasons,
    generation_presentation, is_emergency_case, officer_case_summary, other_routing_notes, provenance_caption,
    queue_actions, readable_advice, tool_execution_view, unique_labels,
)
from agrireach.ui_feedback import auth_headers, feedback

API = os.getenv("AGRIREACH_API", "http://127.0.0.1:8000")
logger = logging.getLogger(__name__)


def _client_marker() -> str | None:
    """A digest of this browser's address for the API's per-client submission limit (the API sees only the
    portal container). Behind a reverse proxy the last X-Forwarded-For entry is the address the proxy saw."""
    try:
        forwarded = st.context.headers.get("X-Forwarded-For") or ""
        address = forwarded.split(",")[-1].strip() if isinstance(forwarded, str) and forwarded else (
            st.context.ip_address or "")
    except Exception:  # no browser session (scripts, tests)
        return None
    if not isinstance(address, str) or not address:  # e.g. Streamlit's AppTest has no real client address
        return None
    return hashlib.sha256(address.encode("utf-8")).hexdigest()[:32]


def request(method, path, **kwargs):
    """Handle service errors without displaying credentials or internal exceptions."""
    marker = _client_marker()
    if marker:
        kwargs["headers"] = {**(kwargs.get("headers") or {}), "X-AgriReach-Client": marker}
    try:
        response = httpx.request(method, API + path, timeout=180, **kwargs)
        return response.status_code, response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("ui_request_failed", extra={"event_name": "ui_request_failed", "error_type": type(exc).__name__})
        return 503, {}


def show_result(status, data, text=""):
    level, message = feedback(status, data)
    getattr(st, level)(message)
    detail = data.get("detail", {})
    if isinstance(detail, dict):
        show_findings(detail.get("findings", []), text)


LABELS = {"S1": "Required source safeguard", "S2": "Consultation or protection instruction",
          "S3": "Unsourced material or dose", "S4": "Burning without a source", "LANGUAGE": "Language needs additional review",
          "SOURCE_SUPPORT": "Source support needs review", "SOURCE_FIGURES": "Number not in the cited source",
          "SOURCE_CONFLICT": "Cited sources disagree", "RELEVANCE": "Reply does not address the question",
          "EVIDENCE_GAP": "No sourced guidance for this question"}


PASSAGE_ID = re.compile(r"\[?'?\b([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*:[\w-]+)'?\]?")  # e.g. ['MOFA-MAIZE:p10-when-to-plant']


def show_findings(findings, text=""):
    """Show each hold with its line and the plain reason, so the officer knows what to edit."""
    for finding in findings:
        st.caption(LABELS.get(finding["rule_id"], "Additional review required"))
        sentence = finding.get("sentence")
        quoted = re.search(r"'([^']+)'", finding.get("reason") or "")
        if not sentence and quoted:  # a number hold names the figure; show the line it is in
            sentence = next((s for s in re.split(r"(?<=[.!?])\s+", text) if re.search(rf"(?<!\w){re.escape(quoted[1])}(?!\w)", s, re.I)), "")
        if sentence:
            st.text(sentence)
        if finding.get("reason"):
            st.text("Why: " + PASSAGE_ID.sub(lambda m: source_name(m[1]), finding["reason"]))
        if finding["rule_id"] == "S1":
            for source_line in finding.get("evidence", [])[1:]:
                st.text("Required guidance: " + source_line)


CITATION = re.compile(r"\[[A-Z0-9][A-Z0-9-]*:[^\]]+\]")


def number_citations(text):
    """Replace raw source IDs with [1], [2]... for the officer; return the IDs in order."""
    cites = list(dict.fromkeys(CITATION.findall(text)))
    for n, cite in enumerate(cites, 1):
        text = text.replace(cite, f"[{n}]")
    return text, cites


def restore_citations(text, cites):
    """Put the source IDs back into an officer's edit so the saved draft keeps its citations."""
    return re.sub(r"\[(\d+)\]", lambda m: cites[int(m[1]) - 1] if 0 < int(m[1]) <= len(cites) else m[0], text)


def show_holds(cid, farmer_text, headers):
    """Show why the farmer text would be held as soon as the case opens (read-only check, cached per text)."""
    key = f"holds{cid}"
    if st.session_state.get(key, (None,))[0] != farmer_text:
        status, data = request("POST", f"/officer/cases/{cid}/assess", headers=headers, json={"farmer_text": farmer_text})
        st.session_state[key] = (farmer_text, status, data)
    _, status, data = st.session_state[key]
    if status != 200:
        st.warning("Safety check unavailable. Nothing will be approved until it runs; use Retry assessment after Approve.")
    elif data.get("outcome") != "pass":
        st.warning(f"This text would be held ({data['outcome'].replace('_', ' ')}). Edit the lines below before approving.")
        show_findings(data.get("findings", []), farmer_text)


def source_name(passage_id):
    """Show a source as its title and page, not its internal ID."""
    ref = knowledge.reference(passage_id) or {}
    title = (ref.get("source") or {}).get("title")
    return f"{title}, {ref['page']}" if title and ref.get("page") else title or "Cited source"


def render_delivery(case_id, headers, key):
    status, jobs = request("GET", f"/officer/cases/{case_id}/delivery-jobs", headers=headers)
    if status != 200:
        show_result(status, jobs)
        return
    if not jobs and key == 'queue':
        st.caption("Delivery: no channel send recorded. Web answers become available only after approval and release.")
    for job in jobs:
        st.caption(f"Delivery {job['id']}: {job['state'].replace('_', ' ')}")
        if job["state"] == "unknown":
            evidence = st.text_input("Verified provider evidence reference", key=f"evidence{key}{job['id']}")
            disposition = st.selectbox("Verified provider outcome", ["accepted", "definitely_failed"], key=f"disposition{key}{job['id']}")
            verified = st.checkbox("I checked the provider record and verified this outcome", key=f"verified{key}{job['id']}")
            if st.button("Record reconciliation without sending", key=f"reconcile{key}{job['id']}", disabled=not (verified and evidence.strip())):
                show_result(*request("POST", f"/officer/delivery-jobs/{job['id']}/reconcile", headers=headers,
                    json={"accepted": disposition == "accepted", "provider_evidence": evidence}))


def _with_tool_record(case, headers):
    """Load the server tool record once. The queue payload does not include it."""
    if "log" in case:
        return case
    status, detail = request("GET", f"/officer/cases/{case['id']}", headers=headers)
    if status == 200 and isinstance(detail, dict) and "log" in detail:
        st.session_state["review_case"] = detail
        return detail
    return case


def _show_generation(case):
    """Use the server's generation record. The offline marker inside the draft is not enough."""
    shown = generation_presentation(case.get("generation"), case.get("draft") or "", llm.STUB_LABEL)
    st.subheader("How this draft was made")
    if shown["model_used"]:
        st.info(shown["headline"])
    elif shown["known"] and "NO MODEL CALLS" in shown["headline"]:
        st.caption(shown["headline"])
    else:
        st.warning(shown["headline"])
    for line in shown["usage"]:
        st.caption(line)


def _show_tool_record(case):
    st.subheader("Tool execution")
    view = tool_execution_view(case.get("tool_evidence"), case.get("log"))
    if view["note"]:
        st.caption(view["note"].strip())
    if not view["rows"] and not view["timeline"]:
        return
    for row in view["rows"]:
        outcome = "completed" if row["ok"] else "did not complete"
        duration = f" · {row['ms']} ms" if row["ms"] is not None else ""
        order = row["order"] if row["order"] is not None else "—"
        server = f" · {row['server']}" if row.get("server") else ""
        st.markdown(f"**{order}. {row['tool']}**{server} · {outcome}{duration}")
        if row["error"]:
            st.caption("Error: " + row["error"])
    if view["timeline"]:
        st.caption("Recorded case log, in the order stored.")
        for item in view["timeline"]:
            outcome = "completed" if item["ok"] else "did not complete"
            st.markdown(f"**{item['order']}. {item['tool']}** · {outcome}")
            if item["summary"]:
                st.caption(item["summary"])


def render_case(case, headers):
    case = _with_tool_record(case, headers)
    cid = case["id"]
    with st.expander(case["question"], expanded=True):
        st.caption(
            f"{OFFICER_STATUS.get(case['status'], 'Needs review')} · Reference {cid} · "
            "An officer must approve the exact answer before the farmer can read it."
        )
        st.caption(f"Submitted {case.get('created_at', 'time unavailable')} · Crop: {case.get('crop') or 'Not specified'} · Location: {case.get('region') or 'Not specified'}")
        if is_emergency_case(case):
            st.error("Emergency classification")
            for reason in emergency_reasons(case):
                st.write(reason)
            notes = other_routing_notes(case)
            if notes:
                with st.expander("Other routing notes"):
                    for note in notes:
                        st.caption(note)
        else:
            for reason in case.get("urgent_reasons") or []:
                st.warning(reason)
        st.info(officer_case_summary(case, llm.STUB_LABEL))
        with st.expander("Audit trail", expanded=False):
            _show_generation(case)
            _show_tool_record(case)
            render_delivery(cid, headers, "queue")
        if case["status"] == "not_delivered" and st.button("Retry release and delivery", key=f"retry{cid}"):
            show_result(*request("POST", f"/cases/{cid}/release", headers=headers))
        st.subheader("Source evidence")
        if not case["sources"]:
            st.info("No source passages are attached. Review that gap before making a decision.")
        else:
            st.caption("; ".join(unique_labels(source_name(s) for s in case["sources"])))
        ack_status, ack = request("GET", f"/officer/cases/{cid}/acknowledgement", headers=headers)
        if ack_status == 200:
            text = acknowledgement_text(ack)
            phone = ack.get("phone_masked") or "not stored"
            if text:
                st.caption(f"{text} Phone {phone}.")
        voice_status, inbound = request("GET", f"/officer/cases/{cid}/voice", headers=headers)
        if voice_status == 200 and inbound.get("has_audio"):
            # Keep the officer's ability to verify the machine transcript.
            try:
                audio = httpx.get(f"{API}/officer/cases/{cid}/audio", headers=headers, timeout=30)
                if audio.status_code == 200:
                    st.audio(audio.content)
            except httpx.HTTPError:
                st.warning("Voice note unavailable. Ask the operator to restore access before relying on the transcript.")
            if inbound.get('transcript'):
                st.text("Machine transcript: " + inbound['transcript'])
            else:
                st.warning("No machine transcript is available. Listen to the recording before reviewing this case.")
        shown = "\n".join(l for l in case["draft"].splitlines() if not l.startswith(llm.STUB_LABEL))
        # Officers see numbered citations; edits are mapped back to the source IDs before saving.
        shown, cites = number_citations(shown)
        st.subheader("1 · Review or revise advisory")
        edited = st.text_area("Officer draft with citations", shown, key=f"draft{cid}")
        for label, numbers in citation_groups(cites, source_name):
            st.caption(", ".join(f"[{n}]" for n in numbers) + " " + label)
        with st.expander("Read the source passages"):
            grouped = {}
            for source_id in case["sources"]:
                grouped.setdefault(source_name(source_id), []).append(source_id)
            for label, source_ids in grouped.items():
                st.markdown("**" + label + "**")
                seen_text = set()
                for source_id in source_ids:
                    ref = knowledge.reference(source_id) or {}
                    passage = ref.get("text") or ""
                    if passage and passage not in seen_text:
                        seen_text.add(passage)
                        st.text(passage)
        text = case["draft"] if edited == shown else restore_citations(edited, cites)
        if st.button("Re-propose farmer text", key=f"repropose{cid}"):
            status, proposal = request("POST", f"/officer/cases/{cid}/farmer-draft", headers=headers, json={"officer_text": text})
            if status == 200:
                st.session_state[f"farmer{cid}"] = proposal.get("text", "")
                st.info("New proposal prepared. Check it against the sources before approving.")
            else:
                show_result(status, proposal)
        st.subheader("2 · Check safety before anyone receives this")
        farmer_text = st.text_area("Exact answer the farmer would receive", case.get("farmer_text") or (case.get("farmer_draft") or {}).get("text", ""), key=f"farmer{cid}")
        st.caption("Safety findings below are warnings about the answer text. Approving is a separate step, and a warning does not mean the answer was sent.")
        if farmer_text.strip():
            show_holds(cid, farmer_text, headers)
        elif is_emergency_case(case):
            st.caption("No advice text is ready to check. The emergency classification above is the server's routing record, not an approval.")
        else:
            st.caption("No advice text is ready to check. Nothing was approved or sent.")
        st.subheader("3 · Record a decision")
        note = st.text_area("Officer note or clarification request", key=f"note{cid}")
        confirmed = st.checkbox("Required for approval: I checked every advice line against the cited sources", key=f"confirm{cid}")
        status, preview = request("POST", f"/officer/cases/{cid}/voice-preview", headers=headers, json={"officer_text": farmer_text})
        script = None
        if status == 200 and preview.get("enabled"):
            st.text(preview["text"])
            if st.checkbox("I reviewed this exact spoken script", key=f"voice{cid}"):
                script = preview["text"]
        body = {"decision": "edit_approve" if text != case["draft"] else "approve", "edited_text": text,
                "farmer_text": farmer_text, "confirmed": confirmed, "expected_revision": case["revision"],
                "approved_voice_script": script, "note": note}

        def submit(candidate):
            status, data = request("POST", f"/officer/cases/{cid}/decision", headers=headers, json=candidate)
            show_result(status, data, candidate.get("farmer_text") or "")
            detail = data.get("detail", {})
            if isinstance(detail, dict) and detail.get("outcome") == "acknowledgement_required":
                st.session_state[f"challenge{cid}"] = {"body": candidate, "token": detail["acknowledgement"]}
            st.session_state[f"assessment_retry{cid}"] = status == 503

        if st.button("Approve and release", key=f"approve{cid}", type="primary", disabled=not confirmed):
            submit(body)
        # Retry only re-checks the text. Approving is always a separate click.
        if st.session_state.get(f"assessment_retry{cid}") and st.button("Retry assessment", key=f"assessment{cid}"):
            status, data = request("POST", f"/officer/cases/{cid}/assess", headers=headers, json={"farmer_text": farmer_text})
            if status == 200:
                st.session_state[f"assessment_retry{cid}"] = False
                st.info(f"Assessment complete: {data.get('outcome', 'unknown').replace('_', ' ')}. Nothing was approved or sent.")
                show_findings(data.get("findings", []), farmer_text)
            else:
                show_result(status, data)
        st.divider()
        st.caption("Reject or request information · A note and explicit confirmation are required. No advice is released.")
        for label, decision in (("Reject", "reject"), ("Request info", "request_info")):
            sure = st.checkbox(f"Confirm: {label.lower()} this case with the note above", key=f"sure{decision}{cid}")
            if st.button(label, key=f"{decision}{cid}", disabled=not (sure and note.strip())):
                submit(body | {"decision": decision})
        challenge = st.session_state.get(f"challenge{cid}")
        if challenge and challenge["body"] == body:
            acknowledged = st.checkbox("I reviewed and explicitly acknowledge the source concerns", key=f"ack{cid}")
            if st.button("Approve with acknowledgement", key=f"acksubmit{cid}", disabled=not (confirmed and acknowledged)):
                submit(body | {"acknowledgement": challenge["token"]})


def clear_officer_state():
    """Erase credentials, edits and acknowledgement challenges at sign-out."""
    for key in list(st.session_state):
        if key not in {'farmer_case_id', 'farmer_case_token', 'farmer_question', 'farmer_lookup_id', 'farmer_lookup_token', 'farmer_active_question'}:
            del st.session_state[key]


def load_review(case):
    """Bind fresh widgets to one server revision; never reuse stale confirmation."""
    cid = case['id']
    for prefix in ('draft', 'farmer', 'note', 'confirm', 'voice', 'challenge', 'assessment_retry', 'holds', 'ack', 'surereject', 'surerequest_info'):
        st.session_state.pop(f'{prefix}{cid}', None)
    st.session_state['review_case'] = case


def _question_preview(question: str) -> str:
    text = " ".join((question or "").split())
    if len(text) <= 90:
        return text or "Question"
    return text[:87] + "…"


@st.fragment(run_every="10s")
def review_queue(headers):
    status, queue = request("GET", "/officer/queue", headers=headers)
    if status == 401:
        clear_officer_state()
        st.session_state["officer_tab_forgotten"] = True
        st.session_state["_signout_note"] = "Your session has ended. Sign in again."
        st.rerun()
    if status != 200:
        show_result(status, queue if isinstance(queue, dict) else {})
        return
    st.caption(f"{len(queue)} questions awaiting action · Updates every 10 seconds")
    if not queue:
        st.info("No questions are waiting for review. A new farmer question will appear here automatically.")
    for case in queue:
        emergency = is_emergency_case(case)
        label = ("Emergency · " if emergency else "") + _question_preview(case.get("question") or "")
        if st.button(label, key=f"open{case['id']}", width="stretch"):
            load_review(case)
            st.rerun()
        if emergency:
            st.error("Emergency")
            for reason in emergency_reasons(case):
                st.caption(reason)
        st.caption(OFFICER_STATUS.get(case["status"], "Needs review"))
        st.caption(queue_actions(case))
        st.caption(f"Submitted {case.get('created_at', 'time unavailable')}")


def _email_sign_in():
    """POST /officer/auth/login. The session token stays in Streamlit server state and is never rendered."""
    note = st.session_state.pop("_signout_note", None)
    if note:
        st.info(note)
    login_error = st.session_state.get("_login_error")
    st.subheader("Sign in")
    st.caption("Use the email and password issued for your officer account.")
    with st.form("officer_email_signin", clear_on_submit=True):
        email = st.text_input("Email", key="officer_email_input")
        password = st.text_input("Password", type="password", key="officer_password_input")
        submitted = st.form_submit_button("Sign in", key="officer_email_submit")
    if login_error:
        st.error(login_error)
    if not submitted:
        return
    st.session_state.pop("_login_error", None)
    typed_email = email.strip()
    typed_password = password
    st.session_state["_drop_password"] = True
    result = classify_login(*request(
        "POST", "/officer/auth/login", json={"email": typed_email, "password": typed_password}))
    if result["ok"]:
        st.session_state["officer_token"] = result["token"]
        st.session_state["officer_auth_kind"] = "session"
        st.session_state["officer_email"] = result.get("email") or typed_email
        st.session_state["officer_expires_at"] = result.get("expires_at")
        st.session_state["officer_tab_forgotten"] = False
        st.rerun()
    st.session_state["_login_error"] = result["message"]
    st.rerun()


def officer_screen():
    # The officer session token stays in this Streamlit server session. It is not
    # written into the browser component, sessionStorage, or the page.
    if st.session_state.pop("_drop_password", False):
        st.session_state.pop("officer_password_input", None)
    tab_state("officer", forget=True)
    st.caption("AGRIREACH · EXTENSION OFFICER")
    st.title("Review queue" if st.session_state.get('officer_token') else "Officer sign in")
    st.write("Read the farmer's question, check the agricultural sources and safety findings, then approve or reject the exact answer.")
    if not st.session_state.get('officer_token'):
        _email_sign_in()
        return
    headers = auth_headers(st.session_state['officer_token'])
    status, me = request("GET", "/officer/auth/me", headers=headers)
    if status == 401:
        clear_officer_state()
        st.session_state['officer_tab_forgotten'] = True
        st.session_state['_signout_note'] = "Your session has ended. Sign in again."
        st.rerun()
    if status != 200 or not isinstance(me, dict):
        show_result(status, me if isinstance(me, dict) else {})
        return
    email = me.get("email") or st.session_state.get("officer_email")
    expires = me.get("expires_at") or st.session_state.get("officer_expires_at")
    who = f" as {email}" if email else ""
    st.caption(f"Signed in{who}. Session ends {expires or 'at the time set by the server'}.")
    if st.button("Sign out", key="officer_signout"):
        status, data = request("POST", "/officer/auth/logout", headers=headers)
        if status == 200 and isinstance(data, dict) and data.get("revoked") is True:
            note = "Signed out. This session can no longer be used."
        elif status == 200:
            note = "Signed out. The server said this session was already closed."
        else:
            note = ("This screen forgot the session, but the server did not confirm that it was revoked. "
                    "It remains valid until it expires or an operator revokes it.")
        clear_officer_state()
        st.session_state['officer_tab_forgotten'] = True
        st.session_state['_signout_note'] = note
        st.rerun()
    left, right = st.columns([1, 2], gap="large")
    with left:
        st.subheader("Review queue")
        review_queue(headers)
    with right:
        case = st.session_state.get('review_case')
        if case:
            if st.button("Reload case and discard unsaved edits", key="reload_case"):
                cid = case['id']
                status, current = request("GET", f"/officer/cases/{cid}", headers=headers)
                if status == 200:
                    load_review(current)
                    st.rerun()
                else:
                    show_result(status, current)
            # Edits stay tied to the loaded revision; concurrent decisions must
            # fail at the API until the officer explicitly reloads the case.
            render_case(case, headers)
        else:
            st.info("Choose a question from the queue to read it, check the sources, and record a decision.")
    with st.expander("Case history and delivery recovery"):
        status, cases = request("GET", "/officer/cases", headers=headers)
        if status == 200:
            for case in cases:
                st.caption(f"Case {case['id']}: {case['status'].replace('_', ' ')}")
                render_delivery(case["id"], headers, "history")
        else:
            show_result(status, cases)
    with st.expander("Return an unsent case to review"):
        cid = st.number_input("Case to reopen", min_value=1, step=1, key="reopen_id")
        reason = st.text_input("Additional information or reason for fresh review", key="reopen_reason")
        if st.button("Reload and reopen case", key="reopen_submit", disabled=not reason.strip()):
            status, case = request("GET", f"/officer/cases/{cid}", headers=headers)
            if status == 200:
                show_result(*request("POST", f"/officer/cases/{cid}/reopen", headers=headers,
                    json={"expected_revision": case["revision"], "information": reason}))
            else:
                show_result(status, case)


OFFICER_STATUS = {
    "pending_review": "Waiting for your review. The farmer cannot read an answer yet.",
    "draft": "Still being prepared. The farmer cannot read an answer yet.",
    "approved": "Approved. It has not been released to the farmer.",
    "released": "Released. The farmer can read the approved answer.",
    "rejected": "Rejected. No answer was released.",
    "needs_info": "More information was requested. No answer was released.",
    "not_delivered": "Release was not confirmed. Review it before trying again.",
    "undeliverable": "Delivery is unavailable because the recipient was removed.",
    "review_required": "Needs further review before an answer can be shown.",
}


STATES = {
    'pending_review': 'Waiting for officer review. Advice is not available yet.',
    'draft': 'Your question is being prepared for review.',
    'approved': 'Approved by an officer. Release is still pending.',
    'released': 'Approved response available.',
    'rejected': 'The officer rejected this advice. No advice was released.',
    'needs_info': 'The officer needs more information before approving advice.',
    'not_delivered': 'Delivery has not been confirmed. An officer must review it.',
    'undeliverable': 'Delivery is unavailable because the recipient was removed.',
    'review_required': 'This case needs further review before an answer can be shown.',
}


def _phone_problem(phone: str, consent: bool) -> str | None:
    """Farmer-facing phone feedback. The message does not repeat the typed number."""
    if not consent:
        return None
    raw = (phone or "").strip()
    if not raw:
        return "Enter a Ghana mobile number, or leave SMS updates unchecked."
    try:
        normalize_phone(raw)
    except PhoneError as exc:
        return str(exc)
    return None


def _clear_supplement():
    """Drop the reply target so a later question cannot post to an older case."""
    for key in ("farmer_supplement_case", "farmer_supplement_revision", "farmer_supplement_token"):
        st.session_state.pop(key, None)


def _bind_supplement(case_id, revision, token):
    st.session_state['farmer_supplement_case'] = case_id
    st.session_state['farmer_supplement_revision'] = revision
    st.session_state['farmer_supplement_token'] = token


def _check_case(cid, access_token):
    """Fetch one case with its private code and show the farmer-safe result.

    The API authorizes every call; a successful lookup becomes the tab's active question."""
    status, data = request("GET", f"/farmer/cases/{cid}", headers={"X-Case-Access-Token": access_token})
    if status == 200:
        st.session_state['farmer_tab_forgotten'] = False
        if st.session_state.get('farmer_case_id') != cid:
            st.session_state.pop('farmer_active_question', None)
        st.session_state['farmer_case_id'] = cid
        st.session_state['farmer_case_token'] = access_token
        tab_state('farmer', value={'case_id': cid, 'token': access_token,
                                   'question': st.session_state.get('farmer_active_question', '')},
                  instance='manual_lookup')
        notice = acknowledgement_text(data.get("acknowledgement") or {})
        if data.get("acknowledgement") and notice:
            st.info(notice)
        if data.get('clarification'):
            _bind_supplement(cid, data.get('revision'), access_token)
            if data.get("processing_failure"):
                st.warning(data.get("message") or "AgriReach could not finish preparing this question. No treatment advice has been approved.")
            else:
                st.info(data.get('message') or 'Awaiting your information before an officer can review this.')
            st.write(data['clarification'])
        else:
            _clear_supplement()
            if data.get("status") == "rejected":
                st.info(data.get("message") or (
                    "An extension officer reviewed this question and did not approve any advice. "
                    "Nothing was sent to you."))
            elif data.get("emergency"):
                st.error(data.get("message") or "This may be an emergency. Call 112 now or go to the nearest health facility. An extension officer has been alerted.")
            elif data.get("evidence_gap"):
                st.info(data.get("message") or "An extension officer will investigate this question. No treatment advice has been approved.")
            else:
                st.info(STATES.get(data['status'], 'Your case is being reviewed.'))
            if data.get('delivery_status'):
                st.caption('Delivery: ' + data['delivery_status'].replace('_', ' '))
            if data.get('answer'):
                _show_farmer_answer(data)
    elif status == 404:
        _clear_supplement()
        st.error("We could not find your question in this tab.")
    else:
        _clear_supplement()
        st.error("Unable to check the answer. Please try again shortly.")


def _show_farmer_answer(data):
    st.success(readable_advice(data.get("answer") or "", source_name))
    st.caption(provenance_caption(data))


def _farmer_session_headers():
    session = st.session_state.get("farmer_session")
    return {"X-Farmer-Session": session} if isinstance(session, str) and session else None


def _ensure_farmer_session():
    """Create the private session once. A phone number is not a session."""
    current = st.session_state.get("farmer_session")
    if isinstance(current, str) and current:
        return current
    status, data = request("POST", "/farmer/session")
    if status == 200 and isinstance(data, dict) and isinstance(data.get("farmer_session"), str) and data["farmer_session"]:
        st.session_state["farmer_session"] = data["farmer_session"]
        st.session_state["farmer_session_expires"] = data.get("expires_at")
        return data["farmer_session"]
    if status == 429:
        st.warning("Too many questions were sent from this connection. Wait a few minutes and try again. Nothing new was saved.")
        return False
    return None


def _show_farmer_session_questions():
    """List only the cases the current private session filed. Never by phone number."""
    headers = _farmer_session_headers()
    if not headers:
        return
    status, items = request("GET", "/farmer/session/cases", headers=headers)
    if status == 401:
        st.session_state.pop("farmer_session", None)
        st.session_state.pop("farmer_session_expires", None)
        st.info("This private session has ended. Ask again in this tab. A phone number does not restore it.")
        return
    if status != 200 or not isinstance(items, list) or not items:
        return
    st.subheader("Questions in this private session")
    st.caption("These are the questions asked with this tab's private session. A phone number does not open another person's questions.")
    for item in items:
        st.markdown(f"**{item.get('question') or 'Question'}**")
        if item.get("answer"):
            _show_farmer_answer(item)
        elif item.get("message"):
            st.info(item["message"])
        else:
            st.caption(STATES.get(item.get("status"), "Waiting for an update."))
        notice = acknowledgement_text(item.get("acknowledgement") or {})
        if item.get("acknowledgement") and notice:
            st.caption(notice)


def farmer_screen():
    # Browser tab state survives refresh, not tab closure. Verify a restored
    # case credential with the same API used for a manual case lookup.
    forgotten = st.session_state.get('farmer_tab_forgotten', False)
    active = st.session_state.get('farmer_case_id') and st.session_state.get('farmer_case_token')
    value = ({'case_id': st.session_state['farmer_case_id'],
              'token': st.session_state['farmer_case_token'],
              'question': st.session_state.get('farmer_active_question', '')} if active else None)
    stored = tab_state('farmer', value=value, forget=forgotten)
    if not forgotten and not active and isinstance(stored, dict):
        cid, token = stored.get('case_id'), stored.get('token')
        if type(cid) is int and cid > 0 and isinstance(token, str) and token:
            status, _ = request('GET', f'/farmer/cases/{cid}',
                                headers={'X-Case-Access-Token': token})
            if status == 200:
                st.session_state['farmer_case_id'] = cid
                st.session_state['farmer_case_token'] = token
                st.session_state['farmer_active_question'] = stored.get('question', '')
                st.rerun()
            if status == 404:
                st.session_state['farmer_tab_forgotten'] = True
                st.rerun()
    st.title("Ask about your crop")
    st.write("AgriReach helps farmers in Ghana ask a crop question. An extension officer checks every answer before you can read it.")
    st.caption("You ask. Agricultural sources are gathered. An officer reviews safety. You can read an answer only after it is released.")
    with st.container(border=True):
        st.subheader("Ask a question")
        with st.form('farmer_submit'):
            question = st.text_area("Your question", key="farmer_question", placeholder="What crop are you growing, where, and what do you need help with?")
            phone_input = st.text_input("Phone number for text updates (optional)", key="farmer_phone", placeholder="Ghana mobile number")
            consent = st.checkbox(
                "I agree that AgriReach may text this number about this question, and may send approved advice when that is available.",
                key="farmer_sms_consent", value=False)
            st.caption("The box starts unchecked. A phone number does not sign you in. Leave the number blank if you do not want text updates.")
            submitted = st.form_submit_button("Ask for advice", key="farmer_submit_button", type="primary")
        if submitted:
            phone = phone_input
            if not question.strip():
                st.warning("Enter a question before sending.")
            elif problem := _phone_problem(phone, consent):
                st.warning(problem)
            else:
                payload = {"question": question}
                if consent:
                    payload["phone"] = phone.strip()
                    payload["sms_consent"] = True
                with st.spinner("Saving your question…"):
                    session = _ensure_farmer_session()
                    if session is False:
                        status, data = None, None
                    else:
                        status, data = request("POST", "/ask", headers=_farmer_session_headers(), json=payload)
                if status == 200:
                    st.session_state['farmer_tab_forgotten'] = False
                    st.session_state['farmer_case_id'] = data['case_id']
                    st.session_state['farmer_case_token'] = data['access_token']
                    tab_state('farmer', value={'case_id': data['case_id'], 'token': data['access_token'],
                                               'question': question.strip()}, instance='submission')
                    st.session_state['farmer_lookup_id'] = data['case_id']
                    st.session_state['farmer_lookup_token'] = data['access_token']
                    st.success("Your question has been received.")
                    st.session_state['farmer_active_question'] = question.strip()
                    notice = acknowledgement_text(data.get("acknowledgement") or {})
                    if data.get("acknowledgement") and notice:
                        st.info(notice)
                    if data.get('clarification'):
                        _bind_supplement(data['case_id'], data.get('revision'), data['access_token'])
                        st.info(data.get('message') or 'Awaiting your information before an officer can review this.')
                        st.write(data['clarification'])
                    else:
                        _clear_supplement()
                        if data.get("emergency"):
                            st.error(data.get("message") or "This may be an emergency. Call 112 now or go to the nearest health facility. An extension officer has been alerted.")
                        elif data.get("evidence_gap"):
                            st.info(data.get("message") or "An extension officer will investigate this question. No treatment advice has been approved.")
                        elif data.get("status") == "pending_review":
                            st.caption("It is waiting for an extension officer to review. Advice is not available yet.")
                elif status == 422:
                    st.warning("Check the phone number. Use a Ghana mobile number, or leave the phone field blank.")
                elif status is not None:
                    st.error("We could not send your question. Nothing was saved. Please try again shortly.")
    active_id = st.session_state.get('farmer_case_id')
    active_token = st.session_state.get('farmer_case_token')
    with st.container(border=True):
        st.subheader("2 · Your question")
        _show_farmer_session_questions()
        lookup = None
        if active_id and active_token:
            question_text = st.session_state.get('farmer_active_question')
            if question_text:
                st.markdown(f"**{question_text}**")
            else:
                st.caption("Your question is saved in this tab.")
            # The private code survives a refresh in tab-scoped browser storage,
            # never in a URL. Every API check still validates the credential.
            st.caption("Refreshing this page keeps the question in this tab. "
                       "Closing the tab removes it from this device. A phone number does not sign you in.")
            refresh_col, forget_col = st.columns(2)
            if refresh_col.button("Check for updates", key="farmer_refresh", type="primary", width="stretch"):
                lookup = (int(active_id), active_token)
            if forget_col.button("Forget this question on this device", key="farmer_forget", width="stretch"):
                for key in ('farmer_case_id', 'farmer_case_token', 'farmer_lookup_id', 'farmer_lookup_token', 'farmer_active_question'):
                    st.session_state.pop(key, None)
                _clear_supplement()
                st.session_state['farmer_tab_forgotten'] = True
                st.rerun()
        else:
            st.caption("After you ask, the status of this question appears here.")
        with st.expander("Look up a question from a closed tab", expanded=False):
            st.caption("Use this only when this tab no longer has the question. You need the question number and private code. This does not sign you in.")
            st.session_state.setdefault('farmer_lookup_id', st.session_state.get('farmer_case_id', 1))
            st.session_state.setdefault('farmer_lookup_token', st.session_state.get('farmer_case_token', ''))
            cid = st.number_input("Question number", min_value=1, step=1, key="farmer_lookup_id")
            access_token = st.text_input("Private access code", type="password", key="farmer_lookup_token",
                help="Only needed if this browser tab no longer has your question.")
            if st.button("Check answer", key="farmer_check"):
                lookup = (int(cid), access_token.strip())
        if lookup:
            with st.spinner("Checking your question…"):
                _check_case(*lookup)
        supplement_case = st.session_state.get('farmer_supplement_case')
        if st.session_state.get('farmer_supplement_revision') and supplement_case:
            with st.form('farmer_supplement'):
                st.caption("Add the missing detail for this question.")
                reply = st.text_input('Add the missing detail', key='farmer_supplement_text')
                if st.form_submit_button('Send details', key='farmer_supplement_button'):
                    status, data = request('POST', f"/farmer/cases/{supplement_case}/supplement",
                                           headers={'X-Case-Access-Token': st.session_state['farmer_supplement_token']},
                                           json={'text': reply, 'expected_revision': st.session_state['farmer_supplement_revision']})
                    if status == 200 and data.get('clarification'):
                        _bind_supplement(supplement_case, data.get('revision'), st.session_state['farmer_supplement_token'])
                        if data.get("processing_failure"):
                            st.warning(data.get("message") or "AgriReach could not finish preparing this question. No treatment advice has been approved.")
                        else:
                            st.info(data.get('message') or 'Awaiting your information before an officer can review this.')
                        st.write(data['clarification'])
                    elif status == 200:
                        _clear_supplement()
                        if data.get("emergency"):
                            st.error(data.get("message") or "This may be an emergency. Call 112 now or go to the nearest health facility. An extension officer has been alerted.")
                        elif data.get("evidence_gap"):
                            st.info(data.get("message") or "An extension officer will investigate this question. No treatment advice has been approved.")
                        elif data.get("status") == "rejected":
                            st.info(data.get("message") or "An extension officer reviewed this question and did not approve any advice. Nothing was sent to you.")
                        elif data.get("status") == "pending_review":
                            st.success(data.get('message') or 'Your question has been received. It is waiting for an extension officer to review.')
                        else:
                            st.success(data.get('message') or 'Your question has been received.')
                    else:
                        st.error("We could not save that detail. Nothing new was approved. Please try again shortly.")


def main(role="farmer"):
    st.set_page_config(
        page_title="AgriReach · Crop advice checked by an officer",
        page_icon="🌱",
        layout="wide" if role == "officer" else "centered",
    )
    st.markdown("""<style>
    .stApp { background: #f6f8f2; color: #173b2c; }
    [data-testid="stSidebar"] { background: #e8efdf; }
    .block-container { max-width: 1180px; padding-top: 4.5rem; }
    [data-testid="stCaptionContainer"] { opacity: 1 !important; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #4c6255 !important; }
    h1,h2,h3 { color: #173b2c; letter-spacing: -.025em; }
    .stButton>button, .stFormSubmitButton>button { min-height: 48px; border-radius: 8px; border-color: #507447; }
    [data-testid="stAlert"] { border-radius: 8px; }
    @media(max-width:800px) {
      .block-container { padding: 4.5rem 1rem 1rem; }
      [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important; }
    }
    </style>""", unsafe_allow_html=True)
    st.markdown("### 🌱 AgriReach")
    status, health = request("GET", "/health")
    if status != 200:
        st.warning("The service is unavailable. Try again shortly.")
    elif role == 'officer' and health.get('draft_mode') == 'stub':
        st.info("This server is preparing new drafts from saved sources. A question still shows earlier model calls when its record includes them.")
    if role == 'officer':
        officer_screen()
    else:
        farmer_screen()


if __name__ == "__main__":
    main()
