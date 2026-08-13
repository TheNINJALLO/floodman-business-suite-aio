from __future__ import annotations

import base64
import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.mobile_api import build_mobile_router
from app.providers import ProviderClient
from app.store import OfficeStore


JPEG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAUDBAQEAwUEBAQFBQUGBwwIBwcHBw8LCwkMEQ8SEhEPERETFhwXExQaFRERGCEYGh0dHx8fExciJCIeJBweHx7/2wBDAQUFBQcGBw4ICA4eFBEUHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh4eHh7/wAARCAAkAEADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD7LooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigD//Z"

def jpeg_data_url() -> str:
    return "data:image/jpeg;base64," + JPEG_B64


def run() -> None:
    root = tempfile.mkdtemp(prefix="floodman-roomflow-native-")
    signing = base64.b64encode(b"1" * 32).decode()
    os.environ.update({
        "OFFICE_CONSOLE_DATA_DIR": root,
        "DOCUMENTS_PATH": root + "/docs",
        "FLOODMAN_MOBILE_TOKEN_SECRET": "x" * 64,
        "FLOODMAN_MOBILE_API_PUBLIC_URL": "https://example.invalid/mobile-api",
        "FLOODMAN_CUSTOMER_PUBLIC_URL": "https://example.invalid/customer",
        "FLOODMAN_PAYMENTS_ENABLED": "false",
        "AR_TIMEZONE": "America/Detroit",
        "INTERNAL_HMAC_KEYS": "v1:" + signing,
        "AI_HMAC_KEYS": "v1:" + signing,
    })
    settings = Settings.from_env()
    store = OfficeStore(root)
    store.create_owner("Josh Aldrich", "josh@floodman.com", "Password12345!")
    app = FastAPI()
    app.include_router(build_mobile_router(store, ProviderClient(settings), settings))
    client = TestClient(app)
    login = client.post("/mobile-api/v1/auth/login", json={
        "email":"josh@floodman.com", "password":"Password12345!", "auth_source":"local",
        "device_id":"roomflow-native-test", "device_name":"RoomFlow Android", "platform":"android", "app_version":"0.3.0"
    })
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    initial_bootstrap = client.get("/mobile-api/v1/roomflow/bootstrap", headers=headers)
    assert initial_bootstrap.status_code == 200, initial_bootstrap.text
    default_workspace = initial_bootstrap.json()["active_workspace"]
    assert default_workspace["name"] == "Floodman"
    assert initial_bootstrap.json()["selected_workspace_id"] == default_workspace["id"]
    payload = {
        "workspace_id": default_workspace["id"],
        "job_name": "Carter Basement",
        "customer_name": "Alex Carter",
        "customer_email": "alex@example.com",
        "customer_phone": "2315550100",
        "property_address": "1847 Pine Ridge Lane, Traverse City, MI 49686",
        "project_category": "basement-waterproofing",
        "title": "Basement Waterproofing & Water Management",
        "snapshot": {"currentJobName":"Carter Basement", "rooms":[{"id":"room-1","name":"Basement","width":20,"length":30}], "costing":{"customerName":"Alex Carter","customerEmail":"alex@example.com","customerAddress":"1847 Pine Ridge Lane, Traverse City, MI 49686"}},
        "summary": {"rooms":1,"levels":1,"measurements":4},
        "layout_data_url": jpeg_data_url(),
        "sections": [{"title":"Waterproofing","description":"Measured RoomFlow scope","lines":[{"name":"Interior perimeter drainage system","quantity":92,"unit":"LF","unit_price_cents":4500,"save_to_catalog":True}]}],
        "sync_estimate": True,
    }
    created = client.post("/mobile-api/v1/roomflow/jobs", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["job"]["snapshot"]["rooms"][0]["name"] == "Basement"
    assert body["job"]["workspace_id"] == default_workspace["id"]
    assert body["workspace"]["id"] == default_workspace["id"]
    assert body["layout_available"] is True
    assert body["estimate"]["total_cents"] == 414000
    assert body["estimate"]["deposit_cents"] == 207000
    assert body["estimate"]["recommended_project_title"]
    catalog = store.records("catalog_items")
    assert len(catalog) == 1
    assert catalog[0]["name"] == "Interior perimeter drainage system"
    assert body["estimate"]["line_items"][0]["catalog_item_id"] == catalog[0]["id"]
    job_id = body["job"]["id"]
    detail = client.get(f"/mobile-api/v1/roomflow/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["customer"]["email"] == "alex@example.com"
    bootstrap = client.get("/mobile-api/v1/roomflow/bootstrap", headers=headers)
    assert bootstrap.status_code == 200, bootstrap.text
    assert bootstrap.json()["api_version"] == "0.3.0-alpha11"
    assert bootstrap.json()["minimum_ios_version"] == "0.1.0-alpha02"
    assert bootstrap.json()["active_workspace"]["id"] == default_workspace["id"]
    assert bootstrap.json()["jobs"][0]["workspace"]["id"] == default_workspace["id"]
    assert bootstrap.json()["jobs"][0]["job"]["snapshot"]["rooms"][0]["name"] == "Basement"
    assert bootstrap.json()["jobs"][0]["layout_capture_required"] is False
    layout = client.get(f"/mobile-api/v1/roomflow/jobs/{job_id}/layout", headers=headers)
    assert layout.status_code == 200 and layout.content.startswith(b"\xff\xd8")
    payload["status"] = "READY_FOR_REVIEW"
    payload["estimate_id"] = body["estimate"]["id"]
    payload["sections"][0]["lines"][0]["quantity"] = 100
    updated = client.put(f"/mobile-api/v1/roomflow/jobs/{job_id}", headers=headers, json=payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["estimate"]["total_cents"] == 450000
    assert len(store.records("catalog_items")) == 1, "Repeated RoomFlow sync must not duplicate custom catalog items"
    print("Floodman native RoomFlow API smoke test passed")


if __name__ == "__main__":
    run()
