"""Run 9 mini driver: one F1 case on the model server (:18080), one on the no-model server (:18083); reads the
farmer_text_proposal audit entry, approves both with the proposed text, compares phone/farmer view/record."""
import json, sys, time, httpx
WH = "evalwebhooktoken-0123456789abcdef"
F1Q = "Adaklu maize farmer planted late Feb, saw worms mid-March, sprayed the recommended chemicals with no effect. What next?"
c = httpx.Client(timeout=120); out = open("/tmp/apprun9/results.jsonl", "w")
for name, base, tokf, phone in [("F1-model", "http://127.0.0.1:18080", "main", "+233240000091"),
                                ("F1-nomodel", "http://127.0.0.1:18083", "nokey", "+233240000092")]:
    H = {"Authorization": "Bearer " + open(f"/tmp/apprun9/{tokf}/token").read().strip()}
    c.post(f"{base}/channels/sms/inbound/{WH}", data={"from": phone, "text": F1Q, "id": f"AT-{name}", "to": "12345"})
    cid = None
    for _ in range(90):
        time.sleep(2)
        for x in c.get(f"{base}/officer/cases", headers=H).json():
            if x.get("status") == "pending_review":
                lg = c.get(f"{base}/officer/cases/{x['id']}", headers=H).json()["log"]
                if any(l["tool"] == "inbound_message" for l in lg): cid = x["id"]
        if cid: break
    det = c.get(f"{base}/officer/cases/{cid}", headers=H).json()
    prop_entries = [l for l in det["log"] if l["tool"] == "farmer_text_proposal"]
    text = (det.get("farmer_draft") or {}).get("text") or ""
    rec = {"case": name, "case_id": cid, "draft_mode": det.get("draft_mode"), "draft_head": (det.get("draft") or "")[:90],
           "proposal_entries": [{"args": l.get("args"), "summary": l.get("result_summary")} for l in prop_entries],
           "sms_mode": (det.get("farmer_draft") or {}).get("mode"), "proposed": text}
    r = c.post(f"{base}/officer/cases/{cid}/decision", headers=H,
               json={"decision": "approve", "edited_text": det.get("draft"), "farmer_text": text, "confirmed": True})
    time.sleep(1)
    sent = [json.loads(l) for l in open("/tmp/apprun9/sent.jsonl")]
    phone_last = [m["message"] for m in sent if m["to"] == phone][-1]
    fv = c.get(f"{base}/farmer/cases/{cid}").json().get("answer") or ""
    record = c.get(f"{base}/officer/cases/{cid}", headers=H).json().get("farmer_text") or ""
    rec |= {"approve_http": r.status_code, "warnings": r.json().get("warnings"), "delivery": r.json().get("delivery"),
            "byte_identical": bool(text) and phone_last.encode() == fv.encode() == record.encode() == text.encode()}
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
    print(json.dumps(rec, ensure_ascii=False, indent=1)[:3000], flush=True)
