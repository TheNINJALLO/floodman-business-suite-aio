"""Isolated owner/admin authorization and real-browser setup matrix."""
import os
import re
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from web_ui_smoke import free_port
from integration_setup_smoke import EMAIL


def run():
    with tempfile.TemporaryDirectory(prefix="floodman-setup-ui-") as root:
        port = free_port(); base = f"http://127.0.0.1:{port}"
        os.environ.update(OFFICE_CONSOLE_DATA_DIR=root, DOCUMENTS_PATH=str(Path(root)/"documents"), OFFICE_SESSION_COOKIE_SECURE="false",
            OFFICE_CONSOLE_PUBLIC_URL=base, INTERNAL_HMAC_KEYS="v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=", AI_HMAC_KEYS="ai:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=")
        from app import main
        from fastapi.testclient import TestClient
        from playwright.sync_api import sync_playwright, expect
        import uvicorn
        owner = main.store.create_owner("Fictional Owner", "owner@example.com", "Fictional-Test-2026!")
        session = main.store.create_session(owner["id"])
        admin = main.store.upsert_gauzy_user(dict(name="Fictional Admin", email="admin@example.com", role="ADMIN", gauzy_user_id="fake-admin"))
        # Explicit staff role; identity translation cannot accidentally make this an owner fixture.
        main.store._state["users"][admin["id"]]["role"] = "ADMIN"
        main.store._save()
        admin_session = main.store.create_session(admin["id"])
        guest = TestClient(main.app, base_url=base, follow_redirects=False)
        url = "/office/service-setup"
        assert guest.get(url).status_code == 303
        guest.cookies.set("floodman_session", admin_session)
        assert guest.get(url).status_code == 403
        assert guest.post(url+"/email/save", data=EMAIL).status_code == 403
        guest.cookies.set("floodman_session", session)
        page = guest.get(url)
        assert page.status_code == 200 and page.headers["cache-control"] == "no-store"
        ticket = re.search("name='ticket' value='([^']+)'", page.text).group(1)
        values = dict(EMAIL, revision="0", ticket=ticket)
        assert guest.post(url+"/email/save", data=values, headers={"Origin":"https://attacker.example.com"}).status_code == 403
        assert guest.post(url+"/email/save", data={**values,"ticket":"fake"}, headers={"Origin":base}).status_code == 403
        assert guest.post(url+"/email/save", data=values, headers={"Origin":base}).status_code == 303
        assert guest.post(url+"/email/save", data=values, headers={"Origin":base}).status_code == 400
        assert EMAIL["password"] not in guest.get(url).text
        assert EMAIL["password"] not in str(main.store.snapshot())
        assert guest.post(url+"/email/save", content=b"x"*17000, headers={"Origin":base,"Content-Type":"application/x-www-form-urlencoded"}).status_code == 413
        server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, daemon=True); thread.start()
        deadline = time.time()+15
        while not server.started and time.time()<deadline: time.sleep(.05)
        assert server.started
        try:
            with patch("app.integration_setup.smtp_check"), patch("app.integration_setup.smtp_deliver") as send, sync_playwright() as playwright:
                for engine in (playwright.chromium, playwright.webkit):
                    browser = engine.launch(headless=True)
                    for width, height in ((320,568),(390,844),(768,1024),(1024,768),(1440,900)):
                        context = browser.new_context(viewport={"width":width,"height":height})
                        context.add_cookies([{"name":"floodman_session", "value":session, "url":base}])
                        page = context.new_page(); errors=[]
                        page.on("pageerror",lambda err:errors.append(str(err)))
                        page.goto(base+url, wait_until="networkidle")
                        expect(page.get_by_role("heading",name="Payments & email",exact=True)).to_be_visible()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                        assert page.locator("#email-password").input_value() == ""
                        page.locator("#email summary").click()
                        expect(page.locator("#email-host")).to_be_visible()
                        page.locator("#email-host").focus(); page.keyboard.press("Tab")
                        assert page.locator("#email-security").evaluate("e=>e===document.activeElement")
                        if engine.name == "chromium" and width == 390:
                            page.locator("#email").get_by_role("button",name="Check connection",exact=True).click()
                            expect(page.locator("#email")).to_contain_text("SMTP TLS connection and sign-in checked")
                            page.locator("#email input[name=confirmed]").check()
                            page.get_by_role("button",name="Enable email",exact=True).click()
                            expect(page.locator("#email .setup-status")).to_have_text("Email enabled")
                            page.locator("#email-recipient").fill("recipient@example.com")
                            page.get_by_role("button",name="Send test email",exact=True).click()
                            expect(page.locator(".callout.success[role=status]")).to_contain_text("mail server accepted")
                            assert send.call_count == 1
                            page.get_by_role("button",name="Disable email delivery",exact=True).click()
                            expect(page.locator("#email .setup-status")).to_have_text("Disabled")
                        assert EMAIL["password"] not in page.content() and not errors
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth+1")
                        context.close()
                    browser.close()
        finally:
            server.should_exit=True; thread.join(timeout=15)
        print("Setup UI: owner-only, CSRF/origin, no secret echo, actual forms, Chromium/WebKit 10-view matrix PASS")


if __name__ == "__main__": run()
