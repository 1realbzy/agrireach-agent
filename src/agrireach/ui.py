"""Officer and farmer screens with explicit workflow feedback and safe sign in."""
import logging
import os
import re

import httpx
import streamlit as st

from agrireach import knowledge, llm
from agrireach.ui_feedback import auth_headers, feedback

API = os.getenv("AGRIREACH_API", "http://127.0.0.1:8000")
logger = logging.getLogger(__name__)

# Visual tokens from DESIGN.md (Nature Distilled, https://designmd.app/library/nature-distilled), adapted for contrast. Logic is unchanged.
THEME_CSS = """
<style>
:root {
  --ar-primary: #2D5A27;
  --ar-primary-hover: #234720;
  --ar-accent: #C67B5C;
  --ar-bg: #F5F0E1;
  --ar-surface: #FFF9F0;
  --ar-surface-strong: #EDE4D0;
  --ar-border: #C9B89A;
  --ar-soil: #6B3E24;
  --ar-text: #2C2118;
  --ar-muted: #6B5E4E;
  --ar-focus: #E0A84A;
  --ar-error: #8B2E1F;
  --ar-success: #6B7B3C;
  --ar-font: ui-sans-serif, "Segoe UI", system-ui, "Helvetica Neue", Helvetica, Arial, sans-serif;
  --ar-radius: 12px;
  --ar-radius-sm: 8px;
  --ar-shadow: 0 2px 12px rgba(44, 33, 24, 0.08);
}
html, body, [data-testid="stAppViewContainer"], .stApp, .stMarkdown, .stText, .stCaption,
[data-testid="stWidgetLabel"], [data-testid="stExpander"] {
  font-family: var(--ar-font) !important;
  color: var(--ar-text);
}
.stApp { background: var(--ar-bg); }
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], footer {
  display: none !important;
}
.block-container { padding-top: 0 !important; max-width: 1200px; }
.ar-masthead, .ar-service {
  position: relative;
  left: 50%;
  right: 50%;
  margin-left: -50vw;
  margin-right: -50vw;
  width: 100vw;
  box-sizing: border-box;
}
.ar-masthead {
  background: #2D5A27 !important;
  color: #FFF9F0 !important;
  padding: 14px 24px;
}
.ar-masthead, .ar-masthead * { color: #FFF9F0 !important; background: transparent; }
.ar-masthead-inner { font-weight: 700; font-size: 1.15rem; letter-spacing: 0.04em; }
.ar-service {
  background: var(--ar-surface);
  border-bottom: 1px solid var(--ar-border);
  margin-bottom: 1.5rem;
  padding: 18px 24px 20px;
  box-shadow: var(--ar-shadow);
}
.ar-service h1 {
  font-size: 1.7rem;
  font-weight: 700;
  line-height: 1.2;
  margin: 0 0 4px;
  color: var(--ar-text);
}
.ar-service p { margin: 0; color: var(--ar-muted); font-size: 1rem; }
.ar-badge {
  display: inline-block;
  background: #C67B5C;
  color: #FFF9F0;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 0.25rem 0.6rem;
  border-radius: 999px;
  margin: 0.2rem 0 0.6rem;
}
h3.ar-section {
  font-family: var(--ar-font);
  font-size: 1.15rem;
  font-weight: 700;
  margin: 1.25rem 0 0.4rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--ar-border);
  color: var(--ar-text);
}
h3.ar-section:first-child, .ar-first h3.ar-section { border-top: 0; padding-top: 0; }
.ar-panel-label {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--ar-soil);
  margin: 0.5rem 0 0.2rem;
}
details, [data-testid="stExpander"] {
  border: 1px solid var(--ar-border) !important;
  border-radius: var(--ar-radius) !important;
  background: var(--ar-surface) !important;
  box-shadow: var(--ar-shadow);
  margin-bottom: 1rem;
}
[data-testid="stExpander"] details { border: 0 !important; margin-bottom: 0; box-shadow: none; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {
  font-weight: 700 !important;
  font-size: 1.05rem !important;
}
.stButton > button {
  border-radius: var(--ar-radius-sm) !important;
  font-weight: 600 !important;
  border: 1px solid var(--ar-soil) !important;
  background: var(--ar-surface) !important;
  color: var(--ar-text) !important;
  padding: 0.55rem 1.05rem !important;
  box-shadow: var(--ar-shadow) !important;
}
.stButton > button:hover { background: var(--ar-surface-strong) !important; }
.stButton > button:focus, .stButton > button:focus-visible {
  outline: 3px solid var(--ar-focus) !important;
  outline-offset: 2px !important;
  box-shadow: none !important;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"] {
  background: var(--ar-primary) !important;
  color: #FFF9F0 !important;
  border-color: var(--ar-primary) !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover {
  background: var(--ar-primary-hover) !important;
  border-color: var(--ar-primary-hover) !important;
}
.stButton > button:disabled {
  opacity: 0.45 !important;
  background: var(--ar-surface-strong) !important;
  color: var(--ar-muted) !important;
  border-color: var(--ar-border) !important;
  box-shadow: none !important;
}
.stTextInput input, .stTextArea textarea, .stNumberInput input, [data-baseweb="select"] {
  border-radius: var(--ar-radius-sm) !important;
  border-color: var(--ar-border) !important;
  background: #FFFdf8 !important;
}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {
  outline: 3px solid var(--ar-focus) !important;
  outline-offset: 0 !important;
  box-shadow: none !important;
}
[data-testid="stAlert"] { border-radius: var(--ar-radius-sm) !important; border-left-width: 5px !important; }
div[data-testid="stTabs"] button[data-baseweb="tab"] {
  font-weight: 600;
  color: var(--ar-text);
}
div[data-testid="stTabs"] button[aria-selected="true"] {
  border-bottom: 4px solid var(--ar-primary) !important;
}
@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
</style>
"""


