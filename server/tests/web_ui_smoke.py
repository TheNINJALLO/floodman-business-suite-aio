from __future__ import annotations

import os
import re
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


class FakeProviders:
    async def lab_state(self) -> dict[str, Any]:
        return {
            "demo_job_id": "ui-smoke-job",
            "job": {},
            "gauzy_contacts": {"items": []},
            "properties": [],
            "gauzy_invoices": {"items": []},
            "gauzy_payments": {"items": []},
            "square_invoices": [],
            "envelopes": [],
            "staff_alerts": [],
            "ar_cases": [],
            "sms_messages": [],
            "messages": [],
            "message_threads": [],
            "emails": [],
            "imported_documents": [],
            "notes": [],
        }

    async def competitor_targets(self) -> list[dict[str, Any]]:
        return []

    async def competitor_reports(self) -> list[dict[str, Any]]:
        return []

    async def gauzy_context(self) -> dict[str, Any]:
        return {
            "tenant_id": "ui-smoke-tenant",
            "organization_id": "ui-smoke-organization",
            "from_organization_id": "ui-smoke-organization",
            "sync_enabled": False,
        }

    def square_payment_configuration(self) -> dict[str, Any]:
        return {
            "environment": "local",
            "application_id": "",
            "location_id": "local-square-location",
            "sdk_url": "",
            "live": False,
            "local_mock": True,
        }


def seed(main: Any) -> dict[str, Any]:
    owner = main.store.create_owner("UI Smoke Owner", "owner@example.test", "Floodman-Test-2026!")
    contact = main.store.create_record(
        "contacts",
        {
            "name": "Alex Carter",
            "first_name": "Alex",
            "last_name": "Carter",
            "email": "alex@example.test",
            "phone": "2315550148",
            "status": "ACTIVE_CUSTOMER",
            "street": "1847 Pine Ridge Lane",
            "city": "Traverse City",
            "state": "MI",
            "postal_code": "49686",
        },
        actor_id=owner["id"],
    )
    property_record = main.store.create_record(
        "properties",
        {
            "contact_id": contact["id"],
            "name": "Carter Residence",
            "property_name": "Carter Residence",
            "property_type": "Residential",
            "service_street": "1847 Pine Ridge Lane",
            "service_city": "Traverse City",
            "service_state": "MI",
            "service_postal_code": "49686",
        },
        actor_id=owner["id"],
    )
    section = {"id": "section-1", "name": "Waterproofing", "description": "", "sort_order": 0}
    line = {
        "id": "line-1",
        "section_id": "section-1",
        "section_name": "Waterproofing",
        "name": "Interior perimeter drainage",
        "description": "Install a customer-approved drainage system.",
        "quantity": 10,
        "unit": "LF",
        "unit_price_cents": 4500,
        "line_total_cents": 45000,
        "selected": True,
        "sort_order": 0,
    }
    common = {
        "contact_id": contact["id"],
        "property_id": property_record["id"],
        "title": "Carter basement waterproofing",
        "currency": "USD",
        "sections": [section],
        "line_items": [line],
        "total_cents": 45000,
        "terms": "Payment is due according to the signed agreement.",
    }
    estimate = main.store.create_record(
        "estimates",
        {
            **common,
            "estimate_number": "EST-UI-001",
            "status": "ACCEPTED",
            "deposit_type": "PERCENT",
            "deposit_percent": 30,
            "deposit_due_stage": "IMMEDIATELY",
            "deposit_payable": True,
        },
        actor_id=owner["id"],
    )
    invoice = main.store.create_record(
        "invoices",
        {
            **common,
            "invoice_number": "INV-UI-001",
            "status": "PARTIALLY_PAID",
            "balance_cents": 30000,
            "paid_cents": 15000,
            "collection_mode": "PAYMENT_PAGE",
        },
        actor_id=owner["id"],
    )
    payment = main.store.create_record(
        "payments",
        {
            "invoice_id": invoice["id"],
            "contact_id": contact["id"],
            "amount_cents": 15000,
            "currency": "USD",
            "status": "COMPLETED",
            "method": "CARD",
            "payment_date": "2026-08-12",
            "processor_payment_id": "ui-smoke-payment",
            "card_brand": "VISA",
            "last_4": "1111",
        },
        actor_id=owner["id"],
    )
    estimate = main._ensure_public_document("estimate", estimate, actor_id=owner["id"])
    invoice = main._ensure_public_document("invoice", invoice, actor_id=owner["id"])
    return {"owner": owner, "contact": contact, "property": property_record, "estimate": estimate, "invoice": invoice, "payment": payment}


