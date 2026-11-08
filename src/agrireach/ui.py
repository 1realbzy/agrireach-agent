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
    with st.expander(f"Case {cid}: {case['question']}", expanded=True):
        st.caption(f"{case['status'].replace('_', ' ').title()} | Revision {case['revision']} | Human approval required")
        for reason in case.get('urgent_reasons', []):
            st.warning(reason)
        render_delivery(cid, headers, "queue")
        if case["status"] == "not_delivered" and st.button("Retry release and delivery", key=f"retry{cid}"):
            show_result(*request("POST", f"/cases/{cid}/release", headers=headers))
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
            if inbound.get('transcript'):
                st.text("Machine transcript: " + inbound['transcript'])
            else:
                st.warning("No machine transcript is available. Listen to the recording before reviewing this case.")
        if llm.STUB_LABEL in case['draft']:
            st.warning("Offline demonstration draft: assembled from sources. No language model was used.")
        shown = "\n".join(l for l in case["draft"].splitlines() if not l.startswith(llm.STUB_LABEL))
        # Officers see numbered citations; edits are mapped back to the source IDs before saving.
        shown, cites = number_citations(shown)
        edited = st.text_area("Officer draft with citations", shown, key=f"draft{cid}")
        for n, cite in enumerate(cites, 1):
            st.caption(f"[{n}] " + source_name(cite[1:-1]))
        with st.expander("Read source evidence"):
            for source_id in case['sources']:
                ref = knowledge.reference(source_id)
                st.markdown('**' + source_name(source_id) + '**')
                if ref:
                    st.text(ref.get('text', ''))
        text = case["draft"] if edited == shown else restore_citations(edited, cites)
        if st.button("Re-propose farmer text", key=f"repropose{cid}"):
            status, proposal = request("POST", f"/officer/cases/{cid}/farmer-draft", headers=headers, json={"officer_text": text})
            if status == 200:
                st.session_state[f"farmer{cid}"] = proposal.get("text", "")
                st.info("New proposal prepared. Check it against the sources before approving.")
            else:
                show_result(status, proposal)
        farmer_text = st.text_area("Farmer text: exactly what will be sent", case.get("farmer_text") or (case.get("farmer_draft") or {}).get("text", ""), key=f"farmer{cid}")
        show_holds(cid, farmer_text, headers)
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

        if st.button("Approve and release", key=f"approve{cid}", disabled=not confirmed):
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
        if key not in {'farmer_case_id', 'farmer_case_token', 'farmer_question', 'farmer_lookup_id', 'farmer_lookup_token'}:
            del st.session_state[key]


def load_review(case):
    """Bind fresh widgets to one server revision; never reuse stale confirmation."""
    cid = case['id']
    for prefix in ('draft', 'farmer', 'note', 'confirm', 'voice', 'challenge', 'assessment_retry', 'holds', 'ack', 'surereject', 'surerequest_info'):
        st.session_state.pop(f'{prefix}{cid}', None)
    st.session_state['review_case'] = case


@st.fragment(run_every="10s")
def review_queue(headers):
    status, queue = request("GET", "/officer/queue", headers=headers)
    if status != 200:
        show_result(status, queue)
        return
    st.caption(f"{len(queue)} cases awaiting action · Updates every 10 seconds")
    if not queue:
        st.info("No cases waiting for review. New farmer questions will appear here automatically.")
    for case in queue:
        if st.button(f"Open case {case['id']} · {case['status'].replace('_', ' ')}", key=f"open{case['id']}", width="stretch"):
            load_review(case)
            st.rerun()
        st.caption(case['question'])


def officer_screen():
    st.title("Officer workspace")
    st.write("Review the question, verify source evidence, and approve the exact response the farmer will receive.")
    if not st.session_state.get('officer_token'):
        with st.form('officer_signin', clear_on_submit=True):
            token = st.text_input("Officer sign in token", type="password", key="officer_token_input",
                help="Use the officer credential issued by the operator. A farmer case access token cannot sign in here.")
            submitted = st.form_submit_button("Sign in", key="officer_signin_submit")
        st.caption("Paste the officer token issued by your operator. A farmer case access token cannot sign in here. Do not include quotes or a Bearer prefix; the token stays masked.")
        if submitted:
            status, queue = request("GET", "/officer/queue", headers=auth_headers(token))
            if status == 200:
                st.session_state['officer_token'] = token.strip()
                st.rerun()
            else:
                show_result(status, queue)
        else:
            st.info("Sign in with your officer token to see the review queue.")
        return
    headers = auth_headers(st.session_state['officer_token'])
    status, _ = request("GET", "/officer/queue", headers=headers)
    if status == 401:
        clear_officer_state()
        st.rerun()
    if status != 200:
        show_result(status, {})
        return
    if st.button("Sign out", key="officer_signout"):
        clear_officer_state()
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
            st.info("Choose a case from the queue to review its advice and sources.")
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