def apply_theme():
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    st.markdown(
        '<div class="ar-masthead"><div class="ar-masthead-inner">AgriReach</div></div>'
        '<div class="ar-service"><h1>Agricultural advisory review</h1>'
        '<p>Advice reaches a farmer only after it is released: by a named officer, or automatically when a routine case passes every safety check.</p></div>',
        unsafe_allow_html=True,
    )


def request(method, path, **kwargs):
    """Handle service errors without displaying credentials or internal exceptions."""
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
          "SOURCE_CONFLICT": "Cited sources disagree"}


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
    else:
        st.success("No safety holds on the current farmer text.")


def source_name(passage_id):
    """Show a source as its title and page, not its internal ID."""
    ref = knowledge.reference(passage_id) or {}
    title = (ref.get("source") or {}).get("title")
    return f"{title}, {ref['page']}" if title and ref.get("page") else title or "Cited source"


def heading(title):
    st.markdown(f'<h3 class="ar-section">{title}</h3>', unsafe_allow_html=True)


def render_delivery(case_id, headers, key):
    status, jobs = request("GET", f"/officer/cases/{case_id}/delivery-jobs", headers=headers)
    if status != 200:
        show_result(status, jobs)
        return
    for job in jobs:
        st.caption(f"Delivery {job['id']}: {job['state'].replace('_', ' ')}")
        if job["state"] == "unknown":
            evidence = st.text_input("Verified provider evidence reference", key=f"evidence{key}{job['id']}")
            disposition = st.selectbox("Verified provider outcome", ["accepted", "definitely_failed"], key=f"disposition{key}{job['id']}")
            verified = st.checkbox("I checked the provider record and verified this outcome", key=f"verified{key}{job['id']}")
            if st.button("Record reconciliation without sending", key=f"reconcile{key}{job['id']}", disabled=not (verified and evidence.strip())):
                show_result(*request("POST", f"/officer/delivery-jobs/{job['id']}/reconcile", headers=headers,
                    json={"accepted": disposition == "accepted", "provider_evidence": evidence}))


