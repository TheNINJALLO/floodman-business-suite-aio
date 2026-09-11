"""Exercise real multi-file/camera controls and every job tab using fictional data."""
import asyncio
import os
import tempfile
import threading
import time
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from portal_tools_smoke import ToolsConnection, IMAGE, PortalTools, PhotoPortal
from web_ui_smoke import FakeProviders, build_browser_app, free_port, assert_layout_contract


class BrowserConnection(ToolsConnection):
    async def request(self, action, payload):
        if action == 'job-tools':
            return {'media':[{'id':1,'media_type':'photo','caption':'Fictional photo','topic':'Restoration','revision':'a'*64}],
                'notes':[{'id':2,'note':'Fictional note <script>unsafe</script>','updated_at':'2026-09-11','revision':'b'*64}],
                'receipts':[{'id':3,'vendor':'Fictional hardware','amount':12.34,'notes':'Staff-only supplies','revision':'c'*64}],
                'contents':[{'id':4,'name':'Fictional chair','category':'Furniture','condition':'Wet','description':'Test inventory','photo_ids':[1],'revision':'d'*64}],
                'receipt_total':12.34,'topics':['Restoration'],'categories':['Furniture'],'conditions':['Wet']}
        return await super().request(action,payload)


def run():
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix='floodman-portal-tools-browser-') as temporary:
        os.environ.update(OFFICE_CONSOLE_DATA_DIR=temporary,DOCUMENTS_PATH=temporary+'/documents',OFFICE_SESSION_COOKIE_SECURE='false',OFFICE_AUTH_ENABLED='true',
                          INTERNAL_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=',AI_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=')
        from app import main
        main.store.create_owner('Fictional Owner','owner@example.test','Fictional-Pass-2026!')
        main.providers=FakeProviders()
        port=free_port(); base=f'http://127.0.0.1:{port}'
        main.settings=replace(main.settings,public_url=base,external_portal_api_url='https://portal.example.test/api/floodman.php',external_portal_api_token='fictional-'*8)
        connection=BrowserConnection(main.store,main.settings); main.portal_connection=connection
        client=TestClient(main.app)
        assert client.post('/login',data={'email':'owner@example.test','password':'Fictional-Pass-2026!'}).status_code==200
        action='/office/photo-portal/42/actions'
        assert client.post(action,headers={'Origin':'https://evil.example.test'},json={}).status_code==403
        assert client.post(action,headers={'Origin':base},json=[]).status_code==422
        assert client.post(action,headers={'Origin':base},content=b'x'*64001).status_code==413
        assert client.post('/office/photo-portal/42/uploads/00000000-1111-4444-8888-111111111111/0',headers={'Origin':base},content=IMAGE).status_code==403
        server=uvicorn.Server(uvicorn.Config(build_browser_app(main),host='127.0.0.1',port=port,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,daemon=True); thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        try:
            with sync_playwright() as p:
                for engine,widths in [(p.chromium,[320,390,768,1024,1440]),(p.firefox,[390,1440]),(p.webkit,[390,1440])]:
                    browser=engine.launch(headless=True)
                    context=browser.new_context(service_workers='block')
                    assert context.request.post(base+'/login',form={'email':'owner@example.test','password':'Fictional-Pass-2026!'}).status==200
                    def remote(route):
                        if 'view=staff-gallery' in route.request.url:
                            route.fulfill(content_type='text/html',body='<h2>Project photos</h2>')
                        else: route.fulfill(content_type='image/png',body=IMAGE)
                    context.route('https://portal.example.test/**',remote)
                    page=context.new_page(); errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    for width in widths:
                        page.set_viewport_size({'width':width,'height':844 if width<768 else 900})
                        for tab in ('photos','videos','notes','receipts','contents'):
                            response=page.goto(base+f'/office/photo-portal?job_id=42&tab={tab}',wait_until='networkidle')
                            assert response.status==200
                            assert page.locator('.portal-tabs [aria-current=page]').inner_text()==tab.capitalize()
                            assert_layout_contract(page,f'{engine.name} {tab} {width}',office_shell=True)
                            page.locator('.portal-upload>summary').click()
                            assert_layout_contract(page,f'{engine.name} open {tab} {width}',office_shell=True)
                            assert page.locator('input[capture=environment]').count()==(0 if tab=='notes' else 1)
                            if tab=='receipts':
                                assert page.get_by_text('Total: $12.34').is_visible()
                                page.evaluate('window.print=()=>{window.fixturePrinted=true}')
                                page.locator('[data-portal-print]').click()
                                page.wait_for_function('window.fixturePrinted===true')
                            if tab=='notes': assert '<script>unsafe</script>' in page.locator('.portal-preserve').inner_text()
                            evidence=os.environ.get('FLOODMAN_UI_EVIDENCE_DIR')
                            if evidence and engine.name=='chromium' and width in (390,1440) and tab=='receipts':
                                Path(evidence).mkdir(parents=True,exist_ok=True)
                                page.screenshot(path=str(Path(evidence)/f'portal-receipts-{width}.png'),full_page=True)
                    if engine.name=='chromium':
                        page.goto(base+'/office/photo-portal?job_id=42',wait_until='networkidle')
                        page.locator('.portal-upload>summary').click()
                        form=page.locator('.portal-upload form')
                        form.locator('[name=files]').set_input_files([{'name':'one.png','mimeType':'image/png','buffer':IMAGE},{'name':'two.png','mimeType':'image/png','buffer':IMAGE}])
                        form.locator('#portal-caption').fill('Two fictional photos')
                        form.locator('[type=submit]').click()
                        page.wait_for_function("document.querySelector('.portal-upload [data-tool-status]').textContent.includes('Saved safely')")
                        rows=main.store.records('portal_actions')
                        assert len(rows)==2 and all(row['status']=='PENDING' for row in rows)
                        tools=PortalTools(PhotoPortal(connection))
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            for row in rows: executor.submit(lambda row=row: asyncio.run(tools.sync(row))).result()
                        page.wait_for_function("document.querySelector('.portal-upload [data-tool-status]').textContent.includes('Saved to the portal')")
                        page.goto(base+'/office/photo-portal?job_id=42&tab=receipts',wait_until='networkidle')
                        page.locator('.portal-upload>summary').click()
                        form=page.locator('.portal-upload form')
                        form.locator('[name=camera]').set_input_files({'name':'receipt.png','mimeType':'image/png','buffer':IMAGE})
                        form.locator('[name=vendor]').fill('Fictional vendor'); form.locator('[name=amount]').fill('9.50')
                        form.locator('[type=submit]').click()
                        page.wait_for_function("document.querySelector('.portal-upload [data-tool-status]').textContent.includes('Saved safely')")
                        receipt=next(row for row in main.store.records('portal_actions') if row['kind']=='receipt')
                        assert receipt['fields']['amount']=='9.50' and receipt['status']=='PENDING'
                        with ThreadPoolExecutor(max_workers=1) as executor:
                            executor.submit(lambda: asyncio.run(tools.sync(receipt))).result()
                        page.goto(base+'/office/photo-portal?job_id=42&tab=notes',wait_until='networkidle')
                        page.locator('.portal-upload>summary').click()
                        form=page.locator('.portal-upload form'); form.locator('[name=note]').fill('Another fictional staff note'); form.locator('[type=submit]').click()
                        page.wait_for_function("document.querySelector('.portal-upload [data-tool-status]').textContent.includes('Saved safely')")
                        assert any(row['kind']=='note' for row in main.store.records('portal_actions'))
                    assert not errors,errors
                    context.close(); browser.close()
        finally:
            server.should_exit=True; thread.join(timeout=10)
    print('Job tools browser: five tabs, 320-1440 layouts, Chromium/Firefox/WebKit, batch photos, receipt camera/totals/print, notes, CSRF and limits passed')


if __name__=='__main__':
    run()
