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

    print("Floodman ERP, Office, and RoomFlow unified login smoke test passed")


if __name__ == "__main__":
    run()