def render_case(case, headers):
    cid = case["id"]
    with st.expander(f"Case {cid}: {case['question']}"):
        if case.get("auto_released"):
            render_auto_audit(case, headers)
        render_delivery(cid, headers, "queue")
        if case["status"] == "not_delivered" and st.button("Retry release and delivery", key=f"retry{cid}"):
            show_result(*request("POST", f"/cases/{cid}/release", headers=headers))
        heading("Case")
        st.markdown(f'<div class="ar-panel-label">Farmer question</div>', unsafe_allow_html=True)
        st.text(case["question"])
        st.caption("Status: " + case["status"].replace("_", " "))
        heading("Evidence and citations")
        st.caption("Sources: " + "; ".join(source_name(s) for s in case["sources"]))
        voice_status, inbound = request("GET", f"/officer/cases/{cid}/voice", headers=headers)
        if voice_status == 200 and inbound.get("has_audio"):
            # Keep the officer's ability to verify the machine transcript.
            try:
                audio = httpx.get(f"{API}/officer/cases/{cid}/audio", headers=headers, timeout=30)
                if audio.status_code == 200:
                    st.audio(audio.content)
            except httpx.HTTPError:
                st.warning("Voice note unavailable. Ask the operator to restore access before relying on the transcript.")
            st.text("Machine transcript: " + (inbound.get("transcript") or ""))
        # The offline label is for logs and tests; officers see only the advice.
        shown = "\n".join(l for l in case["draft"].splitlines() if not l.startswith(llm.STUB_LABEL))
        # Officers see numbered citations; edits are mapped back to the source IDs before saving.
        shown, cites = number_citations(shown)
        heading("Draft advice")
        edited = st.text_area("Officer draft with citations", shown, key=f"draft{cid}")
        for n, cite in enumerate(cites, 1):
            st.caption(f"[{n}] " + source_name(cite[1:-1]))
        text = case["draft"] if edited == shown else restore_citations(edited, cites)
        if st.button("Re-propose farmer text", key=f"repropose{cid}"):
            status, proposal = request("POST", f"/officer/cases/{cid}/farmer-draft", headers=headers, json={"officer_text": text})
            if status == 200:
                st.session_state[f"farmer{cid}"] = proposal.get("text", "")
                st.info("New proposal prepared. Check it against the sources before approving.")
            else:
                show_result(status, proposal)
        farmer_text = st.text_area("Farmer text: exactly what will be sent", case.get("farmer_text") or (case.get("farmer_draft") or {}).get("text", ""), key=f"farmer{cid}")
        heading("Safety flags")
        show_holds(cid, farmer_text, headers)
        heading("Decision")
        st.caption("Edit the draft or farmer text if needed, then approve, or reject / request more information.")
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
        reject_col, info_col = st.columns(2)
        for column, label, decision in ((reject_col, "Reject", "reject"), (info_col, "Request info", "request_info")):
            with column:
                sure = st.checkbox(f"Confirm: {label.lower()} this case with the note above", key=f"sure{decision}{cid}")
                if st.button(label, key=f"{decision}{cid}", disabled=not (sure and note.strip())):
                    submit(body | {"decision": decision})
        challenge = st.session_state.get(f"challenge{cid}")
        if challenge and challenge["body"] == body:
            acknowledged = st.checkbox("I reviewed and explicitly acknowledge the source concerns", key=f"ack{cid}")
            if st.button("Approve with acknowledgement", key=f"acksubmit{cid}", type="primary", disabled=not (confirmed and acknowledged)):
                submit(body | {"acknowledgement": challenge["token"]})


def render_auto_audit(case, headers):
    """Show why a case was auto-released, and let the officer retract it when delivery is not accepted."""
    audit = case.get("auto_release") or {}
    st.markdown('<div class="ar-badge">Auto-released</div>', unsafe_allow_html=True)
    if audit.get("retracted"):
        st.warning("This auto-released answer was later flagged and returned to the review queue.")
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    raw = audit.get("released_at") or case.get("decided_at")
    when = "unknown"
    if raw:
        try:
            when = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(ZoneInfo("Africa/Nairobi")).strftime("%d %b %Y, %H:%M East Africa Time")
        except ValueError:
            when = raw
    st.caption("Released at: " + when)
    st.caption("Why it qualified: " + (audit.get("reason") or "routine_allowlisted_judge_passed").replace("_", " "))
    st.markdown('<div class="ar-panel-label">Released answer</div>', unsafe_allow_html=True)
    st.text(audit.get("farmer_text") or case.get("farmer_text") or "")
    heading("Evidence")
    for source in audit.get("sources") or []:
        st.caption((source.get("title") or source.get("id") or "Cited source") + (f", {source['page']}" if source.get("page") else ""))
    heading("Judge result")
    st.caption("Judge: " + (audit.get("judge_status") or "unknown"))
    for verdict in audit.get("verdicts") or []:
        st.caption(f"Line {verdict.get('n')}: {verdict.get('verdict')}")
    if case.get("status") == "released" and not audit.get("retracted"):
        flag = st.text_input("Reason to flag this auto-released answer for officer review", key=f"flagreason{case['id']}")
        if st.button("Flag and return to review", key=f"flag{case['id']}", disabled=not flag.strip()):
            show_result(*request("POST", f"/officer/cases/{case['id']}/reopen", headers=headers,
                json={"expected_revision": case["revision"], "information": flag}))



FARMER_REVIEWING = "An officer is reviewing this."
FARMER_REJECTED = "An officer reviewed this question and could not approve it. Please ask again, or send more detail."
FARMER_NEEDS_INFO = "An officer has asked for more information. Please send a new question with the details they need."


def farmer_waiting_message(payload: dict) -> str:
    """Farmer-facing status when no answer is available. Never includes a case number."""
    status = payload.get("status")
    if status == "rejected":
        return FARMER_REJECTED
    if status == "needs_info":
        return FARMER_NEEDS_INFO
    return payload.get("message") or FARMER_REVIEWING


def render_farmer_case(payload: dict) -> None:
    if payload.get("answer"):
        if payload.get("auto_released"):
            st.caption("Auto-released")
        st.success(payload["answer"])
        return
    message = farmer_waiting_message(payload)
    if payload.get("status") == "rejected":
        st.warning(message)
    else:
        st.info(message)


@st.fragment(run_every=2)
def watch_farmer_case():
    """Poll the pending case stored in session state. Reloading the page drops this id."""
    cid = st.session_state.get("farmer_case_id")
    if not cid:
        return
    status, data = request("GET", f"/farmer/cases/{cid}")
    if status == 200:
        render_farmer_case(data)
    else:
        show_result(status, data)


