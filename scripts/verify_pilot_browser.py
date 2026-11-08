"""Disposable offline browser acceptance. Never reads pilot credentials or cases.

Requires Playwright and an installed Chrome browser. Run from the repository root.
Creates private temporary data under AGRIREACH_BROWSER_WORK and screenshots under
AGRIREACH_BROWSER_EVIDENCE. Tokens exist only in memory; no traces or HTML dumps.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
API = 'http://127.0.0.1:18000'
UI = 'http://127.0.0.1:18501'


def settle(page):
    # Streamlit commits text inputs on blur and then rerenders controls. Wait
    # before the next click so it is not sent to a control being replaced.
    page.wait_for_timeout(250)
    page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for()


def capture(page, path, mask=None):
    settle(page)
    page.locator('[data-testid="stMain"]').evaluate('(e)=>e.scrollTop=0')
    page.screenshot(path=str(path), full_page=True, mask=mask or [], mask_color='#dce5d6')


def walkthrough(con, token, output):
    from agrireach import db
    class Results(dict):
        def __setitem__(self, key, value):
            super().__setitem__(key, value)
            print(key + ': ' + value, flush=True)
    results = Results()
    client = httpx.Client(base_url=API, trust_env=False, timeout=180)
    auth = {'Authorization': 'Bearer ' + token}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel=os.getenv('AGRIREACH_BROWSER_CHANNEL', 'chrome'), headless=True)
        officer = browser.new_context(permissions=['clipboard-read', 'clipboard-write'], viewport={'width': 1440, 'height': 1400})
        farmer_context = browser.new_context(viewport={'width': 1280, 'height': 1250})
        page = officer.new_page()
        farmer = farmer_context.new_page()
        for tab in (page, farmer):
            tab.set_default_timeout(60000)
        page.goto(UI + '/officer')
        page.get_by_label('Officer sign in token', exact=True).fill('invalid')
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.get_by_text('Sign in with a valid officer token to continue.', exact=True).wait_for()
        results['invalid_officer_browser'] = 'passed'
        # Real browser clipboard API and native paste, no token in command line/log.
        page.evaluate('(v)=>navigator.clipboard.writeText(v)', '  ' + token + '  ')
        field = page.get_by_label('Officer sign in token', exact=True)
        field.click(); field.press('Control+a'); field.press('Control+v')
        if field.input_value().strip() != token:
            raise AssertionError('clipboard contents differed')
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.get_by_text('No cases waiting for review.', exact=False).wait_for()
        results['clipboard_whitespace_auth'] = 'passed'
        page.evaluate('()=>navigator.clipboard.writeText("")')
        capture(page, output/'officer-empty.png')
        farmer.goto(UI)
        farmer.get_by_label('Your question').fill('When should I harvest soybean in Tamale?')
        farmer.get_by_role('button', name='Send question', exact=True).click()
        farmer.get_by_text('created. Keep your private access token', exact=False).wait_for(timeout=180000)
        cid = int(farmer.get_by_label('Check case number', exact=True).input_value())
        private = farmer.get_by_label('Case access token', exact=True).input_value()
        assert private and private != token
        access = {'X-Case-Access-Token': private}
        farmer.get_by_role('button', name='Check answer', exact=True).click()
        farmer.get_by_text('Waiting for officer review. Advice is not available yet.', exact=True).wait_for()
        assert client.get(f'/farmer/cases/{cid}', headers=access).json()['answer'] is None
        assert client.post(f'/cases/{cid}/release', headers=auth).status_code >= 400
        capture(farmer, output/'farmer-pending.png', [farmer.get_by_label('Case access token', exact=True)])
        results['farmer_submission_private_pending'] = 'passed'
        # No refresh click: the already open officer page must discover the case.
        page.get_by_role('button', name=f'Open case {cid} · pending review', exact=True).wait_for(timeout=45000)
        results['automatic_queue'] = 'passed'
        page.get_by_role('button', name=f'Open case {cid} · pending review', exact=True).click()
        page.get_by_label('Officer draft with citations', exact=True).wait_for()
        page.get_by_text('Read source evidence', exact=True).click()
        from agrireach import knowledge
        source_case = client.get(f'/officer/cases/{cid}', headers=auth).json()
        assert 'APNI-SARI-2023:harvest' in source_case['sources']
        approved_text = knowledge.reference('APNI-SARI-2023:harvest')['text']
        source_text = knowledge.reference(source_case['sources'][0])['text']
        page.get_by_test_id('stText').get_by_text(source_text, exact=True).wait_for()
        capture(page, output/'officer-source-evidence.png')
        results['generated_draft_source_evidence_visible'] = 'passed'
        assert page.get_by_role('button', name='Approve and release', exact=True).is_disabled()
        text = page.get_by_label('Farmer text: exactly what will be sent', exact=True)
        text.fill('Spray pesticide twice every week.'); text.press('Tab')
        settle(page)
        page.get_by_text('Required for approval: I checked every advice line against the cited sources', exact=True).click()
        page.get_by_role('button', name='Approve and release', exact=True).click()
        page.get_by_text('Approval was blocked or held', exact=False).wait_for()
        assert client.get(f'/farmer/cases/{cid}', headers=access).json()['answer'] is None
        capture(page, output/'officer-safety-hold.png')
        results['browser_safety_hold_no_release'] = 'passed'
        # Navigate away and back: officer session persists; draft authorization
        # remains on API, not on possession of a farmer token.
        page.get_by_role('link', name='Farmer', exact=True).click()
        page.get_by_role('heading', name='Advice for your next step', exact=True).wait_for()
        page.get_by_role('link', name='Extension officer', exact=True).click()
        page.get_by_role('button', name='Sign out', exact=True).wait_for()
        results['navigation_session'] = 'passed'
        text = page.get_by_label('Farmer text: exactly what will be sent', exact=True)
        text.fill(approved_text); text.press('Tab')
        settle(page)
        confirmation = page.get_by_role('checkbox', name='Required for approval: I checked every advice line against the cited sources', exact=True)
        if not confirmation.is_checked():
            page.get_by_text('Required for approval: I checked every advice line against the cited sources', exact=True).click()
        capture(page, output/'officer-review.png')
        original = client.get(f'/officer/cases/{cid}', headers=auth).json()
        page.get_by_role('button', name='Approve and release', exact=True).click()
        page.get_by_text('Advice approved and released for the farmer to read.', exact=True).wait_for()
        assert client.get(f'/farmer/cases/{cid}', headers=access).json()['answer'] == approved_text
        # Retained revision cannot be reused; includes a browser rerun.
        page.get_by_role('button', name='Approve and release', exact=True).click()
        page.get_by_text('The action could not proceed with the current case', exact=False).wait_for()
        results['browser_revision_conflict'] = 'passed'
        farmer.get_by_role('button', name='Check answer', exact=True).click()
        farmer.get_by_text(approved_text, exact=True).wait_for()
        capture(farmer, output/'farmer-approved.png', [farmer.get_by_label('Case access token', exact=True)])
        results['browser_approval_and_retrieval'] = 'passed'
        for headers in ({}, {'Authorization': 'Bearer invalid'}, {'Authorization': 'Bearer ' + private}):
            assert client.get('/officer/queue', headers=headers).status_code == 401
            assert client.post(f'/officer/cases/{cid}/decision', headers=headers,
                json={'decision': 'approve', 'confirmed': True, 'expected_revision': original['revision'], 'farmer_text': approved_text}).status_code == 401
            assert client.post(f'/cases/{cid}/release', headers=headers).status_code == 401
        assert client.get(f'/farmer/cases/{cid}', headers={'X-Case-Access-Token': token}).status_code == 404
        farmer.get_by_label('Case access token', exact=True).fill('invalid')
        farmer.get_by_role('button', name='Check answer', exact=True).click()
        farmer.get_by_text('Case not found or private access token incorrect.', exact=False).wait_for()
        results['credential_separation_unauthorized_actions'] = 'passed'
        # Second farmer-created case, rejected in the actual UI.
        farmer.get_by_label('Your question').fill('How do I contact an extension officer about maize in Wa?')
        farmer.get_by_role('button', name='Send question', exact=True).click()
        farmer.get_by_text('created. Keep your private access token', exact=False).wait_for(timeout=180000)
        rejected = int(farmer.get_by_label('Check case number', exact=True).input_value())
        page.get_by_role('button', name=f'Open case {rejected} · pending review', exact=True).click()
        page.get_by_text(f'Case {rejected}: How do I contact an extension officer about maize in Wa?', exact=True).wait_for()
        settle(page)
        page.get_by_label('Officer note or clarification request', exact=True).fill('Synthetic rejection: please consult the local extension office.')
        page.get_by_label('Officer note or clarification request', exact=True).press('Tab')
        settle(page)
        page.get_by_text('Confirm: reject this case with the note above', exact=True).click()
        settle(page)
        assert page.get_by_role('checkbox', name='Confirm: reject this case with the note above', exact=True).is_checked()
        assert page.get_by_label('Officer note or clarification request', exact=True).input_value().startswith('Synthetic rejection:')
        page.get_by_role('button', name='Reject', exact=True).click()
        page.get_by_text('Case rejected. Your decision and note were recorded.', exact=False).wait_for()
        farmer.get_by_role('button', name='Check answer', exact=True).click()
        farmer.get_by_text('The officer rejected this advice. No advice was released.', exact=True).wait_for()
        assert not con.execute('SELECT 1 FROM approvals WHERE case_id=?', (rejected,)).fetchone()
        results['browser_rejection'] = 'passed'
        page.get_by_role('button', name='Sign out', exact=True).click()
        page.get_by_label('Officer sign in token', exact=True).wait_for()
        assert page.get_by_label('Officer draft with citations', exact=True).count() == 0
        results['signout_clears_review'] = 'passed'
        page.evaluate('(v)=>navigator.clipboard.writeText(v)', private)
        field = page.get_by_label('Officer sign in token', exact=True)
        field.click(); field.press('Control+v')
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.get_by_text('Sign in with a valid officer token to continue.', exact=True).wait_for()
        page.evaluate('()=>navigator.clipboard.writeText("")')
        results['farmer_token_officer_login_rejected'] = 'passed'
        # Actual file upload through simulator, with consent enabled and STT off.
        page.get_by_role('link', name='Voice simulator', exact=True).click()
        page.get_by_label('Simulated sender', exact=True).fill('sim:browser-audio')
        page.get_by_label('Simulated sender', exact=True).press('Tab')
        settle(page)
        page.locator('input[type="file"]').set_input_files(str(ROOT/'tests/fixtures/audio/en_plant_wa_piper.wav'))
        settle(page)
        page.get_by_role('button', name='Send to AgriReach', exact=True).click()
        page.get_by_text('Simulator state: awaiting consent', exact=True).wait_for()
        page.get_by_role('button', name='Show messages', exact=True).click()
        capture(page, output/'voice-simulator.png')
        # Consent via same service; the uploaded audio becomes an officer case.
        response = client.post('/channels/simulator/inbound', data={'sender': 'sim:browser-audio', 'text': 'YES'})
        assert response.status_code == 200
        audio_id = response.json()['case_id']
        voice = client.get(f'/officer/cases/{audio_id}/voice', headers=auth).json()
        assert voice['has_audio'] and not voice.get('transcript')
        assert client.get(f'/officer/cases/{audio_id}/audio', headers=auth).status_code == 200
        assert client.get(f'/officer/cases/{audio_id}/audio').status_code == 401
        results['audio_upload_consent_stt_off_review_access'] = 'passed'
        page.get_by_role('link', name='Extension officer', exact=True).click()
        page.evaluate('(v)=>navigator.clipboard.writeText(v)', token)
        field = page.get_by_label('Officer sign in token', exact=True)
        field.click(); field.press('Control+a'); field.press('Control+v')
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.evaluate('()=>navigator.clipboard.writeText("")')
        page.get_by_role('button', name=f'Open case {audio_id} · pending review', exact=True).click()
        page.get_by_text('No machine transcript is available.', exact=False).wait_for()
        page.locator('audio').wait_for()
        capture(page, output/'officer-audio-review.png')
        results['browser_audio_review_no_fake_transcript'] = 'passed'
        farmer.set_viewport_size({'width': 390, 'height': 844})
        capture(farmer, output/'farmer-mobile.png', [farmer.get_by_label('Case access token', exact=True)])
        assert farmer.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        results['mobile_no_horizontal_overflow'] = 'passed'
        for tab in (farmer, page):
            assert tab.locator('[data-testid="stException"]').count() == 0
        browser.close()
    client.close()
    return results


def main():
    work = Path(os.environ.get('AGRIREACH_BROWSER_WORK', '../browser-work')).resolve()
    output = Path(os.environ.get('AGRIREACH_BROWSER_EVIDENCE', 'output/playwright')).resolve()
    work.mkdir(parents=True, exist_ok=True); output.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='disposable-', dir=work))
    env = os.environ | {'DATABASE_URL': 'sqlite:///' + str(temp/'demo.db'), 'PYTHONPATH': str(ROOT/'src'),
        'AGRIREACH_API': API, 'AGRIREACH_SOURCE_CHECK': '0', 'AGRIREACH_RAINFALL': 'off',
        'AGRIREACH_STT': 'none', 'AGRIREACH_TTS': '', 'SMS_ENABLED': '0', 'WHATSAPP_ENABLED': '0',
        'AGRIREACH_SIMULATOR': '1', 'AGRIREACH_CONSENT': '1', 'AGRIREACH_MEDIA_DIR': str(temp/'media'),
        'AGRIREACH_OUTBOX': str(temp/'outbox'), 'LLM_BASE_URL': '', 'LLM_MODEL': '', 'LLM_API_KEY': '',
        'AGRIREACH_JUDGE_BASE_URL': '', 'AGRIREACH_JUDGE_API_KEY': ''}
    os.environ.update(env)
    from agrireach import db
    con = db.connect()
    token = db.add_officer(con, 'Disposable browser officer')
    processes = []
    try:
        for args in (['uvicorn','agrireach.api:app','--host','127.0.0.1','--port','18000','--no-access-log'],
            ['streamlit','run','src/agrireach/ui.py','--server.address','127.0.0.1','--server.port','18501','--server.headless','true','--browser.gatherUsageStats','false']):
            processes.append(subprocess.Popen([sys.executable, '-m', *args], cwd=ROOT, env=env,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for _ in range(180):
            if any(process.poll() is not None for process in processes):
                raise RuntimeError('A disposable server failed to start; check port availability')
            try:
                if httpx.get(UI+'/_stcore/health', trust_env=False).status_code == 200 and httpx.get(API+'/health', trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('Disposable servers did not become ready')
        result = walkthrough(con, token, output)
        (output/'browser-results.json').write_text(json.dumps({'mode': 'offline stub', 'checks': result}, indent=2), encoding='utf-8')
        print(json.dumps(result), flush=True)
    finally:
        con.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=20)


if __name__ == '__main__':
    main()
