"""Chrome acceptance on ports 8501/8502 with an isolated API/database.

Stop the pilot UIs before running. The original API on port 8000 is untouched.
No pilot credentials, databases, or messages are used.
"""
import os, sys, json, tempfile, subprocess, time
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]

def main():
    output=Path(os.environ.get('AGRIREACH_BROWSER_EVIDENCE','output/playwright/separate')).resolve()
    output.mkdir(parents=True,exist_ok=True)
    temp=Path(tempfile.mkdtemp(prefix='separate-demo-',dir=ROOT.parent))
    env=os.environ|{'PYTHONPATH':str(ROOT/'src'),'DATABASE_URL':'sqlite:///'+str(temp/'demo.db'),
        'AGRIREACH_API':'http://127.0.0.1:18000','AGRIREACH_SOURCE_CHECK':'0','AGRIREACH_RAINFALL':'off',
        'AGRIREACH_STT':'none','AGRIREACH_TTS':'','AGRIREACH_SIMULATOR':'0','SMS_ENABLED':'0','WHATSAPP_ENABLED':'0',
        'LLM_BASE_URL':'','LLM_MODEL':'','LLM_API_KEY':'','AGRIREACH_JUDGE_BASE_URL':'','AGRIREACH_JUDGE_API_KEY':'',
        'AGRIREACH_MEDIA_DIR':str(temp/'media'),'AGRIREACH_OUTBOX':str(temp/'outbox')}
    os.environ.update(env)
    from agrireach import db,knowledge
    con=db.connect();token=db.add_officer(con,'Disposable verification officer')
    processes=[];checks={}
    def settle(page):
        page.wait_for_timeout(250)
        page.locator('[data-testid="stApp"][data-test-script-state="notRunning"]').wait_for()
    def shot(page,name):
        settle(page)
        page.locator('[data-testid="stMain"]').evaluate('(e)=>e.scrollTop=0')
        page.screenshot(path=str(output/name),full_page=True,mask=page.get_by_label('Private access code',exact=True).all(),mask_color='#dce5d6')
    try:
        commands=[['uvicorn','agrireach.api:app','--host','127.0.0.1','--port','18000','--ws','none','--no-access-log']]
        for role,port in [('farmer',8501),('officer',8502)]:
            commands.append(['streamlit','run',f'src/agrireach/{role}_ui.py','--server.address','127.0.0.1','--server.port',str(port),'--server.headless','true','--browser.gatherUsageStats','false'])
        for args in commands:
            processes.append(subprocess.Popen([sys.executable,'-m',*args],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL))
        for _ in range(120):
            try:
                if all(httpx.get(f'http://127.0.0.1:{p}/_stcore/health',trust_env=False).status_code==200 for p in (8501,8502)):break
            except httpx.HTTPError:pass
            time.sleep(1)
        with httpx.Client(base_url=env['AGRIREACH_API'],trust_env=False,timeout=180) as client, sync_playwright() as p:
            browser=p.chromium.launch(channel='chrome',headless=True)
            ctx=browser.new_context(permissions=['clipboard-read','clipboard-write'],viewport={'width':1440,'height':1400})
            farmer=ctx.new_page();officer=ctx.new_page()
            for tab in (farmer,officer):tab.set_default_timeout(60000)
            farmer.goto('http://127.0.0.1:8501');farmer.get_by_label('Your question',exact=True).wait_for()
            assert farmer.get_by_role('link',name='Extension officer',exact=True).count()==0
            assert farmer.get_by_label('Officer sign in token',exact=True).count()==0
            assert farmer.locator('input[type=file]').count()==0
            assert 'Voice simulator' not in farmer.locator('body').inner_text()
            farmer.reload();farmer.get_by_label('Your question',exact=True).wait_for()
            officer.goto('http://127.0.0.1:8502');officer.get_by_label('Officer sign in token',exact=True).wait_for()
            officer.reload();officer.get_by_label('Officer sign in token',exact=True).wait_for()
            shot(officer,'officer-sign-in.png')
            officer.get_by_label('Officer sign in token',exact=True).fill('invalid')
            officer.get_by_role('button',name='Sign in',exact=True).click()
            officer.get_by_text('Sign in with a valid officer token to continue.',exact=True).wait_for()
            officer.evaluate('(v)=>navigator.clipboard.writeText(v)',token)
            field=officer.get_by_label('Officer sign in token',exact=True);field.click();field.press('Control+a');field.press('Control+v')
            officer.get_by_role('button',name='Sign in',exact=True).click()
            officer.get_by_role('button',name='Sign out',exact=True).wait_for()
            officer.evaluate('()=>navigator.clipboard.writeText("")')
            farmer.get_by_label('Your question',exact=True).fill('When should I harvest soybean in Tamale?')
            farmer.get_by_role('button',name='Send question',exact=True).click()
            farmer.get_by_text('We received your question.',exact=False).wait_for(timeout=180000)
            cid=int(farmer.get_by_label('Question number',exact=True).input_value())
            private=farmer.get_by_label('Private access code',exact=True).input_value()
            access={'X-Case-Access-Token':private};auth={'Authorization':'Bearer '+token}
            farmer.get_by_role('button',name='Check answer',exact=True).click()
            farmer.get_by_text('Waiting for officer review. Advice is not available yet.',exact=True).wait_for()
            assert client.get(f'/farmer/cases/{cid}',headers=access).json()['answer'] is None
            assert client.post(f'/cases/{cid}/release',headers=auth).status_code>=400
            shot(farmer,'farmer-pending.png')
            button=officer.get_by_role('button',name=f'Open case {cid} · pending review',exact=True)
            button.wait_for();shot(officer,'officer-dashboard.png');button.click()
            officer.get_by_label('Officer draft with citations',exact=True).wait_for()
            officer.get_by_text('Read source evidence',exact=True).click()
            shot(officer,'officer-case-review.png')
            assert officer.get_by_role('button',name='Approve and release',exact=True).is_disabled()
            approved=knowledge.reference('APNI-SARI-2023:harvest')['text']
            edit=officer.get_by_label('Farmer text: exactly what will be sent',exact=True)
            edit.fill(approved);edit.press('Tab');settle(officer)
            officer.get_by_text('Required for approval: I checked every advice line against the cited sources',exact=True).click();settle(officer)
            officer.get_by_role('button',name='Approve and release',exact=True).click()
            officer.get_by_text('Advice approved and released for the farmer to read.',exact=True).wait_for()
            farmer.get_by_role('button',name='Check answer',exact=True).click();farmer.get_by_text(approved,exact=True).wait_for()
            shot(farmer,'farmer-approved.png')
            for headers in ({},{'Authorization':'Bearer invalid'},{'Authorization':'Bearer '+private}):
                assert client.get('/officer/queue',headers=headers).status_code==401
                assert client.post(f'/cases/{cid}/release',headers=headers).status_code==401
            officer.get_by_role('button',name='Sign out',exact=True).click();officer.get_by_label('Officer sign in token',exact=True).wait_for()
            farmer.set_viewport_size({'width':390,'height':844});shot(farmer,'farmer-mobile.png')
            assert farmer.evaluate('document.documentElement.scrollWidth<=innerWidth')
            for tab in (farmer,officer):assert tab.locator('[data-testid="stException"]').count()==0
            browser.close()
            checks={k:'passed' for k in ['independent_portals','no_farmer_officer_or_voice_controls','direct_urls_and_refresh','invalid_officer_credentials','native_clipboard_login','farmer_submission','pending_no_release','automatic_queue','source_review','approval_and_answer','unauthorized_access','sign_out','mobile_layout']}
        (output/'results.json').write_text(json.dumps({'mode':'offline stub','database':'disposable','browser':'Chrome','checks':checks},indent=2))
        print(json.dumps(checks))
    finally:
        con.close()
        for process in processes:process.terminate()
        for process in processes:process.wait(timeout=20)

if __name__=='__main__':main()
