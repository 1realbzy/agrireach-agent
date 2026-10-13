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

farmer, officer = st.tabs(["Farmer", "Extension officer"])
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

with officer:
    name = st.text_input("Officer name (required to decide)")
    for c in httpx.get(f"{API}/officer/queue", timeout=10).json():
        tag = "URGENT" if c["priority"] == "urgent" else "routine"
        with st.expander(f"[{tag}] Case {c['id']}: {c['question']}"):
            for reason in c["urgent_reasons"]:
                st.error(reason)
            text = st.text_area("Draft (edit before approving if needed)", c["draft"], key=f"d{c['id']}", height=220)
            st.caption("Sources: " + ", ".join(c["sources"]))
            cols = st.columns(3)
            for col, (label, dec) in zip(cols, [("Approve & release", "approve"), ("Reject", "reject"),
                                                ("Request info", "request_info")]):
                if col.button(label, key=f"{dec}{c['id']}"):
                    if dec == "approve" and text != c["draft"]:
                        dec = "edit_approve"
                    r = httpx.post(f"{API}/officer/cases/{c['id']}/decision",
                                   json={"officer": name, "decision": dec, "edited_text": text}, timeout=10)
                    st.write(r.json())
            if st.checkbox("Show tool-call log", key=f"l{c['id']}"):
                st.dataframe(httpx.get(f"{API}/officer/cases/{c['id']}", timeout=10).json()["log"])