def farmer_screen():
    st.title("Advice for your next step")
    st.write("Ask an agricultural question. An extension officer checks the advice before you receive it.")
    st.caption("This pilot uses Ghanaian source material and locations. It is not validated Kenyan farming guidance.")
    with st.container(border=True):
        st.subheader("1 · Ask a question")
        with st.form('farmer_submit'):
            question = st.text_area("Your question", key="farmer_question", placeholder="What crop are you growing, where, and what do you need help with?")
            submitted = st.form_submit_button("Send question", key="farmer_submit_button")
        if submitted:
            if not question.strip():
                st.warning("Enter a question before sending.")
            else:
                with st.spinner("Preparing your question for officer review…"):
                    status, data = request("POST", "/ask", json={"question": question})
                if status == 200:
                    st.session_state['farmer_case_id'] = data['case_id']
                    st.session_state['farmer_case_token'] = data['access_token']
                    st.session_state['farmer_lookup_id'] = data['case_id']
                    st.session_state['farmer_lookup_token'] = data['access_token']
                    st.success(f"Case {data['case_id']} created. Keep your private access token to check the answer.")
                    if data.get('clarification'):
                        st.info(data['clarification'])
                else:
                    show_result(status, data)
    with st.container(border=True):
        st.subheader("2 · Check your answer")
        st.caption("Save your case number and private token before closing this browser. This token opens only your case; it is not an officer sign-in token.")
        st.session_state.setdefault('farmer_lookup_id', st.session_state.get('farmer_case_id', 1))
        st.session_state.setdefault('farmer_lookup_token', st.session_state.get('farmer_case_token', ''))
        cid = st.number_input("Check case number", min_value=1, step=1, key="farmer_lookup_id")
        access_token = st.text_input("Case access token", type="password", key="farmer_lookup_token")
        if st.button("Check answer", key="farmer_check"):
            status, data = request("GET", f"/farmer/cases/{cid}", headers={"X-Case-Access-Token": access_token.strip()})
            if status == 200:
                st.info(STATES.get(data['status'], 'Your case is being reviewed.'))
                if data.get('delivery_status'):
                    st.caption('Delivery: ' + data['delivery_status'].replace('_', ' '))
                if data.get('answer'):
                    st.success(data['answer'])
                    st.caption('Human approval verified by the service.')
            elif status == 404:
                st.error("Case not found or private access token incorrect. Check both and try again.")
            else:
                st.error("Unable to check the answer. Please try again shortly.")


def voice_screen():
    st.title("Voice note simulator")
    st.warning("Local simulator only · Not a live phone service")
    st.write("Upload a synthetic recording or type a message to exercise channel intake and consent. Audio transcription requires separately configured faster-whisper models; spoken replies require Piper and officer script approval.")
    st.caption("Unavailable speech processing is flagged for officer listening; a successful upload does not prove transcription. Local language recognition and Kenyan guidance have not been validated.")
    sender = st.text_input("Simulated sender", "sim:farmer-1", key="voice_sender")
    clip = st.file_uploader("Voice note", type=["wav", "ogg", "mp3", "m4a"], key="voice_clip")
    typed = st.text_input("Or type a question", key="voice_text")
    if st.button("Send to AgriReach", key="voice_send"):
        if not sender.startswith('sim:'):
            st.error("Use a synthetic sender beginning with sim:.")
        elif not clip and not typed.strip():
            st.warning("Upload a recording or type a message first.")
        else:
            with st.spinner("Processing simulator intake…"):
                status, data = request("POST", "/channels/simulator/inbound", data={"sender": sender, "text": typed},
                    files={"audio": (clip.name, clip.getvalue())} if clip else None)
            if status == 200:
                st.info('Simulator state: ' + data.get('status', 'received').replace('_', ' '))
                if data.get('case_id'):
                    st.caption(f"Case {data['case_id']} created for officer review.")
            else:
                show_result(status, data)
    if st.button("Show messages", key="voice_messages"):
        status, data = request("GET", "/channels/simulator/outbox", params={"sender": sender})
        if status == 200:
            if not data:
                st.info("No simulator messages yet.")
            for message in data:
                st.info(message['text'])
        else:
            show_result(status, data)


def main():
    st.set_page_config(page_title="AgriReach · Reviewed agricultural advice", page_icon="🌱", layout="wide")
    st.markdown("""<style>
    .stApp { background: #f6f8f2; color: #173b2c; }
    [data-testid="stSidebar"] { background: #e8efdf; }
    .block-container { max-width: 1180px; padding-top: 4.5rem; }
    [data-testid="stCaptionContainer"] { opacity: 1 !important; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color: #4c6255 !important; }
    h1,h2,h3 { color: #173b2c; letter-spacing: -.025em; }
    .stButton>button, .stFormSubmitButton>button { border-radius: 8px; border-color: #507447; }
    @media(max-width:640px) { .block-container { padding: 4.5rem 1rem 1rem; } }
    </style>""", unsafe_allow_html=True)
    with st.sidebar:
        st.title("🌱 AgriReach")
        st.caption("SOURCE EVIDENCE · HUMAN REVIEW")
    status, health = request("GET", "/health")
    if status != 200:
        st.warning("The service is unavailable. Try again shortly.")
    elif health.get('draft_mode') == 'stub':
        st.caption("OFFLINE DEMONSTRATION · No language model inference · Human approval required")
    else:
        st.caption("MODEL DRAFTING · Human approval required before release")
    page = st.navigation([
        st.Page(farmer_screen, title="Farmer", url_path="farmer", default=True),
        st.Page(officer_screen, title="Extension officer", url_path="officer"),
        st.Page(voice_screen, title="Voice simulator", url_path="voice"),
    ])
    page.run()


if __name__ == "__main__":
    main()
