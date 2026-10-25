"""Run 6 approval-path driver against the real HTTP API (throwaway server on :18080, mock Africa's Talking on :18081,
simulator-off server on :18082). Writes one JSON record per case to results.jsonl."""
import json, re, sys, time
import httpx
sys.path.insert(0, "/workspace/agrireach/eval-live/src")
from agrireach.channels.sms import measure
from agrireach.farmer_reply import SAFETY_RE
B, OFF, WH = "http://127.0.0.1:18080", "http://127.0.0.1:18082", "evalwebhooktoken-0123456789abcdef"
TOK = open("/tmp/apprun6/main/token").read().strip()
H = {"Authorization": f"Bearer {TOK}"}
c = httpx.Client(timeout=120)
def sent(to): return [json.loads(l) for l in open("/tmp/apprun6/sent.jsonl")] if to is None else [m for m in (json.loads(l) for l in open("/tmp/apprun6/sent.jsonl")) if m["to"] == to]
def sents(t): return [s for s in re.split(r"(?<=[.!?])\s+", t.strip()) if s]
CASES = [
    ("F1-a", "+233240000001", "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?", "approve"),
    ("F1-b", "+233240000002", "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?", "edit_delete_safety"),
    ("S-Kintampo", "+233240000003", "Fall armyworm is eating my maize in Kintampo. What pesticide should I spray?", "approve"),
    ("EJ", "+233240000004", "When should I plant maize in Ejura?", "approve"),
    ("F5", "+233240000005", "Subsidised fertiliser arrived when the maize is knee-high, about two months after planting. Is it still worth applying?", "approve"),
    ("F9", "+233240000006", "What is the cocoa producer price this season?", "gate_then_approve"),
    ("B1", "+233240000007", "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?", "b1_replay"),
    ("F1-c", "+233240000009", "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?", "ui_delete_safety"),
    ("TWI", "+233240000008", "Mmoa redi me aburo wɔ Kintampo. Aduro bɛn na memfa apete?", "twi_officer_text"),
]
B1_DRAFT = open("/tmp/apprun6/b1f1_draft.txt").read()
# Test text for the Unicode limit (written for this eval, not checked by a Twi speaker or an agronomist).
TWI_SHORT = "Kɔ hu wo mpɔtam hɔ AEA na ɔnkyerɛ wo aduro a ɛfata ma fall armyworm. Hwɛ w'afuo mu dapɛn biara."
def twi_len(n):
    base = "Hwɛ w'afuo mu dapɛn biara. "
    t = (base * (n // len(base) + 1))[:n]
    return t
only = sys.argv[1:]
out = open("/tmp/apprun6/results.jsonl", "a")
for name, phone, q, mode in CASES:
    if only and name not in only: continue
    rec = {"case": name, "phone": phone, "q": q, "mode": mode}; t0 = time.time()
    n0 = len(sent(phone)) if open("/tmp/apprun6/sent.jsonl", "a") else 0
    r = c.post(f"{B}/channels/sms/inbound/{WH}", data={"from": phone, "text": q, "id": f"ATin-{name}", "to": "12345"})
    rec["inbound_http"] = r.status_code
    cid = None
    for _ in range(150):
        time.sleep(2)
        lst = c.get(f"{B}/officer/cases", headers=H).json()
        items = lst if isinstance(lst, list) else lst.get("cases", lst.get("items", []))
        m = [x for x in items if x.get("question") == q and x["id"] not in [json.loads(l).get("case_id") for l in open("/tmp/apprun6/results.jsonl")]]
        if m and m[0].get("status") == "pending_review":
            lg = c.get(f"{B}/officer/cases/{m[0]['id']}", headers=H).json().get("log", [])
            if any(l.get("tool") == "inbound_message" for l in lg):  # contact saved and ack sent: inbound finished
                cid = m[0]["id"]; break
    rec["case_id"], rec["agent_secs"] = cid, round(time.time() - t0, 1)
    rec["pre_sent"] = [x["message"] for x in sent(phone)]
    if cid is None:
        rec["error"] = "no case appeared"; out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush(); continue
    det = c.get(f"{B}/officer/cases/{cid}", headers=H).json()
    queue = c.get(f"{B}/officer/queue", headers=H).json()
    qitem = [x for x in (queue if isinstance(queue, list) else queue.get("cases", [])) if x.get("id") == cid]
    fd = det.get("farmer_draft") or {}
    prop = fd.get("text") or ""
    m = measure(prop)
    rec |= {"status": det["status"], "priority": det.get("priority"), "draft_mode": det.get("draft_mode"),
            "draft": det.get("draft"), "sources": det.get("sources"), "urgent_reasons": det.get("urgent_reasons"),
            "proposed_sms": prop, "sms_mode": fd.get("mode"), "sms_problems": fd.get("problems"), "sms_limit": fd.get("sms_limit"),
            "zone_caveat": (fd.get("zone_caveat") or {}).get("sentence"),
            "queue_has_case": bool(qitem), "queue_sms": ((qitem[0].get("farmer_draft") or {}).get("text") if qitem else None),
            "chars": len(prop), "encoding": m.encoding, "units": m.units, "parts": m.segments,
            "ends_at_sentence": bool(re.search(r"[.!?]\)?$", prop.strip())) if prop else None,
            "safety_sentences": [s for s in sents(prop) if SAFETY_RE.search(s)],
            "farmer_view_before": c.get(f"{B}/farmer/cases/{cid}").json()}
    if mode == "gate_then_approve":
        g = {}
        g["get_no_token"] = c.get(f"{B}/officer/cases/{cid}").status_code
        g["get_bad_token"] = c.get(f"{B}/officer/cases/{cid}", headers={"Authorization": "Bearer not-a-real-token"}).status_code
        g["decide_no_token"] = c.post(f"{B}/officer/cases/{cid}/decision", json={"decision": "approve", "farmer_text": prop, "confirmed": True}).status_code
        g["decide_bad_token"] = c.post(f"{B}/officer/cases/{cid}/decision", headers={"Authorization": "Bearer nope"}, json={"decision": "approve", "farmer_text": prop, "confirmed": True}).status_code
        r = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json={"decision": "approve", "farmer_text": prop, "confirmed": False})
        g["unconfirmed"] = (r.status_code, r.json().get("detail"))
        long = ("Plant maize after three good rains within the planting window. " * 11).strip()
        r = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json={"decision": "approve", "farmer_text": long, "confirmed": True})
        g["overlength_gsm"] = (len(long), r.status_code, r.json().get("detail"))
        g["sms_check_ucs2"] = c.post(f"{B}/officer/cases/{cid}/sms-check", headers=H, json={"farmer_text": "Mɛ " * 100}).json()
        g["sms_check_gsm"] = c.post(f"{B}/officer/cases/{cid}/sms-check", headers=H, json={"farmer_text": "a" * 612}).json()
        g["sms_check_gsm_613"] = c.post(f"{B}/officer/cases/{cid}/sms-check", headers=H, json={"farmer_text": "a" * 613}).json()
        g["sim_outbox_when_off"] = c.get(f"{OFF}/channels/simulator/outbox").status_code
        g["sim_inbound_when_off"] = c.post(f"{OFF}/channels/simulator/inbound", data={"sender": "sim:farmer-1", "text": "hi"}).status_code
        g["sim_outbox_when_on"] = c.get(f"{B}/channels/simulator/outbox").status_code
        g["after_failed_attempts_status"] = c.get(f"{B}/officer/cases/{cid}", headers=H).json()["status"]
        rec["gate"] = g
    edited = None
    if mode == "b1_replay":
        r = c.post(f"{B}/officer/cases/{cid}/farmer-draft", headers=H, json={"officer_text": B1_DRAFT})
        fd1 = r.json(); m1 = measure(fd1.get("text") or "")
        rec["b1"] = {"http": r.status_code, "text": fd1.get("text"), "mode": fd1.get("mode"), "problems": fd1.get("problems"),
                     "chars": len(fd1.get("text") or ""), "encoding": m1.encoding, "units": m1.units, "parts": m1.segments,
                     "sentences": sents(fd1.get("text") or "")}
        uni = B1_DRAFT.replace("stunted growth [", "stunted growth in Kɔforidua [")
        r = c.post(f"{B}/officer/cases/{cid}/farmer-draft", headers=H, json={"officer_text": uni})
        fd2 = r.json(); m2 = measure(fd2.get("text") or "")
        rec["b1_unicode_probe"] = {"http": r.status_code, "text": fd2.get("text"), "mode": fd2.get("mode"), "problems": fd2.get("problems"),
                                   "chars": len(fd2.get("text") or ""), "encoding": m2.encoding, "units": m2.units, "parts": m2.segments}
        prop = fd1.get("text") or ""; edited = B1_DRAFT
    if mode == "twi_officer_text":
        t268, t269 = twi_len(268), twi_len(269)
        tw = {"proposal_empty": not prop, "needs_officer_text": fd.get("needs_officer_text"), "problems": fd.get("problems"),
              "measure_268": [measure(t268).encoding, measure(t268).units, measure(t268).segments],
              "sms_check_268": c.post(f"{B}/officer/cases/{cid}/sms-check", headers=H, json={"farmer_text": t268}).json(),
              "sms_check_269": c.post(f"{B}/officer/cases/{cid}/sms-check", headers=H, json={"farmer_text": t269}).json()}
        r = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json={"decision": "edit_approve", "edited_text": t269, "farmer_text": t269, "confirmed": True})
        tw["approve_269"] = (r.status_code, r.json().get("detail"))
        rec["twi"] = tw
        prop = TWI_SHORT; edited = TWI_SHORT
    approved = prop
    if mode == "edit_delete_safety":
        approved = " ".join(s for s in sents(prop) if not SAFETY_RE.search(s))
        body = {"decision": "edit_approve", "edited_text": approved, "farmer_text": approved, "confirmed": True}
    elif mode == "ui_delete_safety":
        # What the officer UI (ui.py) sends: edited_text is the officer draft box (unchanged here), farmer_text is the
        # farmer-text box, from which the officer deleted the pesticide sentence(s); decision stays 'approve'.
        approved = " ".join(s for s in sents(prop) if not SAFETY_RE.search(s))
        body = {"decision": "approve", "edited_text": det.get("draft"), "farmer_text": approved, "confirmed": True}
    elif edited is not None:
        body = {"decision": "edit_approve", "edited_text": edited, "farmer_text": approved, "confirmed": True}
    else:
        body = {"decision": "approve", "farmer_text": approved, "confirmed": True}
    rec["approved_text_sent_to_api"] = approved
    if not approved.strip():
        rec["approval"] = "skipped: empty proposal"
    else:
        r = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json=body)
        aj = r.json()
        rec |= {"approve_http": r.status_code, "approve_warnings": aj.get("warnings"), "delivery": aj.get("delivery"),
                "status_after": aj.get("status")}
        if mode == "gate_then_approve":
            r2 = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json={"decision": "reject", "note": "second"})
            r3 = c.post(f"{B}/officer/cases/{cid}/decision", headers=H, json=body)
            rec["gate"]["second_decision_reject"] = (r2.status_code, r2.json().get("detail"))
            rec["gate"]["second_decision_approve"] = (r3.status_code, r3.json().get("detail"))
        time.sleep(1)
        phone_msgs = [x["message"] for x in sent(phone)]
        fv = c.get(f"{B}/farmer/cases/{cid}").json()
        det2 = c.get(f"{B}/officer/cases/{cid}", headers=H).json()
        last = phone_msgs[-1] if phone_msgs else None
        rec |= {"phone_msgs": phone_msgs, "farmer_view_after": fv, "case_farmer_text": det2.get("farmer_text"),
                "byte_identical": last is not None and last.encode() == (fv.get("answer") or "").encode() == (det2.get("farmer_text") or "").encode() == approved.encode(),
                "approved_measure": [measure(approved).encoding, measure(approved).units, measure(approved).segments], "approved_has_safety": bool(SAFETY_RE.search(det2.get("farmer_text") or "")),
                "log": [{"tool": l.get("tool"), "ok": l.get("ok"), "actor": l.get("actor"), "args": l.get("args"), "summary": (l.get("result_summary") or "")[:1500]} for l in det2.get("log", [])]}
    rec["secs"] = round(time.time() - t0, 1)
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
    print(name, cid, rec.get("status"), rec.get("approve_http"), rec.get("byte_identical"), rec["secs"], flush=True)
