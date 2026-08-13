from __future__ import annotations

import base64
import hashlib
import hmac
import os
import tempfile
import time
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.mobile_api import build_mobile_router
from app.providers import ProviderClient
from app.store import OfficeStore


def run() -> None:
    root = tempfile.mkdtemp(prefix="floodman-mobile-api-")
    signing = base64.b64encode(b"1" * 32).decode()
    os.environ.update(
        {
            "OFFICE_CONSOLE_DATA_DIR": root,
            "DOCUMENTS_PATH": root + "/docs",
            "FLOODMAN_MOBILE_TOKEN_SECRET": "x" * 64,
            "FLOODMAN_MOBILE_API_PUBLIC_URL": "https://example.invalid/mobile-api",
            "FLOODMAN_PAYMENTS_ENABLED": "false",
            "AR_TIMEZONE": "America/Detroit",
            "INTERNAL_HMAC_KEYS": "v1:" + signing,
            "AI_HMAC_KEYS": "v1:" + signing,
        }
    )
    settings = Settings.from_env()
    store = OfficeStore(root)
    store.create_owner("Josh Aldrich", "josh@floodman.com", "Password12345!")
    app = FastAPI()
    app.include_router(build_mobile_router(store, ProviderClient(settings), settings))
    client = TestClient(app)

    health = client.get("/mobile-api/v1/health")
    assert health.status_code == 200, health.text
    assert health.json()["api_version"] == "0.3.0-alpha11"
    assert health.json()["minimum_android_version"] == "0.3.0-alpha11"
    assert health.json()["minimum_ios_version"] == "0.1.0-alpha02"
    assert "roomflow.supabase-import.v1" in health.json()["capabilities"]
    assert "roomflow.workspaces.v1" in health.json()["capabilities"]
    config = client.get("/mobile-api/v1/config")
    assert config.status_code == 200, config.text
    assert config.json()["minimum_ios_version"] == "0.1.0-alpha02"
    assert config.json()["roomflow_import"]["enabled"] is True

    login = client.post(
        "/mobile-api/v1/auth/login",
        json={
            "email": "josh@floodman.com",
            "password": "Password12345!",
            "auth_source": "local",
            "device_id": "android-test-123456",
            "device_name": "Test Android",
            "platform": "android",
            "app_version": "0.1.0",
        },
    )
    assert login.status_code == 200, login.text
    session = login.json()
    headers = {"Authorization": "Bearer " + session["access_token"]}

    customer = client.post(
        "/mobile-api/v1/customers",
        headers=headers,
        json={"first_name": "Alex", "last_name": "Carter", "email": "alex@example.com", "phone": "2315550100"},
    )
    assert customer.status_code == 200, customer.text
    customer_id = customer.json()["id"]

    property_response = client.post(
        "/mobile-api/v1/properties",
        headers=headers,
        json={
            "contact_id": customer_id,
            "property_name": "Home",
            "service_street": "1847 Pine Ridge Lane",
            "service_city": "Traverse City",
            "service_state": "MI",
            "service_postal_code": "49686",
        },
    )
    assert property_response.status_code == 200, property_response.text
    property_id = property_response.json()["id"]

    estimate = client.post(
        "/mobile-api/v1/estimates",
        headers=headers,
        json={
            "contact_id": customer_id,
            "property_id": property_id,
            "title": "Waterproofing test",
            "project_summary": "Test project",
            "deposit_type": "PERCENT",
            "deposit_percent": 50,
            "deposit_due_stage": "IMMEDIATELY",
            "sections": [
                {
                    "title": "Waterproofing",
                    "lines": [
                        {
                            "name": "Drain system",
                            "quantity": 2,
                            "unit": "each",
                            "unit_price_cents": 50_000,
                            "save_to_catalog": True,
                        }
                    ],
                }
            ],
        },
    )
    assert estimate.status_code == 200, estimate.text
    estimate_data = estimate.json()
    assert estimate_data["total_cents"] == 100_000
    assert estimate_data["deposit_cents"] == 50_000

    payment = client.post(
        "/mobile-api/v1/payments/manual",
        headers=headers,
        json={
            "target_kind": "estimate",
            "target_id": estimate_data["id"],
            "amount_cents": 10_000,
            "method": "CASH",
            "reference": "R-1",
        },
    )
    assert payment.status_code == 200, payment.text

    refresh_token = session["refresh_token"]
    device_id = session["device"]["id"]
    timestamp = int(time.time())
    nonce = str(uuid.uuid4())
    device_secret = session["device_secret"]
    raw_secret = base64.urlsafe_b64decode(device_secret + "=" * (-len(device_secret) % 4))
    canonical = f"{device_id}.{timestamp}.{nonce}.{hashlib.sha256(refresh_token.encode()).hexdigest()}"
    proof = base64.urlsafe_b64encode(hmac.new(raw_secret, canonical.encode(), hashlib.sha256).digest()).decode().rstrip("=")
    refreshed = client.post(
        "/mobile-api/v1/auth/refresh",
        json={
            "refresh_token": refresh_token,
            "device_id": device_id,
            "timestamp": timestamp,
            "nonce": nonce,
            "proof": proof,
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    print("Floodman mobile API smoke test passed")


if __name__ == "__main__":
    run()
