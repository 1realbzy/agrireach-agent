"""Mock Africa's Talking messaging endpoint: records each POST form to sent.jsonl, answers 'Sent' (101)."""
import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
OUT = sys.argv[2]
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("content-length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
        with open(OUT, "a") as f:
            f.write(json.dumps({"path": self.path, "to": form.get("to"), "message": form.get("message")}, ensure_ascii=False) + "\n")
        body = json.dumps({"SMSMessageData": {"Message": "Sent to 1/1", "Recipients": [
            {"statusCode": 101, "number": form.get("to"), "status": "Success", "cost": "KES 0.8000", "messageId": "ATXid_mock"}]}}).encode()
        self.send_response(201); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