def officer_screen():
    if not st.session_state.get("officer_token"):
        email = st.text_input("Officer email")
        password = st.text_input("Officer password", type="password")
        if st.button("Sign in"):
            status, data = request("POST", "/officer/login", json={"email": email, "password": password})
            if status == 200 and isinstance(data, dict) and data.get("token"):
                st.session_state.officer_token = data["token"]
                st.session_state.officer_name = data.get("officer") or ""
                st.rerun()
            elif status == 429:
                st.error((data.get("detail") if isinstance(data, dict) else None) or "Too many sign-in attempts. Try again later.")
            else:
                st.error("Sign in details were not recognised.")
        else:
            st.info("Sign in with your officer email and password to see the review queue.")
        return
    headers = auth_headers(st.session_state.officer_token)
    signed = st.session_state.get("officer_name") or "Signed in"
    st.caption(signed)
    if st.button("Sign out"):
        request("POST", "/officer/logout", headers=headers)
        st.session_state.pop("officer_token", None)
        st.session_state.pop("officer_name", None)
        st.rerun()
    if st.button("Reload cases"):
        st.rerun()
    status, queue = request("GET", "/officer/queue", headers=headers)
    if status != 200:
        show_result(status, queue)
        return
    heading("Review queue")
    if not queue:
        st.info("No cases waiting for review.")
    status, released = request("GET", "/officer/cases", params={"status": "released"}, headers=headers)
    auto_cases = [c for c in (released or []) if isinstance(c, dict) and c.get("auto_released")] if status == 200 else []
    heading("Auto-released")
    if status != 200:
        show_result(status, released)
    elif not auto_cases:
        st.caption("No auto-released cases yet.")
    else:
        for case in auto_cases:
            with st.expander(f"Auto-released case {case['id']}: {case['question']}", expanded=True):
                render_auto_audit(case, headers)
    with st.expander("Case history and delivery recovery"):
        status, cases = request("GET", "/officer/cases", headers=headers)
        if status == 200:
            for case in cases:
                st.caption(f"Case {case['id']}: {case['status'].replace('_', ' ')}")
                render_delivery(case["id"], headers, "history")
        else:
            show_result(status, cases)
    with st.expander("Return an unsent case to review"):
        cid = st.number_input("Case to reopen", min_value=1, step=1)
        reason = st.text_input("Additional information or reason for fresh review")
        if st.button("Reload and reopen case", disabled=not reason.strip()):
            status, case = request("GET", f"/officer/cases/{cid}", headers=headers)
            if status == 200:
                show_result(*request("POST", f"/officer/cases/{cid}/reopen", headers=headers,
                    json={"expected_revision": case["revision"], "information": reason}))
            else:
                show_result(status, case)
    for case in queue:
        render_case(case, headers)


def main():
    st.set_page_config(page_title="AgriReach", layout="wide")
    apply_theme()
    status, health = request("GET", "/health")
    if status != 200:
        st.warning("The service is unavailable. Try again shortly.")
    elif health.get("draft_mode") == "stub":
        st.caption("Drafting is in offline stub mode. Configure a model to produce a live advisory draft.")
    else:
        if health.get("auto_release"):
            st.caption("A language model will draft each advisory. Routine, low-risk answers may be auto-released after the safety checks and judge pass; everything else waits for a named officer.")
        else:
            st.caption("A language model will draft each advisory. A named officer still has to approve it.")
    farmer, voice, officer = st.tabs(["Farmer", "Voice note simulator", "Extension officer"])
    with farmer:
        question = st.text_area("Your question", "When should I plant soybean in Tamale?")
        if st.button("Send"):
            status, data = request("POST", "/ask", json={"question": question})
            if status == 200:
                st.session_state.farmer_case_id = data.get("case_id")
            else:
                st.session_state.pop("farmer_case_id", None)
                show_result(status, data)
        watch_farmer_case()
    with voice:
        st.caption("Local demonstration only. Use a simulated sender, never a real number.")
        sender = st.text_input("Simulated sender", "sim:farmer-1")
        clip = st.file_uploader("Voice note", type=["wav", "ogg", "mp3", "m4a"])
        typed = st.text_input("Or type a question")
        if st.button("Send to AgriReach"):
            status, data = request("POST", "/channels/simulator/inbound", data={"sender": sender, "text": typed},
                files={"audio": (clip.name, clip.getvalue())} if clip else None)
            show_result(status, data)
        if st.button("Show messages"):
            status, data = request("GET", "/channels/simulator/outbox", params={"sender": sender})
            if status == 200:
                for message in data:
                    st.info(message["text"])
            else:
                show_result(status, data)
    with officer:
        officer_screen()


if __name__ == "__main__":
    main()
