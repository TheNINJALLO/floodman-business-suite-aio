from __future__ import annotations

import base64
import os
import tempfile

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.mobile_api import build_mobile_router
from app.providers import ProviderClient
from app.roomflow_supabase import create_roomflow_workspace, ensure_roomflow_workspaces, select_roomflow_workspace
from app.store import OfficeStore


def build_client() -> tuple[OfficeStore, TestClient, dict[str, str], dict, str]:
    root = tempfile.mkdtemp(prefix="floodman-roomflow-capture-")
    signing = base64.b64encode(b"2" * 32).decode()
    os.environ.update(
        {
            "OFFICE_CONSOLE_DATA_DIR": root,
            "DOCUMENTS_PATH": root + "/docs",
            "FLOODMAN_MOBILE_TOKEN_SECRET": "c" * 64,
            "FLOODMAN_MOBILE_API_PUBLIC_URL": "https://example.invalid/mobile-api",
            "FLOODMAN_CUSTOMER_PUBLIC_URL": "https://example.invalid/customer",
            "FLOODMAN_PAYMENTS_ENABLED": "false",
            "AR_TIMEZONE": "America/Detroit",
            "INTERNAL_HMAC_KEYS": "v1:" + signing,
            "AI_HMAC_KEYS": "v1:" + signing,
        }
    )
    settings = Settings.from_env()
    store = OfficeStore(root)
    owner = store.create_owner("Capture Owner", "capture@example.com", "Password12345!")
    workspace = ensure_roomflow_workspaces(store, actor_id=str(owner["id"]))[0]
    job = store.create_record(
        "roomflow_jobs",
        {
            "id": "capture-job-1",
            "workspace_id": workspace["id"],
            "job_name": "Fictional Water Loss",
            "estimate_id": "estimate-preserved-1",
            "snapshot": {
                "schemaVersion": "floodman-roomflow-4.4.0",
                "rooms": [],
                "costing": {"customLineItems": [{"name": "Preserve me", "quantity": 1}]},
                "proposalId": "proposal-preserved-1",
            },
            "source": "TEST_FIXTURE",
        },
        actor_id=str(owner["id"]),
    )
    app = FastAPI()
    app.include_router(build_mobile_router(store, ProviderClient(settings), settings))
    client = TestClient(app)
    login = client.post(
        "/mobile-api/v1/auth/login",
        json={
            "email": "capture@example.com",
            "password": "Password12345!",
            "auth_source": "local",
            "device_id": "capture-api-device",
            "device_name": "Capture test device",
            "platform": "android",
            "app_version": "0.3.0-alpha12",
        },
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": "Bearer " + login.json()["access_token"]}
    return store, client, headers, workspace, str(owner["id"])


def room_payload(room_id: str = "room-1", name: str = "Basement Recreation Room") -> dict:
    return {
        "schemaVersion": 2,
        "sessionId": "capture-session-1",
        "roomId": room_id,
        "levelId": "basement",
        "name": name,
        "roomType": "basement",
        "units": "ft",
        "height": 8,
        "vertices": [
            {"id": "v1", "x": 0, "y": 0, "confidence": 0.96, "depthValidated": True, "source": "android-arcore-depth"},
            {"id": "v2", "x": 10, "y": 0, "confidence": 0.95, "depthValidated": True, "source": "android-arcore-depth"},
            {"id": "v3", "x": 10, "y": 12, "confidence": 0.94, "depthValidated": True, "source": "android-arcore-depth"},
            {"id": "v4", "x": 0, "y": 12, "confidence": 0.95, "depthValidated": True, "source": "android-arcore-depth"},
        ],
        "openings": [],
        "affectedAreas": [{"surface": "floor", "scope": "entire-surface", "percent": 100}],
        "scanMetadata": {
            "captureMode": "android-arcore-depth",
            "platform": "android",
            "pointCount": 4,
            "averageConfidence": 0.95,
            "depthValidatedPointCount": 4,
            "automaticCorrectionCount": 0,
            "manualCorrectionCount": 0,
            "verificationRequired": True,
            "rawCaptureRetained": False,
        },
    }


def run() -> None:
    store, client, headers, workspace, owner_id = build_client()
    path = "/mobile-api/v1/roomflow/jobs/capture-job-1/capture/rooms"

    unauthenticated = client.get(path)
    assert unauthenticated.status_code == 401, unauthenticated.text

    created = client.post(path, headers=headers, json={"operationId": "create-room-1", "expectedRevision": 0, "room": room_payload()})
    assert created.status_code == 200, created.text
    assert created.json()["revision"] == 1
    assert created.json()["room"]["measurements"]["floorArea"] == 120

    replayed = client.post(path, headers=headers, json={"operationId": "create-room-1", "expectedRevision": 0, "room": room_payload()})
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replayed"] is True
    assert len(store.records("roomflow_capture_rooms")) == 1
    assert len(store.records("roomflow_capture_audit")) == 1

    changed_replay = client.post(path, headers=headers, json={"operationId": "create-room-1", "expectedRevision": 0, "room": room_payload(name="Different")})
    assert changed_replay.status_code == 409, changed_replay.text

    invalid = room_payload("crossed-room")
    invalid["vertices"] = [{"x": 0, "y": 0}, {"x": 5, "y": 5}, {"x": 0, "y": 5}, {"x": 5, "y": 0}]
    rejected = client.post(path, headers=headers, json={"operationId": "invalid-room", "room": invalid})
    assert rejected.status_code == 422 and "cross" in rejected.text, rejected.text

    oversized = room_payload("oversized-room")
    oversized["reviewNotes"] = "x" * (257 * 1024)
    rejected_size = client.post(path, headers=headers, json={"operationId": "oversized-room", "room": oversized})
    assert rejected_size.status_code == 422 and "256 KB" in rejected_size.text, rejected_size.text

    raw_capture = room_payload("raw-room")
    raw_capture["depthMap"] = "not-allowed"
    rejected_raw = client.post(path, headers=headers, json={"operationId": "raw-room", "room": raw_capture})
    assert rejected_raw.status_code == 422 and "reviewed geometry" in rejected_raw.text, rejected_raw.text

    update_path = path + "/room-1"
    conflict = client.put(update_path, headers=headers, json={"operationId": "stale-update", "expectedRevision": 0, "room": room_payload(name="Reviewed Room")})
    assert conflict.status_code == 409 and "current revision is 1" in conflict.text, conflict.text
    updated = client.put(update_path, headers=headers, json={"operationId": "valid-update", "expectedRevision": 1, "room": room_payload(name="Reviewed Room")})
    assert updated.status_code == 200 and updated.json()["revision"] == 2, updated.text

    second = create_roomflow_workspace(store, name="Other Company", timezone="America/Detroit", user_id=owner_id, actor_id=owner_id)
    isolated = client.get(path, headers=headers)
    assert isolated.status_code == 404, isolated.text
    select_roomflow_workspace(store, owner_id, str(workspace["id"]), actor_id=owner_id)

    listed = client.get(path, headers=headers)
    assert listed.status_code == 200 and len(listed.json()["items"]) == 1, listed.text
    stored_job = store.record("roomflow_jobs", "capture-job-1") or {}
    assert stored_job["estimate_id"] == "estimate-preserved-1"
    assert stored_job["snapshot"]["costing"]["customLineItems"][0]["name"] == "Preserve me"
    assert stored_job["snapshot"]["proposalId"] == "proposal-preserved-1"
    assert stored_job["snapshot"]["rooms"][0]["name"] == "Reviewed Room"

    batch = client.post(
        "/mobile-api/v1/roomflow/jobs/capture-job-1/capture/operations",
        headers=headers,
        json={"operations": [{"action": "CREATE", "operationId": "batch-create", "roomId": "room-2", "expectedRevision": 0, "room": room_payload("room-2", "Laundry")}]},
    )
    assert batch.status_code == 200 and batch.json()["complete"] is True, batch.text
    batch_replay = client.post(
        "/mobile-api/v1/roomflow/jobs/capture-job-1/capture/operations",
        headers=headers,
        json={"operations": [{"action": "CREATE", "operationId": "batch-create", "roomId": "room-2", "expectedRevision": 0, "room": room_payload("room-2", "Laundry")}]},
    )
    assert batch_replay.status_code == 200 and batch_replay.json()["results"][0]["replayed"] is True, batch_replay.text
    assert len(store.records("roomflow_capture_rooms")) == 2

    deleted = client.delete(update_path + "?operation_id=delete-room-1&expected_revision=2", headers=headers)
    assert deleted.status_code == 200 and deleted.json()["deleted"] is True, deleted.text
    missing = client.get(update_path, headers=headers)
    assert missing.status_code == 404, missing.text
    assert len(store.records("roomflow_capture_audit")) == 4
    assert all(record.get("raw_capture_retained") is False for record in store.records("roomflow_capture_audit"))
    assert second["id"] != workspace["id"]

    print("PASS: authenticated RoomFlow Capture CRUD, isolation, revisions, replay, audit, and snapshot retention")


if __name__ == "__main__":
    run()