def route_smoke(main: Any, records: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient

    client = TestClient(main.app, follow_redirects=False)
    login = client.post(
        "/login",
        data={"email": "owner@example.test", "password": "Floodman-Test-2026!", "next": "/office/desktop"},
    )
    assert login.status_code == 303
    assert "floodman_session" in client.cookies

    pages = [
        "/setup", "/office", "/office/desktop", "/office/mobile?mobile=1", "/office/apps",
        "/office/linking", "/office/imports", "/office/contacts", "/office/properties",
        "/office/catalog", "/office/estimates", "/office/estimates/new", "/office/invoices",
        "/office/payments", "/office/payment-settings", "/office/documents", "/office/tasks",
        "/office/notes", "/office/time", "/office/members", "/office/messages",
        "/office/receivables", "/office/intelligence", "/office/alerts", "/office/platform",
        "/office/signing", "/office/roomflow",
        f"/office/contacts/{records['contact']['id']}",
        f"/office/contacts/{records['contact']['id']}/edit",
        f"/office/properties/{records['property']['id']}",
        f"/office/properties/{records['property']['id']}/edit",
        f"/office/estimates/{records['estimate']['id']}",
        f"/office/estimates/{records['estimate']['id']}/edit",
        f"/office/estimates/{records['estimate']['id']}/take-payment",
        f"/office/invoices/{records['invoice']['id']}",
        f"/office/invoices/{records['invoice']['id']}/edit",
        f"/office/invoices/{records['invoice']['id']}/take-payment",
    ]
    for path in pages:
        response = client.get(path)
        assert response.status_code == 200, f"{path} returned {response.status_code}: {response.text[:300]}"
        assert "Floodman" in response.text, f"{path} did not render a Floodman page"

    for kind in ("estimate", "invoice"):
        record = records[kind]
        token = record["public_token"]
        public_page = client.get(f"/customer/{kind}/{token}")
        assert public_page.status_code == 200
        assert "Created by Josh Aldrich" not in public_page.text or "Floodman" in public_page.text
        pdf = client.get(f"/customer/{kind}/{token}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF-")

    pay = client.get(f"/customer/pay/{records['invoice']['public_token']}")
    assert pay.status_code == 200 and "secure payment" in pay.text.lower()
    receipt = client.get(
        f"/customer/receipt/{records['invoice']['public_token']}?payment={records['payment']['id']}"
    )
    assert receipt.status_code == 200 and "PAYMENT RECEIPT" in receipt.text
    legacy = client.get("/office/gauzy")
    assert legacy.status_code in {302, 303, 307, 308}


def static_overlay_contracts() -> None:
    sources = {
        "pwa_js": (ROOT / "pwa" / "floodman-pwa.js").read_text(encoding="utf-8"),
        "pwa_css": (ROOT / "pwa" / "floodman-pwa.css").read_text(encoding="utf-8"),
        "panel_js": (ROOT / "roomflow" / "floodman-panel.js").read_text(encoding="utf-8"),
        "panel_css": (ROOT / "roomflow" / "floodman-panel.css").read_text(encoding="utf-8"),
        "legacy_js": (ROOT / "roomflow" / "floodman-roomflow.js").read_text(encoding="utf-8"),
        "legacy_css": (ROOT / "roomflow" / "floodman-roomflow.css").read_text(encoding="utf-8"),
        "hub_js": (ROOT / "hub" / "hub.js").read_text(encoding="utf-8"),
        "launcher": (REPO / "launcher" / "mobile-start.sh").read_text(encoding="utf-8"),
        "deployment": (REPO / "deployment" / "releases" / "mobile-start-v4.6.9.sh").read_text(encoding="utf-8"),
        "nginx": (ROOT / "aio" / "nginx.conf.template").read_text(encoding="utf-8"),
        "office": (ROOT / "office-console" / "app" / "main.py").read_text(encoding="utf-8"),
    }
    assert "fm-pwa-toast-dismiss" in sources["pwa_js"] and "Dismiss notification" in sources["pwa_js"]
    assert ".fm-pwa-toast-dismiss" in sources["pwa_css"]
    assert "fm-rf-panel-dismissed" in sources["panel_js"]
    assert "event.key === 'Escape'" in sources["panel_js"]
    assert "No separate RoomFlow account is required" in sources["panel_js"]
    assert "authOverlay.style.display = 'none'" in sources["panel_js"]
    assert "btn-more-create-company" in sources["panel_js"] and "changeWorkspace" in sources["panel_js"]
    assert "/office/api/roomflow/workspaces" in sources["office"]
    assert ":not(.fm-rf-panel-dismissed)" in sources["panel_css"]
    assert "fmrf-close-icon" in sources["legacy_js"] and "aria-label','Close save dialog" in sources["legacy_js"]
    assert "e.key === 'Escape'" in sources["legacy_js"] and "fmrf-modal-open" in sources["legacy_css"]
    assert "aria-modal" in sources["hub_js"] and "Back to Floodman" in sources["hub_js"]
    assert "location = /api/auth/login" in sources["nginx"]
    assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in sources["nginx"]
    assert "error_page 401 =302 /login?next=/roomflow/" in sources["nginx"]
    assert "floodmanLoginNext" in sources["office"] and "/login/erp-session" in sources["office"]
    for key in ("launcher", "deployment"):
        assert "floodman-dismiss-recovery" in sources[key]
        assert "event.key === 'Escape'" in sources[key]
        assert "Created by Josh Aldrich" in sources[key]
        assert "const pendingLoginKey = 'floodmanLoginNext'" in sources[key]
        assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in sources[key]


def browser_executable() -> str | None:
    candidates = [
        shutil.which("msedge"), shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((str(candidate) for candidate in candidates if candidate and Path(candidate).is_file()), None)


def build_browser_app(main: Any) -> Any:
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    app = FastAPI()

    files = {
        "/floodman-pwa.css": ROOT / "pwa" / "floodman-pwa.css",
        "/floodman-pwa.js": ROOT / "pwa" / "floodman-pwa.js",
        "/floodman-sw.js": ROOT / "pwa" / "floodman-sw.js",
        "/floodman-workspace.css": ROOT / "pwa" / "workspace-mode.css",
        "/manifest.webmanifest": ROOT / "pwa" / "manifest.webmanifest",
        "/hub.css": ROOT / "hub" / "hub.css",
        "/hub.js": ROOT / "hub" / "hub.js",
        "/roomflow/floodman-panel.css": ROOT / "roomflow" / "floodman-panel.css",
        "/roomflow/floodman-panel.js": ROOT / "roomflow" / "floodman-panel.js",
        "/legacy-roomflow.css": ROOT / "roomflow" / "floodman-roomflow.css",
        "/legacy-roomflow.js": ROOT / "roomflow" / "floodman-roomflow.js",
    }
    for route, path in files.items():
        app.add_api_route(route, lambda path=path: FileResponse(path), methods=["GET"])

    @app.get("/floodman-brand/{name}")
    def brand(name: str) -> FileResponse:
        assert name in {"floodman-mark.svg", "floodman-wordmark.svg"}
        return FileResponse(ROOT / "hub" / "brand" / name)

    @app.get("/floodman-pwa-icons/{name}")
    def pwa_icon(name: str) -> FileResponse:
        path = ROOT / "pwa" / "icons" / name
        return FileResponse(path)

    @app.get("/office-health/live")
    def office_health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "4.6.9"})

    @app.get("/hub-fixture")
    def hub_fixture() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/hub.css'></head><body><main><h1>Floodman ERP fixture</h1></main><script>window.FLOODMAN_HUB_CONFIG={officeUrl:location.origin,competitorUrl:location.origin+'/office/intelligence'};</script><script src='/hub.js'></script></body></html>""")

    @app.get("/roomflow/")
    def roomflow_fixture() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/roomflow/floodman-panel.css'></head><body><main><h1>RoomFlow fixture</h1><canvas id='sketch-canvas' width='320' height='240'></canvas><div class='checklist-room-card'><h3>Active Workspaces</h3><p>Legacy account controls</p><select id='more-company-switcher'><option value=''>Select...</option></select><input id='more-new-company-name'><button id='btn-more-create-company'>Create</button><button onclick='RoomFlowAuth.signOut()'>Log Out from Account</button></div><button id='btn-refresh-shared-jobs'>Refresh Shared Jobs</button></main><div id='auth-overlay' class='hidden' style='display:none'>Separate RoomFlow account required</div><script>window.state={currentJobName:'UI Fixture',costing:{customItems:[]}};window.switchTab=function(){};window.RoomFlowAuth={signOut:function(){}};window.__legacyAccountPrompted=false;document.addEventListener('DOMContentLoaded',function(){document.getElementById('btn-more-create-company').addEventListener('click',function(){window.__legacyAccountPrompted=true;document.getElementById('auth-overlay').style.display='flex';});});</script><script src='/roomflow/floodman-panel.js'></script></body></html>""")

    @app.get("/legacy-roomflow")
    def legacy_roomflow_fixture() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/legacy-roomflow.css'></head><body><main><h1>Legacy RoomFlow fixture</h1></main><script>window.state={currentJobName:'Legacy Fixture',costing:{customItems:[]}};</script><script src='/legacy-roomflow.js'></script></body></html>""")

    app.mount("/", main.app)
    return app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def browser_smoke(main: Any) -> None:
    executable = browser_executable()
    if not executable:
        print("Browser UI smoke skipped: no local Chromium-family executable")
        return

    import uvicorn
    from playwright.sync_api import sync_playwright

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(build_browser_app(main), host="127.0.0.1", port=port, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "Browser fixture server did not start"
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable, headless=True)
            desktop = browser.new_context(viewport={"width": 1440, "height": 900})
            page = desktop.new_page()
            page.goto(base + "/login/local?next=/office/desktop")
            form = page.locator("form[action='/login']")
            form.locator("input[name='email']").fill("owner@example.test")
            form.locator("input[name='password']").fill("Floodman-Test-2026!")
            form.locator("button").click()
            page.wait_for_url(re.compile(r"/office/desktop"))

            desktop_pages = [
                "/setup", "/office/desktop?desktop=1", "/office/apps", "/office/linking", "/office/imports",
                "/office/contacts", "/office/properties", "/office/catalog", "/office/estimates",
                "/office/estimates/new", "/office/invoices", "/office/payments", "/office/payment-settings",
                "/office/documents", "/office/tasks", "/office/notes", "/office/time", "/office/members",
                "/office/messages", "/office/receivables", "/office/intelligence", "/office/alerts",
                "/office/platform", "/office/signing", "/office/roomflow",
            ]
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for path in desktop_pages:
                response = page.goto(base + path, wait_until="domcontentloaded")
                assert response and response.status == 200, f"desktop browser route failed: {path}"
                assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"), f"desktop horizontal overflow: {path}"

            page.goto(base + "/office/desktop?desktop=1", wait_until="domcontentloaded")
            page.evaluate("window.dispatchEvent(new Event('appinstalled'))")
            toast = page.locator("#fm-pwa-toast")
            toast.wait_for(state="visible")
            toast.locator(".fm-pwa-toast-dismiss").click()
            assert not toast.evaluate("node => node.classList.contains('is-visible')")

            hub_response = page.goto(base + "/hub-fixture", wait_until="domcontentloaded")
            page.wait_for_timeout(250)
            assert hub_response and hub_response.status == 200
            assert page.locator(".fm-hub-trigger").count() == 1, f"hub shell did not load: {errors}; {page.content()[:500]}"
            page.locator(".fm-hub-trigger").click()
            assert page.locator(".fm-hub-drawer").get_attribute("aria-hidden") == "false"
            page.keyboard.press("Escape")
            assert page.locator(".fm-hub-drawer").get_attribute("aria-hidden") == "true"
            page.locator(".fm-hub-trigger").click()
            page.get_by_role("button", name=re.compile("Floodman RoomFlow Estimator")).click()
            assert page.locator(".fm-hub-overlay").get_attribute("aria-hidden") == "false"
            page.locator(".fm-hub-overlay-close").click()
            assert page.locator(".fm-hub-overlay").get_attribute("aria-hidden") == "true"

            page.goto(base + "/roomflow/", wait_until="domcontentloaded")
            panel = page.locator("#fm-roomflow-panel")
            panel.wait_for(state="visible")
            page.locator("#more-new-company-name").fill("Browser RoomFlow Company")
            page.locator("#btn-more-create-company").click()
            page.wait_for_function("document.querySelector('#more-company-switcher')?.value && document.querySelector('#more-company-switcher')?.selectedOptions[0]?.textContent === 'Browser RoomFlow Company'")
            assert page.evaluate("window.__legacyAccountPrompted") is False
            assert page.locator("#auth-overlay").evaluate("node => getComputedStyle(node).display") == "none"
            assert "No separate RoomFlow account is needed" in page.locator("#more-company-switcher").locator("xpath=ancestor::*[contains(@class,'checklist-room-card')][1]").inner_text()
            page.locator("#fm-rf-close-panel").click()
            assert page.locator("html").evaluate("node => node.classList.contains('fm-rf-panel-dismissed')")
            assert panel.get_attribute("aria-hidden") == "true"
            page.locator("#fm-rf-open-panel").click()
            assert panel.get_attribute("aria-hidden") == "false"
            page.keyboard.press("Escape")
            assert panel.get_attribute("aria-hidden") == "true"

            page.goto(base + "/legacy-roomflow?floodmanPanel=1", wait_until="domcontentloaded")
            page.locator("#fmrf-open").click()
            modal = page.locator("#fmrf-modal")
            modal.wait_for(state="visible")
            page.keyboard.press("Escape")
            assert modal.get_attribute("aria-hidden") == "true"
            page.locator("#fmrf-open").click()
            page.locator("#fmrf-close-icon").click()
            assert modal.get_attribute("aria-hidden") == "true"

            mobile_page = desktop.new_page()
            mobile_page.set_viewport_size({"width": 390, "height": 844})
            mobile_page.goto(base + "/office/mobile?mobile=1", wait_until="domcontentloaded")
            mobile_page.locator("[data-mobile-menu]").first.click()
            sidebar = mobile_page.locator("#fm-office-sidebar")
            assert sidebar.get_attribute("aria-hidden") == "false"
            mobile_page.keyboard.press("Escape")
            assert sidebar.get_attribute("aria-hidden") == "true"
            for path in ["/office/mobile?mobile=1", "/office/contacts", "/office/properties", "/office/estimates", "/office/invoices", "/office/roomflow"]:
                response = mobile_page.goto(base + path, wait_until="domcontentloaded")
                assert response and response.status == 200, f"mobile browser route failed: {path}"
                assert not mobile_page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"), f"mobile horizontal overflow: {path}"

            mobile_page.close()
            desktop.close()
            browser.close()
            assert not errors, f"browser page errors: {errors}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def run() -> None:
    static_overlay_contracts()
    with tempfile.TemporaryDirectory() as temp:
        os.environ["OFFICE_CONSOLE_DATA_DIR"] = str(Path(temp) / "office")
        os.environ["DOCUMENTS_PATH"] = str(Path(temp) / "documents")
        os.environ["OFFICE_CONSOLE_PUBLIC_URL"] = "http://127.0.0.1"
        os.environ["FLOODMAN_CUSTOMER_PUBLIC_URL"] = "http://127.0.0.1/customer"
        os.environ["OFFICE_SESSION_COOKIE_SECURE"] = "false"
        os.environ["INTERNAL_HMAC_KEYS"] = "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
        os.environ["AI_HMAC_KEYS"] = "ai-v1:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
        from app import main

        main.providers = FakeProviders()
        records = seed(main)
        route_smoke(main, records)
        browser_smoke(main)
    print("Floodman web routes, responsive layouts, and dismissible overlay smoke test passed")


if __name__ == "__main__":
    run()
