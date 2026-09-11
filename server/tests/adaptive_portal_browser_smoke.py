"""Real browser checks for automatic device routing and ERP-native photo access."""
from __future__ import annotations
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'office-console'))
from photo_portal_smoke import FakeConnection, IMAGE
from web_ui_smoke import FakeProviders, build_browser_app, free_port, assert_layout_contract


def run():
    import uvicorn
    from fastapi.testclient import TestClient
    from playwright.sync_api import sync_playwright
    with tempfile.TemporaryDirectory(prefix='floodman-adaptive-browser-') as temporary:
        os.environ.update(OFFICE_CONSOLE_DATA_DIR=temporary, DOCUMENTS_PATH=temporary+'/documents',
                          OFFICE_SESSION_COOKIE_SECURE='false', OFFICE_AUTH_ENABLED='true',
                          INTERNAL_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=',
                          AI_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=')
        from app import main
        main.store.create_owner('Fictional Owner','owner@example.test','Fictional-Pass-2026!')
        main.providers = FakeProviders()
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        main.settings = replace(main.settings,public_url=base,external_portal_api_url='https://portal.example.test/portal/api/floodman.php',external_portal_api_token='fictional-test-secret-'*3)
        connection = FakeConnection(main.store,main.settings)
        main.portal_connection = connection
        client = TestClient(main.app)
        assert client.get('/office/photo-portal',follow_redirects=False).status_code in (302,303,307)
        assert client.post('/login',data={'email':'owner@example.test','password':'Fictional-Pass-2026!'}).status_code == 200
        assert client.post('/office/photo-portal/42/photos',headers={'Origin':'https://untrusted.example.test'},files={'photo':('test.png',IMAGE)}).status_code == 403
        assert not main.store.records('portal_uploads')
        server = uvicorn.Server(uvicorn.Config(build_browser_app(main),host='127.0.0.1',port=port,log_level='error',lifespan='off'))
        thread = threading.Thread(target=server.run,daemon=True)
        thread.start()
        for _ in range(100):
            if server.started: break
            time.sleep(.05)
        assert server.started
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                cases = [
                    ({'viewport':{'width':1440,'height':900}},'desktop'),
                    ({'viewport':{'width':640,'height':800}},'mobile'),
                    ({**playwright.devices['iPhone 13']},'mobile'),
                    ({**playwright.devices['iPhone 13 landscape']},'mobile'),
                    ({**playwright.devices['iPad Pro 11 landscape']},'mobile'),
                    ({'viewport':{'width':1440,'height':900},'has_touch':True},'desktop'),
                ]
                for options, mode in cases:
                    options.pop('default_browser_type',None)
                    context = browser.new_context(**options,service_workers='block')
                    context.add_init_script("localStorage.setItem('floodmanWorkspaceMode','desktop');localStorage.setItem('floodmanDesktopMode','1')")
                    context.route('https://portal.example.test/**',lambda route: route.fulfill(content_type='text/html',body="<html><meta name='viewport' content='width=device-width'><body style='background:#07111f;color:#edf4ff;font:16px system-ui'><h2>Project photos</h2><p>Fictional test gallery</p></body></html>"))
                    login = context.request.post(base+'/login',form={'email':'owner@example.test','password':'Fictional-Pass-2026!','next':'/office'})
                    assert login.status == 200
                    page = context.new_page()
                    errors = []
                    page.on('pageerror',lambda error: errors.append(str(error)))
                    page.goto(base+'/workspace',wait_until='domcontentloaded')
                    page.wait_for_url(re.compile(r'/office(?:/mobile)?$'))
                    assert page.locator('html').get_attribute('data-workspace') == mode
                    assert ('/office/mobile' in page.url) == (mode == 'mobile')
                    page.goto(base+'/office/photo-portal?job_id=42&desktop=1&mobile=1',wait_until='domcontentloaded')
                    assert page.get_by_role('heading',name='Fictional Residence').is_visible()
                    assert page.frame_locator('.portal-gallery-frame').get_by_role('heading',name='Project photos').is_visible()
                    assert page.locator('html').get_attribute('data-workspace') == mode
                    assert not page.locator('[data-use-desktop],[data-use-mobile]').count()
                    assert main.settings.external_portal_api_token not in page.content()
                    assert_layout_contract(page,'native portal '+mode,office_shell=True)
                    evidence = os.environ.get('FLOODMAN_UI_EVIDENCE_DIR')
                    if evidence and options['viewport']['width'] in (390,1440):
                        Path(evidence).mkdir(parents=True,exist_ok=True)
                        page.screenshot(path=str(Path(evidence)/f"native-portal-{options['viewport']['width']}.png"),full_page=True)
                    page.locator('.portal-upload summary').click()
                    page.locator('#portal-caption').fill('Unsaved test caption')
                    page.set_viewport_size({'width':390,'height':844})
                    assert page.locator('#portal-caption').input_value() == 'Unsaved test caption'
                    assert_layout_contract(page,'resized portal',office_shell=True)
                    assert not errors, errors
                    context.close()
                browser.close()
        finally:
            server.should_exit=True
            thread.join(timeout=10)
    print('Automatic first load, phone landscape, iPad, touch desktop, stale settings, native gallery, resize preservation, and CSRF checks passed')


if __name__ == '__main__':
    run()
