import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.providers import ProviderClient


ROOT = Path(__file__).resolve().parents[2]


def test_hub_proxy_injects_floodman_assets_and_keeps_native_gauzy() -> None:
    nginx = (ROOT / "gauzy-hub" / "nginx.conf").read_text(encoding="utf-8")
    javascript = (ROOT / "gauzy-hub" / "hub.js").read_text(encoding="utf-8")
    assert "sub_filter '</body>'" in nginx
    assert "gauzy-webapp:4200" in nginx
    assert "gauzy-api:3000" in nginx
    for label in (
        "RoomFlow Estimator",
        "Documents & Signatures",
        "Receivables",
        "Customer Messages",
        "Competitor Intelligence",
        "Members & Access",
    ):
        assert label in javascript
    assert "The full Floodman ERP remains available underneath" in javascript


def test_office_property_becomes_native_gauzy_project() -> None:
    provider = ProviderClient.__new__(ProviderClient)
    provider.settings = SimpleNamespace()
    captured = {}

    async def request(method, path, payload=None, **kwargs):
        captured.update({"method": method, "path": path, "payload": payload})
        return {"id": "project-1"}

    provider._gauzy_request = request
    result = asyncio.run(
        provider.full_gauzy_create_project(
            {
                "id": "property-1",
                "name": "Home",
                "service_street": "100 Main Street",
                "service_city": "Detroit",
                "service_state": "MI",
                "service_postal_code": "48201",
                "notes": "Basement waterproofing",
            },
            {"tenant_id": "tenant-1", "organization_id": "org-1"},
            contact_id="contact-1",
        )
    )
    assert result["id"] == "project-1"
    assert captured["path"] == "/organization-projects/"
    assert captured["payload"]["organizationContactId"] == "contact-1"
    assert captured["payload"]["name"] == "Home"
    assert captured["payload"]["code"].startswith("FM-")


def test_gauzy_browser_api_base_uses_origin_root_once() -> None:
    compose_path = ROOT / "docker-compose.windows.yml"
    if not compose_path.is_file():
        pytest.skip("Windows Compose test is not applicable to the Pterodactyl AIO package")
    compose = compose_path.read_text(encoding="utf-8")
    gauzy_env = (ROOT / "gauzy" / ".env.full.compose").read_text(encoding="utf-8")
    assert "API_BASE_URL: ${GAUZY_PUBLIC_URL:-http://localhost:9000}\n" in compose
    assert "CLIENT_BASE_URL: ${GAUZY_PUBLIC_URL:-http://localhost:9000}\n" in compose
    assert "API_BASE_URL=http://localhost:9000\n" in gauzy_env
    assert "API_BASE_URL: http://localhost:9000/api" not in compose
    assert "API_BASE_URL=http://localhost:9000/api" not in gauzy_env
    assert "location /api/" in (ROOT / "gauzy-hub" / "nginx.conf").read_text(encoding="utf-8")


def test_floodman_white_label_assets_are_served_and_injected() -> None:
    nginx = (ROOT / "gauzy-hub" / "nginx.conf").read_text(encoding="utf-8")
    javascript = (ROOT / "gauzy-hub" / "hub.js").read_text(encoding="utf-8")
    gauzy_env = (ROOT / "gauzy" / ".env.full.compose").read_text(encoding="utf-8")
    assert (ROOT / "gauzy-hub" / "brand" / "floodman-mark.svg").is_file()
    assert (ROOT / "gauzy-hub" / "brand" / "floodman-wordmark.svg").is_file()
    assert "location ^~ /floodman-brand/" in nginx
    assert "Floodman Operations" in javascript
    assert "applyFloodmanBranding" in javascript
    assert "PLATFORM_LOGO=http://localhost:9000/floodman-brand/floodman-wordmark.svg" in gauzy_env
    assert "NO_INTERNET_LOGO=http://localhost:9000/floodman-brand/floodman-wordmark.svg" in gauzy_env


def test_hub_runtime_assets_are_cache_busted_after_environment_rewrite() -> None:
    nginx = (ROOT / "gauzy-hub" / "nginx.conf").read_text(encoding="utf-8")
    assert "fmhub=3.0.0" in nginx
    assert 'Cache-Control "no-store, no-cache, must-revalidate, max-age=0"' in nginx


def test_remote_access_keeps_windows_ports_loopback_only() -> None:
    compose_path = ROOT / "docker-compose.windows.yml"
    if not compose_path.is_file():
        pytest.skip("Windows remote-access test is not applicable to the Pterodactyl AIO package")
    compose = compose_path.read_text(encoding="utf-8")
    env = (ROOT / ".env.windows.example").read_text(encoding="utf-8")
    hub_config = (ROOT / "gauzy-hub" / "hub-config.js.template").read_text(encoding="utf-8")
    for port in (9000, 9001, 9002, 9003, 9004):
        assert f'127.0.0.1:{port}:' in compose
    assert "REMOTE_ACCESS_ENABLED=false" in env
    assert "HUB_REMOTE_ACCESS_ENABLED=false" in env
    assert "window.location.origin" in hub_config
    assert (ROOT / "windows" / "Start-FloodmanTailscaleAccess.ps1").is_file()
    assert (ROOT / "windows" / "Stop-FloodmanTailscaleAccess.ps1").is_file()
    assert (ROOT / "windows" / "Test-FloodmanRemoteAccess.ps1").is_file()
