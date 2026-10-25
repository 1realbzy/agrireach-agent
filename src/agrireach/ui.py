"""Minimal Streamlit UI: farmer ask + officer review queue. Talks to the FastAPI backend."""
import os

import httpx
import streamlit as st

API = os.getenv("AGRIREACH_API", "http://127.0.0.1:8000")
st.set_page_config(page_title="AgriReach", layout="wide")
st.title("AgriReach - soybean extension (MVP)")
mode = httpx.get(f"{API}/health", timeout=10).json()["draft_mode"]
if mode == "stub":
    st.warning("OFFLINE STUB MODE: no language model configured. Drafts are assembled from retrieved passages.")

farmer, voice, officer = st.tabs(["Farmer", "Voice note (simulator)", "Extension officer"])
with farmer:
    q = st.text_area("Your question", "When should I plant soybean in Tamale?")
    if st.button("Send"):
        r = httpx.post(f"{API}/ask", json={"question": q}, timeout=180).json()
        st.info(f"Case {r['case_id']}: {r['message']}")
    cid = st.number_input("Check case number", min_value=1, step=1)
    if st.button("Check answer"):
        r = httpx.get(f"{API}/farmer/cases/{int(cid)}", timeout=10).json()
        st.write(r.get("answer") or r.get("message"))
        if r.get("approved_by"):
            st.caption(f"Approved by {r['approved_by']} at {r['approved_at']} UTC")

with voice:
    st.caption("Simulates a farmer's phone on this computer. Nothing is sent to WhatsApp or any outside service. "
               "Speech-to-text runs locally and has only been tested on synthetic English speech.")
    sender = st.text_input("Simulated sender id", "sim:farmer-1", help="Must look like sim:name. Never a real number.")
    clip = st.file_uploader("Voice note", type=["wav", "ogg", "mp3", "m4a"])
    typed = st.text_input("Or type a question (optional)", "")
    if st.button("Send to AgriReach"):
        files = {"audio": (clip.name, clip.getvalue())} if clip else None
        r = httpx.post(f"{API}/channels/simulator/inbound", data={"sender": sender, "text": typed}, files=files,
                       timeout=300)
        st.write(r.json())
    if st.button("Show messages sent to this phone"):
        for m in httpx.get(f"{API}/channels/simulator/outbox", params={"sender": sender}, timeout=10).json():
            st.info(f"{m['ts']} UTC\n\n{m['text']}")
            if m.get("audio"):
                st.audio(m["audio"])

with officer:
    token = st.text_input("Officer sign-in token (from scripts/add_officer.py)", type="password")
    H = {"Authorization": f"Bearer {token}"}
    q = httpx.get(f"{API}/officer/queue", headers=H, timeout=10)
    if q.status_code == 401:
        st.info("Sign in with your officer token to see the review queue.")
        st.stop()
    for c in q.json():
        tag = "URGENT" if c["priority"] == "urgent" else "routine"
        if c["status"] == "not_delivered":
            tag = "NOT DELIVERED"
        with st.expander(f"[{tag}] Case {c['id']}: {c['question']}"):
            if c["status"] == "not_delivered":
                st.error(f"Approved by {c['officer']} but not delivered: {c.get('delivery_problem')}. Edit the "
                         "farmer text and approve again, or retry sending the same text.")
                if st.button("Retry sending the approved text", key=f"retry{c['id']}"):
                    st.write(httpx.post(f"{API}/cases/{c['id']}/release", headers=H, timeout=60).json())
            for reason in c["urgent_reasons"]:
                st.error(reason)
            v = httpx.get(f"{API}/officer/cases/{c['id']}/voice", headers=H, timeout=10)
            if v.status_code == 200:
                v = v.json()
                st.caption(f"Arrived via {v['channel']} from {v['sender']}")
                if v["has_audio"]:
                    st.audio(httpx.get(f"{API}/officer/cases/{c['id']}/audio", headers=H, timeout=30).content)
                    st.write(f"Machine transcript (check against the audio): {v['transcript']!r}")
            text = st.text_area("Officer draft with citations (edit before approving if needed)", c["draft"],
                                key=f"d{c['id']}", height=220)
            st.caption("Sources: " + ", ".join(c["sources"]))
            fd = c.get("farmer_draft") or {}
            if st.button("Re-propose farmer text from the officer draft above", key=f"rp{c['id']}"):
                fd = httpx.post(f"{API}/officer/cases/{c['id']}/farmer-draft", json={"officer_text": text},
                                headers=H, timeout=60).json()
                st.session_state[f"f{c['id']}"] = fd.get("text", "")
            for p in fd.get("problems", []):
                st.warning(f"Farmer text: {p}")
            farmer_txt = st.text_area("Farmer text: exactly what the farmer will receive (approve covers this text)",
                                      (c["status"] == "not_delivered" and c.get("farmer_text")) or fd.get("text", ""),
                                      key=f"f{c['id']}", height=140)
            st.caption(f"{len(farmer_txt)} characters (aim for under 600)")
            if fd.get("sms_limit"):  # SMS case: show the limit, and check the text as it stands now
                st.caption(fd["sms_limit"])
                chk = httpx.post(f"{API}/officer/cases/{c['id']}/sms-check", json={"farmer_text": farmer_txt},
                                 headers=H, timeout=10).json()
                if chk.get("prompt"):
                    st.warning(f"Farmer text: {chk['prompt']}")
                else:
                    st.caption(f"Fits: {chk.get('parts')} of {chk.get('limit')} SMS parts ({chk.get('encoding')})")
            confirmed = st.checkbox("I checked every advice line in the farmer text against the cited sources",
                                    key=f"ok{c['id']}")
            cols = st.columns(3)
            for col, (label, dec) in zip(cols, [("Approve & release", "approve"), ("Reject", "reject"),
                                                ("Request info", "request_info")]):
                if col.button(label, key=f"{dec}{c['id']}"):
                    if dec == "approve" and text != c["draft"]:
                        dec = "edit_approve"
                    r = httpx.post(f"{API}/officer/cases/{c['id']}/decision", headers=H,
                                   json={"decision": dec, "edited_text": text, "farmer_text": farmer_txt,
                                         "confirmed": confirmed}, timeout=60)
                    st.write(r.json())
            if st.checkbox("Show tool-call log", key=f"l{c['id']}"):
                st.dataframe(httpx.get(f"{API}/officer/cases/{c['id']}", headers=H, timeout=10).json()["log"])
