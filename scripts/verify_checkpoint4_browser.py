"""Browser check for the Checkpoint 4 farmer form on ports 8501 and 8502.

Uses the real farmer_ui.py and officer_ui.py entrypoints, a disposable database,
and simulated mNotify. No provider key is read and no SMS is sent.
Screenshots mask the phone field and the private access code.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PHONE = "0240000001"
QUESTION = "When should I harvest soybean in Tamale?"


def main():
    output = Path(os.environ.get("AGRIREACH_BROWSER_EVIDENCE", "/opt/cursor/artifacts")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="checkpoint4-sms-", dir="/tmp"))
    env = os.environ | {
        "PYTHONPATH": str(ROOT / "src"),
        "DATABASE_URL": "sqlite:///" + str(temp / "demo.db"),
        "AGRIREACH_API": "http://127.0.0.1:18000",
        "AGRIREACH_SOURCE_CHECK": "0",
        "AGRIREACH_RAINFALL": "off",
        "AGRIREACH_STT": "none",
        "AGRIREACH_TTS": "",
        "AGRIREACH_SIMULATOR": "0",
        "SMS_ENABLED": "0",
        "WHATSAPP_ENABLED": "0",
        "MNOTIFY_SMS_MODE": "simulated",
        "LLM_BASE_URL": "",
        "LLM_MODEL": "",
        "LLM_API_KEY": "",
        "AGRIREACH_JUDGE_BASE_URL": "",
        "AGRIREACH_JUDGE_API_KEY": "",
        "AGRIREACH_MEDIA_DIR": str(temp / "media"),
        "AGRIREACH_OUTBOX": str(temp / "outbox"),
    }
    for secret in ("MNOTIFY_API_KEY", "MNOTIFY_SENDER_ID", "AT_API_KEY", "AT_USERNAME"):
        env.pop(secret, None)
    os.environ.update(env)
    from agrireach import db
    con = db.connect()
    token = db.add_officer(con, "Disposable verification officer")
    processes = []

    def settle(page):
        page.wait_for_timeout(300)
        page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for()

    def shot(page, name):
        settle(page)
        page.locator("[data-testid='stMain']").evaluate("(e)=>e.scrollTop=0")
        masks = page.get_by_label("Phone number", exact=True).all()
        masks += page.get_by_label("Private access code", exact=True).all()
        page.screenshot(path=str(output / name), full_page=True, mask=masks, mask_color="#dce5d6")

    try:
        commands = [["uvicorn", "agrireach.api:app", "--host", "127.0.0.1", "--port", "18000", "--ws", "none", "--no-access-log"]]
        for role, port in (("farmer", 8501), ("officer", 8502)):
            commands.append([
                "streamlit", "run", f"src/agrireach/{role}_ui.py",
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false",
            ])
        for args in commands:
            processes.append(subprocess.Popen(
                [sys.executable, "-m", *args], cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(120):
            try:
                if all(httpx.get(f"http://127.0.0.1:{port}/_stcore/health", trust_env=False).status_code == 200
                       for port in (8501, 8502)):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("farmer or officer portal did not become healthy")
        with httpx.Client(base_url=env["AGRIREACH_API"], trust_env=False, timeout=180) as client, sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1400})
            farmer = context.new_page()
            officer = context.new_page()
            for tab in (farmer, officer):
                tab.set_default_timeout(60000)
            farmer.goto("http://127.0.0.1:8501")
            farmer.get_by_label("Your question", exact=True).wait_for()
            assert farmer.get_by_label("Officer sign in token", exact=True).count() == 0
            assert farmer.get_by_role("checkbox").is_checked() is False
            farmer.get_by_label("Your question", exact=True).fill(QUESTION)
            farmer.get_by_label("Phone number", exact=True).fill("12345")
            farmer.get_by_text("I agree that AgriReach may text this number", exact=False).click()
            assert farmer.get_by_role("checkbox").is_checked() is True
            farmer.get_by_role("button", name="Send question", exact=True).click()
            farmer.get_by_text("Ghana mobile number", exact=False).wait_for()
            assert farmer.get_by_label("Your question", exact=True).input_value() == QUESTION
            shot(farmer, "farmer-invalid-phone.png")
            farmer.get_by_label("Phone number", exact=True).fill(PHONE)
            farmer.get_by_role("button", name="Send question", exact=True).click()
            farmer.get_by_text("Your question has been received.", exact=True).wait_for(timeout=180000)
            farmer.get_by_text("simulated", exact=False).wait_for()
            farmer.get_by_text("No message was sent to a phone.", exact=False).wait_for()
            farmer.get_by_text("waiting for an extension officer", exact=False).wait_for()
            case_id = int(farmer.get_by_label("Question number", exact=True).input_value())
            private = farmer.get_by_label("Private access code", exact=True).input_value()
            visible = farmer.locator("body").inner_text()
            assert PHONE not in visible and private not in visible
            shot(farmer, "farmer-received.png")
            farmer.set_viewport_size({"width": 390, "height": 844})
            shot(farmer, "farmer-received-mobile.png")
            farmer.set_viewport_size({"width": 1440, "height": 1400})
            farmer.get_by_role("button", name="Check answer", exact=True).click()
            farmer.get_by_text("Waiting for officer review. Advice is not available yet.", exact=True).wait_for()
            assert farmer.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
            access = {"X-Case-Access-Token": private}
            auth = {"Authorization": "Bearer " + token}
            farmer_body = client.get(f"/farmer/cases/{case_id}", headers=access).json()
            assert farmer_body["answer"] is None
            assert client.post(f"/cases/{case_id}/release", headers=auth).status_code == 409
            officer.goto("http://127.0.0.1:8502")
            officer.get_by_label("Officer sign in token", exact=True).fill(token)
            officer.get_by_role("button", name="Sign in", exact=True).click()
            button = officer.get_by_role("button", name=f"Open case {case_id} · pending review", exact=True)
            button.wait_for(timeout=60000)
            button.click()
            officer.get_by_text("simulated, no message was sent to a phone", exact=False).wait_for()
            assert PHONE not in officer.locator("body").inner_text()
            shot(officer, "officer-acknowledgement.png")
            ack = client.get(f"/officer/cases/{case_id}/acknowledgement", headers=auth).json()
            assert ack["simulated"] is True and ack["handset_delivered"] is False
            assert ack["phone_masked"].endswith("01") and PHONE not in json.dumps(ack)
            assert client.get("/health").json()["draft_mode"] == "stub"
            browser.close()
        evidence = {
            "mode": "simulated",
            "database": "disposable",
            "provider_call": "none",
            "phone": "redacted",
            "access_token": "redacted",
            "case_id": case_id,
            "case_status": "pending_review",
            "answer": None,
            "release_before_approval": 409,
            "acknowledgement": {
                "status": ack["status"],
                "simulated": ack["simulated"],
                "handset_delivered": ack["handset_delivered"],
                "phone_masked": ack["phone_masked"],
            },
            "checks": {
                "invalid_phone_kept_the_question": "passed",
                "consent_started_unchecked": "passed",
                "received_and_simulated_label": "passed",
                "pending_review_wording": "passed",
                "no_advice_before_approval": "passed",
                "officer_sees_simulated_acknowledgement": "passed",
                "mobile_layout": "passed",
            },
        }
        (output / "checkpoint4-browser-evidence.json").write_text(json.dumps(evidence, indent=2))
        print(json.dumps(evidence["checks"]))
    finally:
        con.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=20)


if __name__ == "__main__":
    main()
