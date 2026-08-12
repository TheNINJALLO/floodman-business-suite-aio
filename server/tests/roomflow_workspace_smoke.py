from __future__ import annotations

import base64
import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.mobile_api import build_mobile_router
from app.providers import ProviderClient
from app.roomflow_supabase import ensure_roomflow_workspaces
from app.store import OfficeStore


def build_client() -> tuple[OfficeStore, TestClient, dict[str, str], str]:
    root = tempfile.mkdtemp(prefix="floodman-roomflow-workspaces-")
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
    owner = store.create_owner("Josh Aldrich", "josh@floodman.com", "Password12345!")
    app = FastAPI()
    app.include_router(build_mobile_router(store, ProviderClient(settings), settings))
    client = TestClient(app)
    login = client.post("/mobile-api/v1/auth/login", json={
        "email": "josh@floodman.com",
        "password": "Password12345!",
        "auth_source": "local",
        "device_id": "roomflow-workspace-test",
        "device_name": "RoomFlow Android",
        "platform": "android",
        "app_version": "0.3.0-alpha11",
    })
    assert login.status_code == 200, login.text
    return store, client, {"Authorization": "Bearer " + login.json()["access_token"]}, str(owner["id"])


def run() -> None:
    store, client, headers, owner_id = build_client()

    first = client.get("/mobile-api/v1/roomflow/bootstrap", headers=headers)
    assert first.status_code == 200, first.text
    default_workspace = first.json()["active_workspace"]
    assert default_workspace["name"] == "Floodman"
    assert default_workspace["is_default"] is True

    created = client.post(
        "/mobile-api/v1/roomflow/workspaces",
        headers=headers,
        json={"name": "Floodman Restoration North", "timezone": "America/Detroit"},
    )
    assert created.status_code == 200, created.text
    second_workspace = created.json()["workspace"]
    assert created.json()["bootstrap"]["selected_workspace_id"] == second_workspace["id"]

    saved = client.post("/mobile-api/v1/roomflow/jobs", headers=headers, json={
        "workspace_id": second_workspace["id"],
        "job_name": "North Workspace Inspection",
        "customer_name": "Morgan Carter",
        "property_address": "55 North Street, Traverse City, MI 49684",
        "project_category": "inspection-and-testing",
        "title": "Inspection",
        "snapshot": {"rooms": [], "costing": {"customerName": "Morgan Carter"}},
        "summary": {"rooms": 0},
        "sections": [],
        "sync_estimate": False,
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["job"]["workspace_id"] == second_workspace["id"]

    selected_default = client.post(
        f"/mobile-api/v1/roomflow/workspaces/{default_workspace['id']}/select",
        headers=headers,
        json={},
    )
    assert selected_default.status_code == 200, selected_default.text
    assert selected_default.json()["bootstrap"]["jobs"] == []

    selected_second = client.post(
        f"/mobile-api/v1/roomflow/workspaces/{second_workspace['id']}/select",
        headers=headers,
        json={},
    )
    assert selected_second.status_code == 200, selected_second.text
    assert len(selected_second.json()["bootstrap"]["jobs"]) == 1
    assert selected_second.json()["bootstrap"]["jobs"][0]["job"]["job_name"] == "North Workspace Inspection"

    # Simulate records left by v4.6.2: imported organization metadata exists,
    # but no explicit workspace row or workspace_id exists yet.
    legacy_root = tempfile.mkdtemp(prefix="floodman-roomflow-workspace-recovery-")
    legacy = OfficeStore(legacy_root)
    source_org = "77777777-7777-4777-8777-777777777777"
    contact = legacy.create_record("contacts", {
        "name": "Legacy Customer",
        "roomflow_organization_id": source_org,
        "roomflow_organization_name": "Original Supabase Company",
        "source": "ROOMFLOW_SUPABASE_IMPORT",
    }, actor_id="owner")
    prop = legacy.create_record("properties", {
        "contact_id": contact["id"],
        "full_address": "100 Legacy Road",
        "roomflow_organization_id": source_org,
        "source": "ROOMFLOW_SUPABASE_IMPORT",
    }, actor_id="owner")
    job = legacy.create_record("roomflow_jobs", {
        "name": "Legacy RoomFlow Job",
        "contact_id": contact["id"],
        "property_id": prop["id"],
        "roomflow_organization_id": source_org,
        "roomflow_organization_name": "Original Supabase Company",
        "source": "ROOMFLOW_SUPABASE_IMPORT",
    }, actor_id="owner")
    estimate = legacy.create_record("estimates", {
        "title": "Legacy Estimate",
        "roomflow_job_id": job["id"],
        "source": "ROOMFLOW_SUPABASE_IMPORT",
    }, actor_id="owner")
    recovered = ensure_roomflow_workspaces(legacy, actor_id="owner")
    assert len(recovered) == 1
    assert recovered[0]["name"] == "Original Supabase Company"
    recovered_id = recovered[0]["id"]
    assert legacy.record("roomflow_jobs", job["id"])["workspace_id"] == recovered_id
    assert legacy.record("contacts", contact["id"])["workspace_id"] == recovered_id
    assert legacy.record("properties", prop["id"])["workspace_id"] == recovered_id
    assert legacy.record("estimates", estimate["id"])["workspace_id"] == recovered_id

    print("Floodman RoomFlow workspace smoke test passed")


if __name__ == "__main__":
    run()
