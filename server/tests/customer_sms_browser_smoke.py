"""No production traffic: public token authorization, real forms, and responsive UI."""
import os
import re
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from customer_sms_smoke import Mirror
from web_ui_smoke import free_port


def run():
    with tempfile.TemporaryDirectory(prefix='floodman-customer-sms-ui-') as root:
        os.environ.update(OFFICE_CONSOLE_DATA_DIR=root, DOCUMENTS_PATH=str(Path(root)/'documents'),
            OFFICE_SESSION_COOKIE_SECURE='false', INTERNAL_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=',
            AI_HMAC_KEYS='ai:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=')
        from app import main
        from app.customer_sms import CustomerSms
        from app.security import SignedClient
        from fastapi.testclient import TestClient
        from playwright.sync_api import sync_playwright, expect
        import uvicorn
        port=free_port(); base=f'http://127.0.0.1:{port}'
        main.settings=replace(main.settings,public_url=base,customer_public_url=base+'/customer')
        mirror=Mirror(main.store)
        main.customer_sms=CustomerSms(main.store,SimpleNamespace(orchestrator=mirror),main.settings)
        main.store.create_owner('Fictional Owner','owner@example.test','Fictional-Test-2026!')
        customer=main.store.create_record('contacts',{'name':'Fictional Customer','email':'customer@example.test'})
        other=main.store.create_record('contacts',{'name':'Other Customer'})
        token='fictional-private-portal-token-001'
        document=main.store.create_record('estimates',{'contact_id':customer['id'],'public_token':token,
            'public_enabled':True,'title':'Fictional estimate','estimate_number':'TEST-001','total_cents':0})
        main.store.create_record('invoices',{'contact_id':other['id'],'public_token':'other-private-document-token-002','public_enabled':True})
        guest=TestClient(main.app,base_url=base,follow_redirects=False)
        for page in ('privacy','terms','program'):
            assert guest.get('/customer/sms/'+page).status_code==200
        assert guest.get('/office/messages').status_code==303
        assert guest.post('/internal/v1/customer-sms/check',json={'phone_e164':'+12315550100'}).status_code==401
        for path in ('/customer/estimate/invalid/sms-consent',f'/customer/invoice/{token}/sms-consent'):
            assert guest.post(path,data={}).status_code==404
        path=f'/customer/estimate/{token}/sms-consent'
        fields=dict(ticket=main.customer_sms.ticket(token,customer['id']),choice='enable',phone='2315550100')
        assert guest.post(path,data=fields).status_code==422
        fields['consent']='yes'
        assert guest.post(path,data=fields,headers={'Origin':'https://attacker.example.test'}).status_code==403
        other_fields={**fields,'ticket':main.customer_sms.ticket(token,other['id'])}
        assert guest.post(path,data=other_fields).status_code==422
        assert not main.store.records('customer_sms_events')
        server=uvicorn.Server(uvicorn.Config(main.app,host='127.0.0.1',port=port,log_level='error',access_log=False))
        thread=threading.Thread(target=server.run,daemon=True); thread.start()
        deadline=time.time()+15
        while not server.started and time.time()<deadline: time.sleep(.05)
        assert server.started
        try:
            with sync_playwright() as playwright:
                for engine in (playwright.chromium,playwright.webkit):
                    browser=engine.launch(headless=True)
                    for width in (390,768,1440):
                        page=browser.new_page(viewport={'width':width,'height':900})
                        errors=[]; page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(base+f'/customer/estimate/{token}',wait_until='networkidle')
                        box=page.locator('#sms-consent')
                        assert not box.is_checked()
                        page.locator('#sms-preferences').scroll_into_view_if_needed()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.locator('#sms-mobile').fill('2315550100')
                        page.get_by_role('button',name='Enable text updates',exact=True).click()
                        expect(page.locator('[role=alert]')).to_be_visible()
                        assert not box.is_checked()
                        if engine.name=='chromium' and width==390:
                            page.locator('#sms-mobile').fill('2315550100'); box.check()
                            page.get_by_role('button',name='Enable text updates',exact=True).click()
                            expect(page.locator('[role=status]')).to_be_visible()
                            assert 'saved' in page.locator('[role=status]').inner_text()
                            assert not page.locator('#sms-consent').is_checked()
                            preference=main.customer_sms.current(customer['id'])
                            assert preference['status']=='OPTED_IN'
                            signing=SignedClient.from_key_string(base,main.settings.internal_hmac_keys)
                            body=b'{"organization_id":"floodman","phone_e164":"+12315550100"}'
                            state=guest.post('/internal/v1/customer-sms/check',content=body,headers=signing.headers(body)).json()
                            assert state['managed'] and state['status']=='OPTED_IN' and state['sync_status']=='PENDING'
                            page.get_by_role('button',name='Turn off text updates',exact=True).click()
                            expect(page.locator('[role=status]')).to_contain_text('turned off')
                            assert main.customer_sms.current(customer['id'])['status']=='OPTED_OUT'
                            assert not main.customer_sms.current(other['id'])
                        assert not errors,errors
                        for legal in ('privacy','terms','program'):
                            page.goto(base+'/customer/sms/'+legal)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.close()
                    browser.close()
        finally:
            server.should_exit=True;thread.join(timeout=15)
    print('Customer SMS browser/authentication matrix: PASS')


if __name__=='__main__': run()
