from __future__ import annotations

import json
import os
import tempfile
import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient


def run() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "pwa" / "manifest.webmanifest").read_text(encoding="utf-8"))
    assert manifest["start_url"].startswith("/workspace?source=pwa")
    assert (root / "pwa" / "workspace.html").is_file()
    assert (root / "pwa" / "workspace-mode.css").is_file()
    assert (root / "pwa" / "erp.html").is_file()
    erp_launcher = (root / "pwa" / "erp.html").read_text(encoding="utf-8")
    assert "/api/auth/authenticated" in erp_launcher
    assert "authenticated(payload)" in erp_launcher
    assert "pages/dashboard" in erp_launcher
    assert "auth/login" in erp_launcher
    assert "server down" not in erp_launcher.lower()

    workspace = (root / "pwa" / "workspace.html").read_text(encoding="utf-8")
    assert "/office/desktop?desktop=1" in workspace
    assert "/office/mobile?mobile=1" in workspace
    assert "pointer: coarse" not in workspace
    assert "true desktop workspace" in workspace.lower()
    assert "serviceWorker.register" in workspace
    assert "Refreshing Floodman" in workspace

    workspace_css = (root / "pwa" / "workspace-mode.css").read_text(encoding="utf-8")
    assert 'html[data-workspace="desktop"] .shell' in workspace_css
    assert 'html[data-workspace="desktop"] .mobile-bottom-nav' in workspace_css
    assert 'html[data-workspace="mobile"] .mobile-bottom-nav' in workspace_css
    assert 'html[data-workspace="mobile"] .office-sidebar' in workspace_css

    hub = (root / "hub" / "hub.js").read_text(encoding="utf-8")
    assert "Desktop Operations" in hub
    assert "Mobile Operations" in hub
    assert "pointer: coarse" not in hub
    assert "isPhoneOrTablet" in hub
    assert "${hubOrigin}/#/pages/" not in hub
    assert "${hubOrigin}/index.html?desktop=1#/pages/" in hub

    nginx = (root / "aio" / "nginx.conf.template").read_text(encoding="utf-8")
    assert "location = / {" in nginx
    assert "return 302 /workspace?source=root&workspace=auto;" in nginx
    assert "absolute_redirect off;" in nginx
    assert "location = /workspace" in nginx
    assert "location = /full-erp" in nginx
    assert "location = /floodman-workspace.css" in nginx
    assert "location = /office-health/live" in nginx
    assert "location = /floodman-boot-guard.js" in nginx
    assert "location = /floodman-status.html" in nginx
    assert "/floodman-boot-guard.js?release=${HUB_RELEASE}" in nginx
    assert "http://0.0.0.0:${SERVER_PORT}" in nginx
    assert "proxy_pass http://127.0.0.1:8700/health/live" in nginx
    assert "/home/container/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/" in nginx
    assert "/home/container/runtime/floodman-v4.1.0/" not in nginx

    pwa_js = (root / "pwa" / "floodman-pwa.js").read_text(encoding="utf-8")
    assert "/office-health/live" in pwa_js
    assert "navigator.onLine" not in pwa_js
    service_worker = (root / "pwa" / "floodman-sw.js").read_text(encoding="utf-8")
    assert "dynamicOfficeRoute ? 30000 : 15000" in service_worker
    assert "/floodman-starting.html" in service_worker

    ui = (root / "office-console" / "app" / "ui.py").read_text(encoding="utf-8")
    assert "WORKSPACE_HEAD" in ui
    assert "document.documentElement.dataset.workspace=mode" in ui
    assert "WORKSPACE_CSS" in ui
    assert "<style>{BASE_CSS}</style>{WORKSPACE_CSS}" in ui

    temp = tempfile.mkdtemp(prefix="floodman-dual-workspace-")
    os.environ.update(
        {
            "OFFICE_CONSOLE_DATA_DIR": temp,
            "DOCUMENTS_PATH": temp + "/documents",
            "OFFICE_AUTH_ENABLED": "false",
            "FLOODMAN_MOBILE_TOKEN_SECRET": "x" * 64,
            "FLOODMAN_RELEASE": "pterodactyl-mobile-v4.6.7",
            "GAUZY_FULL_SYNC_ENABLED": "false",
            "FLOODMAN_PAYMENTS_ENABLED": "false",
            "INTERNAL_HMAC_KEYS": "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
            "AI_HMAC_KEYS": "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
        }
    )
    from app import main as office_main

    office_main.store.create_owner("Josh Aldrich", "owner@floodman.test", "Password12345!")
    client = TestClient(office_main.app)

    async def slow_provider_state():
        await asyncio.sleep(10)
        return {}

    office_main.providers.lab_state = slow_provider_state
    started = time.monotonic()
    desktop = client.get("/office/desktop?desktop=1")
    elapsed = time.monotonic() - started
    assert elapsed < 6.0, f"Desktop route blocked for {elapsed:.2f}s"
    assert desktop.status_code == 200, desktop.text
    assert "DESKTOP OPERATIONS WORKSPACE" in desktop.text
    assert "Open mobile workspace" in desktop.text
    assert "floodman-workspace.css?release=4.6.7" in desktop.text
    assert "document.documentElement.dataset.workspace=mode" in desktop.text

    mobile = client.get("/office/mobile?mobile=1")
    assert mobile.status_code == 200, mobile.text
    assert "PHONE & TABLET WORKSPACE" in mobile.text
    assert "Open desktop workspace" in mobile.text

    shortcut = client.get("/desktop", follow_redirects=False)
    assert shortcut.status_code == 307
    assert shortcut.headers["location"] == "/office/desktop?desktop=1"

    print("Floodman true desktop/mobile workspace smoke test passed")


if __name__ == "__main__":
    run()
