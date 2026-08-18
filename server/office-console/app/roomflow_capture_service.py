from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Mapping

from .roomflow_capture import CaptureValidationError, migrate_capture_room
from .store import CaptureOperationConflict, CaptureOperationNotFound, OfficeStore


MAX_CAPTURE_PAYLOAD_BYTES = 256 * 1024
MAX_BATCH_OPERATIONS = 50
FORBIDDEN_RAW_KEYS = {
    "cameraFrame", "cameraFrames", "cameraImage", "depthMap", "depthMaps",
    "imageData", "pointCloud", "rawCapture", "rawDepth", "video",
}


class RoomFlowCaptureService:
    def __init__(self, store: OfficeStore) -> None:
        self.store = store

    @staticmethod
    def _encoded(value: Any) -> bytes:
        try:
            encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise CaptureValidationError("capture data must be valid JSON") from exc
        if len(encoded) > MAX_CAPTURE_PAYLOAD_BYTES:
            raise CaptureValidationError("capture payload exceeds the 256 KB limit")
        return encoded

    @staticmethod
    def _reject_raw_capture(value: Any, path: str = "capture") -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key) in FORBIDDEN_RAW_KEYS:
                    raise CaptureValidationError(f"{path}.{key} cannot be stored; submit reviewed geometry only")
                RoomFlowCaptureService._reject_raw_capture(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                RoomFlowCaptureService._reject_raw_capture(nested, f"{path}[{index}]")

    def _job(self, workspace_id: str, job_id: str) -> dict[str, Any]:
        job = self.store.record("roomflow_jobs", job_id)
        if not job or str(job.get("workspace_id") or "") != workspace_id:
            raise CaptureOperationNotFound("RoomFlow job not found")
        return job

    def list_rooms(self, *, workspace_id: str, job_id: str) -> list[dict[str, Any]]:
        self._job(workspace_id, job_id)
        records = [
            record
            for record in self.store.records("roomflow_capture_rooms")
            if str(record.get("workspace_id") or "") == workspace_id
            and str(record.get("job_id") or "") == job_id
            and not record.get("deleted_at")
        ]
        records.sort(key=lambda value: (str(value.get("created_at") or ""), str(value.get("id") or "")))
        return [self.public_record(record) for record in records]

    def get_room(self, *, workspace_id: str, job_id: str, room_id: str) -> dict[str, Any]:
        self._job(workspace_id, job_id)
        record = self.store.record("roomflow_capture_rooms", room_id)
        if (
            not record
            or record.get("deleted_at")
            or str(record.get("workspace_id") or "") != workspace_id
            or str(record.get("job_id") or "") != job_id
        ):
            raise CaptureOperationNotFound("Captured room not found")
        return self.public_record(record)

    @staticmethod
    def public_record(record: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "room": deepcopy(record.get("room")),
            "revision": int(record.get("revision") or 0),
            "createdAt": record.get("created_at"),
            "updatedAt": record.get("updated_at"),
        }

    def apply(
        self,
        *,
        action: str,
        operation_id: str,
        workspace_id: str,
        job_id: str,
        actor_id: str,
        room_id: str = "",
        expected_revision: int = 0,
        room: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().upper()
        operation_id = str(operation_id or "").strip()
        room_id = str(room_id or (room or {}).get("roomId") or (room or {}).get("id") or "").strip()
        if normalized_action not in {"CREATE", "UPDATE", "DELETE"}:
            raise CaptureValidationError("capture action must be CREATE, UPDATE, or DELETE")
        if not operation_id or len(operation_id) > 128:
            raise CaptureValidationError("operationId is required and must be at most 128 characters")
        if not room_id or len(room_id) > 128:
            raise CaptureValidationError("roomId is required and must be at most 128 characters")
        self._job(workspace_id, job_id)

        normalized_room: dict[str, Any] | None = None
        if normalized_action != "DELETE":
            if not isinstance(room, Mapping):
                raise CaptureValidationError("room is required")
            self._reject_raw_capture(room)
            supplied_workspace = str(room.get("workspaceId") or "")
            supplied_job = str(room.get("jobId") or "")
            supplied_room = str(room.get("roomId") or room.get("id") or "")
            if supplied_workspace and supplied_workspace != workspace_id:
                raise CaptureValidationError("capture workspace does not match the active Floodman company")
            if supplied_job and supplied_job != job_id:
                raise CaptureValidationError("capture job does not match the active Floodman job")
            if supplied_room and supplied_room != room_id:
                raise CaptureValidationError("capture room ID does not match the requested room")
            normalized_room = migrate_capture_room({**deepcopy(dict(room)), "workspaceId": workspace_id, "jobId": job_id, "roomId": room_id, "id": room_id})
            if not normalized_room["name"].strip() or len(normalized_room["name"]) > 160:
                raise CaptureValidationError("room name is required and must be at most 160 characters")
            self._encoded(normalized_room)

        canonical = {
            "action": normalized_action,
            "workspaceId": workspace_id,
            "jobId": job_id,
            "roomId": room_id,
            "expectedRevision": int(expected_revision),
            "room": normalized_room,
        }
        request_hash = hashlib.sha256(self._encoded(canonical)).hexdigest()
        return self.store.commit_roomflow_capture_operation(
            operation_id=operation_id,
            request_hash=request_hash,
            action=normalized_action,
            workspace_id=workspace_id,
            job_id=job_id,
            room_id=room_id,
            room=normalized_room,
            expected_revision=int(expected_revision),
            actor_id=actor_id,
        )

    def apply_batch(
        self,
        *,
        workspace_id: str,
        job_id: str,
        actor_id: str,
        operations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not isinstance(operations, list) or not operations:
            raise CaptureValidationError("operations must contain at least one capture operation")
        if len(operations) > MAX_BATCH_OPERATIONS:
            raise CaptureValidationError(f"no more than {MAX_BATCH_OPERATIONS} capture operations may be replayed at once")
        results: list[dict[str, Any]] = []
        for value in operations:
            try:
                applied = self.apply(
                    action=str(value.get("action") or ""),
                    operation_id=str(value.get("operationId") or ""),
                    workspace_id=workspace_id,
                    job_id=job_id,
                    actor_id=actor_id,
                    room_id=str(value.get("roomId") or ""),
                    expected_revision=int(value.get("expectedRevision") or 0),
                    room=value.get("room") if isinstance(value.get("room"), Mapping) else None,
                )
                results.append({"ok": True, **applied})
            except CaptureOperationConflict as exc:
                results.append({"ok": False, "operationId": str(value.get("operationId") or ""), "code": "REVISION_CONFLICT", "message": str(exc)})
                break
            except CaptureOperationNotFound as exc:
                results.append({"ok": False, "operationId": str(value.get("operationId") or ""), "code": "NOT_FOUND", "message": str(exc).strip("'")})
                break
            except (CaptureValidationError, ValueError, TypeError) as exc:
                results.append({"ok": False, "operationId": str(value.get("operationId") or ""), "code": "INVALID_CAPTURE", "message": str(exc)})
                break
        return {"results": results, "complete": len(results) == len(operations) and all(value["ok"] for value in results)}
