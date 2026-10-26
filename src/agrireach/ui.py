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


def show_result(status, data):
    level, message = feedback(status, data)
    getattr(st, level)(message)
    detail = data.get("detail", {})
    if isinstance(detail, dict):
        show_findings(detail.get("findings", []))


LABELS = {"S1": "Required source safeguard", "S2": "Consultation or protection instruction",
          "S3": "Unsourced material or dose", "S4": "Burning without a source", "LANGUAGE": "Language needs additional review",
          "SOURCE_SUPPORT": "Source support needs review", "SOURCE_FIGURES": "Number not in the cited source"}


def show_findings(findings):
    """Show each hold with its line and the plain reason, so the officer knows what to edit."""
    for finding in findings:
        st.caption(LABELS.get(finding["rule_id"], "Additional review required"))
        if finding.get("sentence"):
            st.text(finding["sentence"])
        if finding.get("reason"):
            st.text("Why: " + finding["reason"])
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
        show_findings(data.get("findings", []))


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
    with st.expander(f"Case {cid}: {case['question']}"):
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
            st.text("Machine transcript: " + (inbound.get("transcript") or ""))
        # The offline label is for logs and tests; officers see only the advice.
        shown = "\n".join(l for l in case["draft"].splitlines() if not l.startswith(llm.STUB_LABEL))
        # Officers see numbered citations; edits are mapped back to the source IDs before saving.
        shown, cites = number_citations(shown)
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
            show_result(status, data)
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
                show_findings(data.get("findings", []))
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


def officer_screen():
    token = st.text_input("Officer sign in token", type="password")
    if not token.strip():
        st.info("Sign in with your officer token to see the review queue.")
        return
    headers = auth_headers(token)
    if st.button("Reload cases"):
        st.rerun()
    status, queue = request("GET", "/officer/queue", headers=headers)
    if status != 200:
        show_result(status, queue)
        return
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
    st.title("AgriReach")
    status, health = request("GET", "/health")
    if status != 200:
        st.warning("The service is unavailable. Try again shortly.")
    farmer, voice, officer = st.tabs(["Farmer", "Voice note simulator", "Extension officer"])
    with farmer:
        question = st.text_area("Your question", "When should I plant soybean in Tamale?")
        if st.button("Send"):
            status, data = request("POST", "/ask", json={"question": question})
            if status == 200:
                st.info(f"Case {data['case_id']}: your question is waiting for review.")
            else:
                show_result(status, data)
        cid = st.number_input("Check case number", min_value=1, step=1)
        if st.button("Check answer"):
            status, data = request("GET", f"/farmer/cases/{cid}")
            if status == 200:
                st.info(data.get("answer") or "Your case is waiting for officer review or confirmed delivery.")
            else:
                show_result(status, data)
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
