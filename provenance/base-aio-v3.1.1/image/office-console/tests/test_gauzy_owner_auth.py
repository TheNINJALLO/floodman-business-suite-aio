from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx

from app import providers as providers_module
from app.providers import ProviderClient


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.request = httpx.Request("POST", "http://gauzy-api:3000/api/auth/login")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json):
        assert url.endswith("/auth/login")
        assert json == {"email": "owner@example.com", "password": "OwnerPassword123!"}
        return httpx.Response(
            200,
            request=self.request,
            json={
                "token": "access-token",
                # Current Gauzy builds can return a minimal user payload here;
                # the configured installation owner must still be recognized.
                "user": {
                    "id": "gauzy-owner-id",
                    "email": "owner@example.com",
                    "firstName": "Primary",
                    "lastName": "Owner",
                },
            },
        )

    async def get(self, url, headers=None, params=None):
        # Simulate a Gauzy build where /user/me is unavailable or requires a
        # different context. Authentication must still use the verified login.
        return httpx.Response(404, request=httpx.Request("GET", url), json={"message": "not found"})


def test_configured_gauzy_owner_is_admin_when_role_relation_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(providers_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = ProviderClient.__new__(ProviderClient)
    provider.settings = SimpleNamespace(
        gauzy_base_url="http://gauzy-api:3000/api",
        gauzy_admin_email="owner@example.com",
        gauzy_tenant_id="AUTO",
        gauzy_organization_id="AUTO",
    )

    identity = asyncio.run(provider.authenticate_gauzy_member("OWNER@example.com", "OwnerPassword123!"))

    assert identity["email"] == "owner@example.com"
    assert identity["is_gauzy_admin"] is True
    assert identity["suggested_office_role"] == "ADMIN"
    assert identity["gauzy_role"] == "USER"
