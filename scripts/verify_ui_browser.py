"""Opt-in Chromium acceptance against a local synthetic demo database.

Requires Playwright only in the developer environment. Start the API and Streamlit
with the same disposable DATABASE_URL before running. Never use production data.
Screenshots contain synthetic cases and a masked generated officer credential.
"""
import os
import json
import subprocess
import sys
import time
from pathlib import Path

from agrireach import db


def run_browser():
    from playwright.sync_api import sync_playwright
    if "round2-demo" not in os.environ.get("DATABASE_URL", ""):
        raise RuntimeError("Use a disposable round2-demo database")
    con = db.connect()
    token = db.add_officer(con, "Browser QA")
    def seed(name, text):
        cid = db.agent_upsert_case(con, status="pending_review", question=name, draft="Source supported draft",
            sources=["APNI-SARI-2023:harvest"])
        with con:
            con.execute("UPDATE cases SET farmer_draft=? WHERE id=?", (json.dumps({"text": text, "language": "en"}), cid))
        return cid
    good = seed("Browser approval", "Harvest when 9 out of 10 pods are mature.")
    bad = seed("Browser safety hold", "Put mancozeb on the pods when they are mature.")
    reject = seed("Browser rejection", "Harvest when 9 out of 10 pods are mature.")
    output = Path(os.environ.get("AGRIREACH_BROWSER_EVIDENCE", "docs/round2-browser"))
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.goto("http://127.0.0.1:8501")
        page.get_by_text("Sign in with your officer token to see the review queue.", exact=True).wait_for(state="attached")
        assert page.get_by_text("Illegal header value", exact=False).count() == 0
        page.screenshot(path=str(output / "signed-out.png"), full_page=True)
        page.get_by_role("tab", name="Extension officer").click()
        page.get_by_label("Officer sign in token").fill(token)
        page.get_by_label("Officer sign in token").press("Enter")
        page.get_by_text(f"Case {good}: Browser approval", exact=True).wait_for()
        def section(cid, title):
            label = page.get_by_text(f"Case {cid}: {title}", exact=True)
            label.click()
            return label.locator("xpath=ancestor::details")
        area = section(bad, "Browser safety hold")
        assert area.get_by_role("button", name="Approve and release", exact=True).is_disabled()
        area.get_by_text("Required for approval: I checked every advice line against the cited sources", exact=True).click()
        area.get_by_role("button", name="Approve and release", exact=True).click()
        area.get_by_text("Approval was blocked or held", exact=False).wait_for()
        area.get_by_text("Approval was blocked or held", exact=False).scroll_into_view_if_needed()
        assert db.get_case(con, bad)["status"] == "pending_review"
        page.screenshot(path=str(output / "safety-hold.png"), full_page=True)
        area = section(reject, "Browser rejection")
        area.get_by_label("Officer note or clarification request").fill("Please confirm the crop condition.")
        area.get_by_role("button", name="Request info", exact=True).click()
        area.get_by_text("Information requested.", exact=False).wait_for()
        area.get_by_text("Information requested.", exact=False).scroll_into_view_if_needed()
        assert db.get_case(con, reject)["officer_note"] == "Please confirm the crop condition."
        page.screenshot(path=str(output / "information-requested.png"), full_page=True)
        area = section(good, "Browser approval")
        area.get_by_text("Required for approval: I checked every advice line against the cited sources", exact=True).click()
        area.get_by_role("button", name="Approve and release", exact=True).click()
        area.get_by_text("Assessment unavailable.", exact=False).wait_for()
        area.get_by_text("Assessment unavailable.", exact=False).scroll_into_view_if_needed()
        area.get_by_role("button", name="Retry assessment", exact=True).click()
        area.get_by_text("Assessment unavailable.", exact=False).wait_for()
        page.screenshot(path=str(output / "assessment-retry.png"), full_page=True)
        from agrireach import knowledge
        area.get_by_label("Farmer text: exactly what will be sent").fill(knowledge.reference("APNI-SARI-2023:harvest")["text"])
        area.get_by_label("Farmer text: exactly what will be sent").press("Tab")
        area.get_by_role("button", name="Approve and release", exact=True).click()
        area.get_by_text("Advice approved and released", exact=False).wait_for()
        area.get_by_text("Advice approved and released", exact=False).scroll_into_view_if_needed()
        assert db.get_case(con, good)["status"] == "released"
        page.screenshot(path=str(output / "approved.png"), full_page=True)
        assert page.locator('[data-testid="stException"]').count() == 0
        browser.close()
    print("Chromium signed-out, required confirmation, safety hold, notes and approval checks passed")


if __name__ == "__main__":
    import httpx
    processes = []
    environment = os.environ | {"AGRIREACH_API": "http://127.0.0.1:8000", "AGRIREACH_SOURCE_CHECK": "0", "AGRIREACH_SIMULATOR": "1"}
    try:
        for args in (["uvicorn", "agrireach.api:app", "--host", "127.0.0.1", "--port", "8000"],
                     ["streamlit", "run", "src/agrireach/ui.py", "--server.address", "127.0.0.1", "--server.port", "8501", "--server.headless", "true"]):
            processes.append(subprocess.Popen([sys.executable, "-m", *args], env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(100):
            try:
                if httpx.get("http://127.0.0.1:8501/_stcore/health", trust_env=False).status_code == 200 and httpx.get("http://127.0.0.1:8000/health", trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        run_browser()
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=10)
