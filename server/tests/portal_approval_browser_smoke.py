"""Real-browser approval and authorization checks using fictional, isolated data."""
from __future__ import annotations
import os
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'office-console'))
from ai_call_intake_smoke import projection
from web_ui_smoke import FakeProviders, browser_executable, build_browser_app, free_port


def run():
    with tempfile.TemporaryDirectory(prefix='floodman-approval-browser-') as temporary:
        os.environ.update(OFFICE_CONSOLE_DATA_DIR=temporary, DOCUMENTS_PATH=str(Path(temporary)/'documents'),
                          OFFICE_SESSION_COOKIE_SECURE='false', INTERNAL_HMAC_KEYS='v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=',
                          AI_HMAC_KEYS='ai-v1:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=')
        from app import main
        from app.roomflow_supabase import ensure_roomflow_workspaces
        from fastapi.testclient import TestClient
        from playwright.sync_api import sync_playwright
        import uvicorn
        port = free_port()
        base = f'http://127.0.0.1:{port}'
        main.settings = replace(main.settings, public_url=base)
        main.providers = FakeProviders()
        owner = main.store.create_owner('Fictional Owner', 'owner@example.test', 'Fictional-2026-Password!')
        workspace = ensure_roomflow_workspaces(main.store, actor_id=owner['id'])[0]['id']
        intake = main.store.project_call_intake(projection('fictional-browser-call', workspace), require_approval=True)
        assert intake['projection_status'] == 'PENDING' and intake['notification_ids']
        contact = main.store.create_record('contacts', {'workspace_id':workspace,'name':'Existing Test Customer','email':'existing@example.test','phone':'+12315550188'}, actor_id=owner['id'])
        prop = main.store.create_record('properties', {'workspace_id':workspace,'contact_id':contact['id'],'service_street':'42 Test Street','service_city':'Traverse City','service_state':'MI','service_postal_code':'49684'}, actor_id=owner['id'])
        other = main.store.create_record('contacts', {'workspace_id':workspace,'name':'Another Test Customer'}, actor_id=owner['id'])
        other_prop = main.store.create_record('properties', {'workspace_id':workspace,'contact_id':other['id'],'service_street':'Private Other Address'}, actor_id=owner['id'])
        path = '/office/calls/' + intake['id']
        anonymous = TestClient(main.app, base_url=base, follow_redirects=False)
        assert anonymous.post(path+'/approve').status_code in (303,401,403)
        client = TestClient(main.app, base_url=base, follow_redirects=False)
        client.cookies.set('floodman_session', main.store.create_session(owner['id']))
        assert client.post(path+'/approve', headers={'Origin':'https://attacker.example.test'}).status_code == 403
        assert client.post(path+'/approve').status_code == 403
        viewer = main.store.upsert_gauzy_user({'id':'fictional-viewer','email':'viewer@example.test','name':'Viewer','role':'VIEWER','gauzy_role':'VIEWER'})
        unprivileged = TestClient(main.app, base_url=base, follow_redirects=False)
        unprivileged.cookies.set('floodman_session', main.store.create_session(viewer['id']))
        assert unprivileged.post(path+'/approve', headers={'Origin':base}).status_code == 403
        server = uvicorn.Server(uvicorn.Config(build_browser_app(main), host='127.0.0.1', port=port, log_level='error', lifespan='off'))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            for _ in range(100):
                if server.started: break
                time.sleep(.05)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(executable_path=browser_executable(), headless=True)
                context = browser.new_context()
                context.add_cookies([{'name':'floodman_session','value':main.store.create_session(owner['id']),'url':base}])
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for width, height in [(320,568),(390,844),(844,390),(1440,900)]:
                    page.set_viewport_size({'width':width,'height':height})
                    page.goto(base+path+'?customer_id='+contact['id'], wait_until='networkidle')
                    section = page.locator('section.card').filter(has=page.get_by_role('heading',name='Review and approve'))
                    assert section.get_by_label('Property').locator('option').count() == 2
                    assert other_prop['id'] not in section.inner_html()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                    assert section.get_by_role('button',name='Approve and create customer files').is_visible()
                section.get_by_label('Property').select_option(prop['id'])
                # An existing property must work even if the caller gave no usable address.
                for key in ('street','city','state','postal_code'):
                    section.locator(f'input[name={key}]').fill('')
                section.get_by_role('button',name='Approve and create customer files').click()
                page.get_by_role('heading',name='Customer files approved').wait_for()
                linked = main.store.record('call_intakes',intake['id'])
                assert linked['approval_status'] == 'APPROVED' and linked['property_id'] == prop['id']
                assert len(main.store.records('estimates')) == 1
                assert not main.providers.sent_emails and not main.providers.sent_sms
                assert not errors, errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    print('Approval UI passed four viewports, property filtering, session/permission/CSRF checks, and no automatic customer messages')


if __name__ == '__main__': run()
