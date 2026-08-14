from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


class FakeErpIdentity:
    def __init__(self) -> None:
        self.passwords: list[str] = []
        self.tokens: list[str] = []

    @staticmethod
    def identity(email: str = "owner@example.test") -> dict[str, Any]:
        return {
            "email": email,
            "name": "Unified Login Owner",
            "gauzy_user_id": "gauzy-unified-owner",
            "gauzy_employee_id": "gauzy-unified-employee",
            "gauzy_role": "ADMIN",
            "tenant_id": "gauzy-tenant",
            "organization_id": "gauzy-organization",
            "suggested_office_role": "ADMIN",
            "is_gauzy_admin": True,
        }

    async def authenticate_gauzy_login(
        self, email: str, password: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        assert email == "owner@example.test"
        assert password == "ERP-Password-Only-In-Memory!"
        self.passwords.append(password)
        return self.identity(email), {
            "token": "eyJfakeheader123.fakepayload123.fakesignature123",
            "user": {"id": "gauzy-unified-owner", "email": email},
        }

    async def authenticate_gauzy_session(self, token: str) -> dict[str, Any]:
        assert token == "eyJexistingheader.existingpayload.existingsignature"
        self.tokens.append(token)
        return self.identity()


def run() -> None:
    with tempfile.TemporaryDirectory(prefix="floodman-unified-login-") as temp:
        root = Path(temp)
        os.environ.update(
            {
                "OFFICE_CONSOLE_DATA_DIR": str(root / "office"),
                "DOCUMENTS_PATH": str(root / "documents"),
                "OFFICE_AUTH_ENABLED": "true",
                "OFFICE_SESSION_COOKIE_SECURE": "false",
                "FLOODMAN_MOBILE_TOKEN_SECRET": "u" * 64,
                "INTERNAL_HMAC_KEYS": "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=",
                "AI_HMAC_KEYS": "v1:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI=",
                "GAUZY_FULL_SYNC_ENABLED": "false",
                "FLOODMAN_PAYMENTS_ENABLED": "false",
            }
        )
        from app import main

        assert main._safe_login_target("/\\outside.invalid") == "/office"
        main.store.create_owner("Unified Login Owner", "owner@example.test", "Local-Recovery-Password!")
        fake = FakeErpIdentity()
        main.providers = fake

        anonymous = TestClient(main.app, follow_redirects=False)
        assert anonymous.get("/login/status").json() == {"authenticated": False}
        roomflow_denied = anonymous.get("/office/api/roomflow/auth-check")
        assert roomflow_denied.status_code == 401
        gateway = anonymous.get("/login?next=/roomflow/")
        assert gateway.status_code == 200
        assert "One login for ERP, Office, and RoomFlow" in gateway.text
        assert "floodmanLoginNext" in gateway.text
        assert "/full-erp?target=login" in gateway.text

        erp_browser = TestClient(main.app, follow_redirects=False)
        login = erp_browser.post(
            "/office/api/erp/login",
            json={"email": "owner@example.test", "password": "ERP-Password-Only-In-Memory!"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["token"].startswith("eyJfakeheader")
        assert "floodman_session" in erp_browser.cookies
        assert erp_browser.get("/login/status").json() == {"authenticated": True}
        assert erp_browser.get("/office/api/roomflow/auth-check").status_code == 204
        linked = main.store.user_by_email("owner@example.test") or {}
        assert linked.get("gauzy_user_id") == "gauzy-unified-owner"
        assert linked.get("auth_source") == "LOCAL_AND_GAUZY"
        roomflow_context = erp_browser.get("/office/api/roomflow/context")
        assert roomflow_context.status_code == 200, roomflow_context.text
        default_workspace = roomflow_context.json()["active_workspace"]
        assert default_workspace["name"] == "Floodman"
        assert roomflow_context.json()["selected_workspace_id"] == default_workspace["id"]

        created_workspace = erp_browser.post(
            "/office/api/roomflow/workspaces",
            json={"name": "Unified ERP Company", "timezone": "America/Detroit"},
        )
        assert created_workspace.status_code == 200, created_workspace.text
        company = created_workspace.json()["active_workspace"]
        assert company["name"] == "Unified ERP Company"
        assert created_workspace.json()["selected_workspace_id"] == company["id"]

        main.store.create_record("roomflow_jobs", {
            "job_name": "Default Company Job", "workspace_id": default_workspace["id"], "source": "ROOMFLOW",
        }, actor_id=str(linked.get("id") or "owner"))
        main.store.create_record("roomflow_jobs", {
            "job_name": "Unified Company Job", "workspace_id": company["id"], "source": "ROOMFLOW",
        }, actor_id=str(linked.get("id") or "owner"))
        company_jobs = erp_browser.get("/office/api/roomflow/jobs")
        assert company_jobs.status_code == 200, company_jobs.text
        assert [item["job_name"] for item in company_jobs.json()["items"]] == ["Unified Company Job"]
        shared_sync_payload = {
            "roomflow_job_id": "shared-browser-job",
            "roomflow_estimate_id": "shared-browser-estimate",
            "job_name": "Shared Browser Estimate ID",
            "customer": {"name": "Browser Test Customer", "email": "browser-customer@example.test"},
            "property": {"street": "100 Test Street", "city": "Detroit", "state": "MI", "postal_code": "48201"},
            "estimate": {"title": "Browser RoomFlow Scope", "lines": [{"name": "Measured service", "quantity": 2, "unit": "each", "unit_price_cents": 12500}]},
            "roomflow_snapshot": {"rooms": [], "levels": []},
        }
        company_synchronized = erp_browser.post(
            "/office/api/roomflow/sync",
            json={**shared_sync_payload, "workspace_id": company["id"]},
        )
        assert company_synchronized.status_code == 200, company_synchronized.text
        assert company_synchronized.json()["workspace_id"] == company["id"]

        selected_default = erp_browser.post(f"/office/api/roomflow/workspaces/{default_workspace['id']}/select", json={})
        assert selected_default.status_code == 200, selected_default.text
        assert selected_default.json()["active_workspace"]["id"] == default_workspace["id"]
        default_jobs = erp_browser.get("/office/api/roomflow/jobs")
        assert [item["job_name"] for item in default_jobs.json()["items"]] == ["Default Company Job"]
        synchronized = erp_browser.post(
            "/office/api/roomflow/sync",
            json={**shared_sync_payload, "workspace_id": default_workspace["id"]},
        )
        assert synchronized.status_code == 200, synchronized.text
        assert synchronized.json()["contact_id"] != company_synchronized.json()["contact_id"]
        assert synchronized.json()["property_id"] != company_synchronized.json()["property_id"]
        assert synchronized.json()["estimate_id"] != company_synchronized.json()["estimate_id"]
        assert synchronized.json()["roomflow_job"]["id"] != company_synchronized.json()["roomflow_job"]["id"]
        assert synchronized.json()["workspace_id"] == default_workspace["id"]
        assert synchronized.json()["roomflow_job"]["workspace_id"] == default_workspace["id"]
        assert synchronized.json()["roomflow_job"]["snapshot"]["workspaceId"] == default_workspace["id"]
        assert main.store.record("estimates", synchronized.json()["estimate_id"])["workspace_id"] == default_workspace["id"]
        existing_erp_browser = TestClient(main.app, follow_redirects=False)
        exchanged = existing_erp_browser.post(
            "/login/erp-session?next=https://outside.invalid",
            headers={"Authorization": "Bearer eyJexistingheader.existingpayload.existingsignature"},
        )
        assert exchanged.status_code == 200, exchanged.text
        assert exchanged.json() == {"authenticated": True, "next": "/office"}
        assert "floodman_session" in existing_erp_browser.cookies
        assert "existingheader" not in exchanged.text
        assert fake.tokens == ["eyJexistingheader.existingpayload.existingsignature"]

        persisted = json.dumps(main.store.snapshot())
        assert "ERP-Password-Only-In-Memory!" not in persisted
        assert "eyJfakeheader123" not in persisted
        assert "eyJexistingheader" not in persisted

        nginx = (Path(__file__).resolve().parents[1] / "aio" / "nginx.conf.template").read_text(encoding="utf-8")
        assert "location = /api/auth/login" in nginx
        assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in nginx
        assert "error_page 401 =302 /login?next=/roomflow/" in nginx
        panel = (Path(__file__).resolve().parents[1] / "roomflow" / "floodman-panel.js").read_text(encoding="utf-8")
        assert "No separate RoomFlow account is required" in panel
        assert "authOverlay.style.display = 'none'" in panel
        assert "`${API}/workspaces`" in panel and "changeWorkspace" in panel

    print("Floodman ERP, Office, and RoomFlow unified login smoke test passed")


if __name__ == "__main__":
    run()
