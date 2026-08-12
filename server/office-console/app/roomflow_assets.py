from __future__ import annotations

import base64
import re
import struct
from pathlib import Path
from typing import Any

from .store import OfficeStore

def _jpeg_info(data: bytes) -> tuple[int, int, int]:
    if len(data) < 4 or not data.startswith(b"\xff\xd8"):
        raise ValueError(
            "RoomFlow layout must be captured as JPEG when the optional Pillow package is unavailable."
        )
    offset = 2
    sof_markers = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    standalone = {0x01, *range(0xD0, 0xD9)}
    length = len(data)
    while offset < length:
        while offset < length and data[offset] != 0xFF:
            offset += 1
        while offset < length and data[offset] == 0xFF:
            offset += 1
        if offset >= length:
            break
        marker = data[offset]
        offset += 1
        if marker in standalone:
            continue
        if offset + 2 > length:
            break
        segment_length = struct.unpack_from(">H", data, offset)[0]
        if segment_length < 2 or offset + segment_length > length:
            break
        if marker in sof_markers:
            if segment_length < 8:
                break
            height, width = struct.unpack_from(">HH", data, offset + 3)
            components = data[offset + 7]
            if width <= 0 or height <= 0 or components not in {1, 3}:
                raise ValueError("RoomFlow JPEG uses an unsupported image layout.")
            return width, height, components
        offset += segment_length
    raise ValueError("Could not read the RoomFlow JPEG dimensions.")


_DATA_URL = re.compile(r"^data:image/(?P<kind>png|jpeg|jpg);base64,(?P<data>[A-Za-z0-9+/=\r\n]+)$", re.I)


def _decode_image(value: Any, *, max_bytes: int = 12 * 1024 * 1024) -> tuple[bytes, str] | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = _DATA_URL.match(text)
    if match:
        raw = base64.b64decode(match.group("data"), validate=False)
        if len(raw) > max_bytes:
            raise ValueError("RoomFlow layout image exceeds the 12 MB limit.")
        return raw, "png" if match.group("kind").lower() == "png" else "jpg"
    try:
        raw = base64.b64decode(text, validate=True)
    except Exception:
        return None
    if len(raw) > max_bytes:
        raise ValueError("RoomFlow layout image exceeds the 12 MB limit.")
    return raw, "jpg"


def normalize_layout_image(content: bytes, *, max_width: int = 2200, max_height: int = 1600) -> bytes:
    """Validate and retain an Android/iOS RoomFlow JPEG without Pillow."""
    if not content:
        raise ValueError("RoomFlow layout image is empty.")
    width, height, _components = _jpeg_info(content)
    if width * height > 40_000_000:
        raise ValueError("RoomFlow layout image dimensions are too large.")
    # Direct embedding preserves the exact field sketch. The native clients
    # already cap and compress captures before upload. Oversize dimensions are
    # rejected instead of invoking an unavailable image-decoding dependency.
    return content


def store_layout_image(store: OfficeStore, value: Any, *, filename: str = "roomflow-layout.jpg") -> dict[str, Any] | None:
    decoded = _decode_image(value)
    if not decoded:
        return None
    raw, _ = decoded
    normalized = normalize_layout_image(raw)
    file_id, path = store.save_upload(filename, normalized)
    return {
        "layout_file_id": file_id,
        "layout_filename": path.name,
        "layout_mime_type": "image/jpeg",
        "layout_bytes": len(normalized),
    }


def layout_path(store: OfficeStore, record: dict[str, Any] | None) -> Path | None:
    if not record:
        return None
    file_id = str(record.get("layout_file_id") or record.get("roomflow_layout_file_id") or "").strip()
    filename = str(record.get("layout_filename") or record.get("roomflow_layout_filename") or "").strip()
    if not file_id or not filename:
        return None
    try:
        path = store.upload_path(file_id, filename)
    except Exception:
        return None
    return path if path.is_file() else None


def matching_roomflow_job(store: OfficeStore, estimate: dict[str, Any]) -> dict[str, Any] | None:
    estimate_id = str(estimate.get("id") or "")
    estimate_number = str(estimate.get("estimate_number") or "")
    roomflow_job_id = str(estimate.get("roomflow_job_id") or "")
    property_id = str(estimate.get("property_id") or "")
    contact_id = str(estimate.get("contact_id") or "")
    candidates: list[tuple[int, dict[str, Any]]] = []
    for job in store.records("roomflow_jobs"):
        score = 0
        if estimate_id and str(job.get("estimate_id") or "") == estimate_id:
            score += 100
        if estimate_number and str(job.get("estimate_number") or "") == estimate_number:
            score += 60
        if roomflow_job_id and str(job.get("roomflow_job_id") or "") == roomflow_job_id:
            score += 80
        if property_id and str(job.get("property_id") or "") == property_id:
            score += 20
        if contact_id and str(job.get("contact_id") or "") == contact_id:
            score += 10
        if layout_path(store, job):
            score += 5
        if score:
            candidates.append((score, job))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def enrich_estimate_with_roomflow(store: OfficeStore, estimate: dict[str, Any]) -> dict[str, Any]:
    result = dict(estimate)
    job = matching_roomflow_job(store, estimate)
    if not job:
        return result
    result["roomflow_job"] = job
    result["roomflow_layout_path"] = str(layout_path(store, job) or "")
    result.setdefault("roomflow_job_id", job.get("roomflow_job_id"))
    result.setdefault("roomflow_snapshot", job.get("snapshot"))
    result.setdefault("roomflow_summary", job.get("summary"))
    return result
