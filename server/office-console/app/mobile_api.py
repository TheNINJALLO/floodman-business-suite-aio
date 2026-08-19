from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from .auth import has_permission, permissions_for
from .config import Settings
from .providers import ProviderClient
from .store import CaptureOperationConflict, CaptureOperationNotFound, OfficeStore
from .project_plans import merge_project_plan
from .mobile_operations import build_operations_router
from .roomflow_assets import store_layout_image, layout_path
from .roomflow_capture import CaptureValidationError
from .roomflow_capture_service import RoomFlowCaptureService
from .roomflow_supabase import (
    DEFAULT_ROOMFLOW_SUPABASE_ANON_KEY,
    DEFAULT_ROOMFLOW_SUPABASE_URL,
    RoomFlowSupabaseError,
    create_roomflow_workspace,
    ensure_roomflow_workspaces,
    import_roomflow_supabase,
    select_roomflow_workspace,
    selected_roomflow_workspace_id,
    workspace_public,
)

API_PREFIX = "/mobile-api/v1"
API_VERSION = "0.3.0-alpha11"
MIN_ANDROID_VERSION = "0.3.0-alpha11"
MIN_IOS_VERSION = "0.1.0-alpha02"
MOBILE_CAPABILITIES = [
    "mobile.compatibility.v1",
    "estimate.detail.v1",
    "estimate.pdf.v1",
    "invoice.detail.v1",
    "invoice.pdf.v1",
    "roomflow.bootstrap.v1",
    "roomflow.snapshot.v1",
    "roomflow.catalog.v1",
    "roomflow.supabase-import.v1",
    "roomflow.layout-capture.v1",
    "roomflow.workspaces.v1",
    "roomflow.capture.v2",
    "roomflow.capture.offline.v1",
]
ACCESS_ALGORITHM = "HS256"
_LOGIN_WINDOW_SECONDS = 600
_LOGIN_ATTEMPTS = 10
_REFRESH_CLOCK_SKEW_SECONDS = 180


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _b64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_text(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _paginate(values: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    size = max(1, min(int(page_size or 50), 100))
    current = max(1, int(page or 1))
    total = len(values)
    start = (current - 1) * size
    return {
        "items": values[start : start + size],
        "page": current,
        "page_size": size,
        "total": total,
        "has_more": start + size < total,
    }


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1, max_length=256)
    auth_source: str = "platform"
    device_id: str = Field(min_length=8, max_length=128)
    device_name: str = Field(default="Android device", max_length=160)
    platform: str = Field(default="android", max_length=40)
    app_version: str = Field(default="", max_length=80)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=512)
    device_id: str = Field(min_length=8, max_length=128)
    timestamp: int
    nonce: str = Field(min_length=8, max_length=128)
    proof: str = Field(min_length=32, max_length=256)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    category: str = Field(default="GENERAL", max_length=80)
    pinned: bool = False


class TagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=80)


class ClockRequest(BaseModel):
    job_reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=2_000)


class CatalogLine(BaseModel):
    catalog_item_id: str | None = None
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=8_000)
    category: str = Field(default="General Services", max_length=160)
    unit: str = Field(default="each", max_length=80)
    quantity: float = 1.0
    unit_price_cents: int = 0
    taxable: bool = False
    optional: bool = False
    save_to_catalog: bool = False


class EstimateSection(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4_000)
    lines: list[CatalogLine] = Field(default_factory=list, max_length=500)


class EstimateCreateRequest(BaseModel):
    contact_id: str
    property_id: str
    estimate_number: str = Field(default="", max_length=120)
    title: str = Field(min_length=1, max_length=240)
    project_category: str = Field(default="general-restoration", max_length=160)
    recommended_project_title: str = Field(default="", max_length=300)
    project_summary: str = Field(default="", max_length=12_000)
    estimated_duration: str = Field(default="", max_length=160)
    project_outcomes: list[dict[str, Any]] = Field(default_factory=list)
    protections: list[str] = Field(default_factory=list)
    optional_upgrades: list[str] = Field(default_factory=list)
    assumptions: str = Field(default="", max_length=12_000)
    exclusions: str = Field(default="", max_length=12_000)
    customer_notes: str = Field(default="", max_length=12_000)
    terms: str = Field(default="", max_length=12_000)
    expiration_days: int = 30
    deposit_type: str = "PERCENT"
    deposit_percent: float = 50.0
    deposit_fixed_cents: int = 0
    deposit_due_stage: str = "AFTER_AUTHORIZATION"
    sections: list[EstimateSection] = Field(default_factory=list, min_length=1, max_length=80)


class RoomFlowSaveRequest(BaseModel):
    workspace_id: str | None = None
    roomflow_job_id: str | None = None
    job_name: str = Field(default="", max_length=300)
    contact_id: str | None = None
    property_id: str | None = None
    estimate_id: str | None = None
    estimate_number: str = Field(default="", max_length=120)
    status: str = Field(default="DRAFT", max_length=80)
    project_category: str = Field(default="general-restoration", max_length=160)
    title: str = Field(default="", max_length=300)
    customer_name: str = Field(default="", max_length=300)
    customer_email: str = Field(default="", max_length=320)
    customer_phone: str = Field(default="", max_length=80)
    property_address: str = Field(default="", max_length=500)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    layout_data_url: str = Field(default="", max_length=18_000_000)
    sections: list[EstimateSection] = Field(default_factory=list, max_length=80)
    sync_estimate: bool = True


class RoomFlowSupabaseImportRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=512)


class RoomFlowWorkspaceCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=300)
    timezone: str = Field(default="America/Detroit", max_length=80)


class MobileCardPaymentRequest(BaseModel):
    target_kind: str
    target_id: str
    source_id: str = Field(min_length=8, max_length=512)
    amount_cents: int = Field(gt=0)
    save_card: bool = False
    authorization_reference: str = Field(default="", max_length=500)
    note: str = Field(default="", max_length=500)


class ManualPaymentRequest(BaseModel):
    target_kind: str
    target_id: str
    amount_cents: int = Field(gt=0)
    method: str = Field(default="CASH", max_length=80)
    reference: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=1000)
    check_date: str = Field(default="", max_length=40)
    bank_name: str = Field(default="", max_length=200)
    check_status: str = Field(default="RECEIVED", max_length=80)


class CustomerCreateRequest(BaseModel):
    first_name: str = Field(default="", max_length=160)
    last_name: str = Field(default="", max_length=160)
    company: str = Field(default="", max_length=240)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=80)
    mailing_street: str = Field(default="", max_length=300)
    mailing_city: str = Field(default="", max_length=160)
    mailing_state: str = Field(default="MI", max_length=80)
    mailing_postal_code: str = Field(default="", max_length=40)
    lead_source: str = Field(default="Android app", max_length=200)
    initial_note: str = Field(default="", max_length=5000)


class PropertyCreateRequest(BaseModel):
    contact_id: str
    property_name: str = Field(default="", max_length=240)
    property_type: str = Field(default="", max_length=160)
    service_street: str = Field(min_length=1, max_length=300)
    service_city: str = Field(min_length=1, max_length=160)
    service_state: str = Field(default="MI", max_length=80)
    service_postal_code: str = Field(default="", max_length=40)
    insurance_company: str = Field(default="", max_length=240)
    claim_number: str = Field(default="", max_length=160)
    notes: str = Field(default="", max_length=5000)


class DeviceRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)


class _LoginLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.time()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] > _LOGIN_WINDOW_SECONDS:
                events.popleft()
            if len(events) >= _LOGIN_ATTEMPTS:
                raise HTTPException(429, "Too many login attempts. Wait a few minutes and try again.")
            events.append(now)

    def success(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


class MobileSecurity:
    def __init__(self, settings: Settings, store: OfficeStore) -> None:
        self.settings = settings
        self.store = store
        self.limiter = _LoginLimiter()

    @property
    def configured(self) -> bool:
        return bool(self.settings.mobile_token_secret and len(self.settings.mobile_token_secret) >= 32)

    def _master(self) -> bytes:
        if not self.configured:
            raise HTTPException(503, "The Floodman mobile API security key is not configured.")
        return self.settings.mobile_token_secret.encode("utf-8")

    def device_secret(self, user_id: str, device_id: str) -> str:
        digest = hmac.new(
            self._master(),
            f"device-key:{user_id}:{device_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return _b64_encode(digest)

    def access_token(self, user: dict[str, Any], device_id: str) -> tuple[str, str]:
        issued = int(time.time())
        expires = issued + max(300, int(self.settings.mobile_access_ttl_seconds))
        payload = {
            "iss": "floodman-operations",
            "aud": "floodman-android",
            "sub": str(user.get("id") or ""),
            "device": device_id,
            "role": str(user.get("role") or "VIEWER"),
            "iat": issued,
            "exp": expires,
            "jti": str(uuid.uuid4()),
            "ver": 1,
        }
        body = _b64_encode(_json_bytes(payload))
        signature = _b64_encode(hmac.new(self._master(), body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}", datetime.fromtimestamp(expires, UTC).isoformat()

    def verify_access(self, token: str) -> dict[str, Any]:
        try:
            body, signature = token.split(".", 1)
            expected = _b64_encode(hmac.new(self._master(), body.encode("ascii"), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise ValueError("bad signature")
            payload = json.loads(_b64_decode(body))
            if payload.get("iss") != "floodman-operations" or payload.get("aud") != "floodman-android":
                raise ValueError("bad audience")
            if int(payload.get("exp") or 0) <= int(time.time()):
                raise HTTPException(401, "Session expired")
            return dict(payload)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(401, "Invalid mobile session") from exc

    def issue_refresh(self, user_id: str, device_id: str, actor_id: str) -> tuple[str, str]:
        token = secrets.token_urlsafe(48)
        expires = _now() + timedelta(days=max(1, int(self.settings.mobile_refresh_ttl_days)))
        self.store.create_record(
            "mobile_refresh_tokens",
            {
                "token_hash": _hash_token(token),
                "user_id": user_id,
                "device_id": device_id,
                "expires_at": expires.isoformat(),
                "revoked_at": None,
                "used_at": None,
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=actor_id,
        )
        return token, expires.isoformat()

    def refresh_record(self, refresh_token: str) -> dict[str, Any] | None:
        digest = _hash_token(refresh_token)
        for record in self.store.records("mobile_refresh_tokens"):
            if hmac.compare_digest(str(record.get("token_hash") or ""), digest):
                return record
        return None

    def verify_refresh_proof(self, request: RefreshRequest, record: dict[str, Any]) -> None:
        now = int(time.time())
        if abs(now - int(request.timestamp)) > _REFRESH_CLOCK_SKEW_SECONDS:
            raise HTTPException(401, "Device clock is too far out of sync")
        user_id = str(record.get("user_id") or "")
        if str(record.get("device_id") or "") != request.device_id:
            raise HTTPException(401, "Refresh token does not belong to this device")
        secret = _b64_decode(self.device_secret(user_id, request.device_id))
        canonical = f"{request.device_id}.{request.timestamp}.{request.nonce}.{_hash_token(request.refresh_token)}"
        expected = _b64_encode(hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, request.proof):
            raise HTTPException(401, "Device proof was not accepted")


def build_mobile_router(store: OfficeStore, providers: ProviderClient, settings: Settings) -> APIRouter:
    router = APIRouter(prefix=API_PREFIX, tags=["Floodman Android"])
    security = MobileSecurity(settings, store)
    capture_service = RoomFlowCaptureService(store)

    def audit(event: str, *, user_id: str = "", device_id: str = "", request: Request | None = None, detail: dict[str, Any] | None = None) -> None:
        try:
            store.create_record(
                "mobile_audit",
                {
                    "event": event,
                    "user_id": user_id or None,
                    "device_id": device_id or None,
                    "ip": str((request.client.host if request and request.client else "") or ""),
                    "user_agent": str((request.headers.get("user-agent") if request else "") or "")[:500],
                    "detail": detail or {},
                    "occurred_at": _now_iso(),
                    "source": "FLOODMAN_ANDROID",
                },
                actor_id=user_id or "mobile-api",
            )
        except Exception:
            pass

    def require_mobile_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Bearer token required")
        claims = security.verify_access(authorization.split(" ", 1)[1].strip())
        user = store.get_user(str(claims.get("sub") or ""))
        if not user or str(user.get("status") or "") != "ACTIVE":
            raise HTTPException(401, "Account is unavailable")
        device = store.record("mobile_devices", str(claims.get("device") or ""))
        if not device or str(device.get("user_id") or "") != str(user.get("id") or "") or str(device.get("status") or "") != "ACTIVE":
            raise HTTPException(401, "Device is not authorized")
        try:
            store.update_record("mobile_devices", str(device["id"]), {"last_seen_at": _now_iso()}, actor_id=str(user.get("id") or ""))
        except Exception:
            pass
        return {**user, "mobile_device_id": str(device.get("id") or ""), "access_claims": claims}

    def require_permission(permission: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        def dependency(user: dict[str, Any] = require_mobile_user) -> dict[str, Any]:
            if not has_permission(user, permission):
                raise HTTPException(403, f"Permission required: {permission}")
            return user
        return dependency

    # FastAPI cannot use a closure-returned function as a default dependency without Depends.
    # The tiny explicit helper below keeps endpoint signatures readable.
    from fastapi import Depends

    def permission(permission: str):
        def checker(user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
            if not has_permission(user, permission):
                raise HTTPException(403, f"Permission required: {permission}")
            return user
        return Depends(checker)

    def contact_public(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "id", "first_name", "last_name", "name", "company", "email", "email_2", "phone", "mobile_phone",
                "mailing_street", "mailing_city", "mailing_state", "mailing_postal_code", "address", "lead_source",
                "status", "tags", "notes", "source", "created_at", "updated_at", "square_customer_id",
                "default_square_card_id", "square_cards",
            )
            if record.get(key) is not None
        }

    def property_public(record: dict[str, Any]) -> dict[str, Any]:
        return {
            key: record.get(key)
            for key in (
                "id", "contact_id", "name", "property_name", "property_type", "service_street", "service_city",
                "service_state", "service_postal_code", "insurance_company", "claim_number", "notes", "status",
                "source", "created_at", "updated_at",
            )
            if record.get(key) is not None
        }

    def document_public(record: dict[str, Any]) -> dict[str, Any]:
        excluded = {"provider_response", "password_hash", "source_id", "card_token", "access_token"}
        return {key: value for key, value in record.items() if key not in excluded}

    def next_estimate_number() -> str:
        year = _now().year
        numbers = []
        for estimate in store.records("estimates"):
            value = str(estimate.get("estimate_number") or "")
            digits = "".join(char for char in value.split("-")[-1] if char.isdigit())
            if digits:
                numbers.append(int(digits))
        return f"EST-{year}-{max(numbers, default=1000) + 1:04d}"

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "floodman-mobile-api",
            "api_version": API_VERSION,
            "server_release": settings.release,
            "authentication_configured": security.configured,
            "time_zone": settings.ar_timezone,
            "minimum_android_version": MIN_ANDROID_VERSION,
            "minimum_ios_version": MIN_IOS_VERSION,
            "capabilities": MOBILE_CAPABILITIES,
        }

    @router.get("/config")
    def mobile_config() -> dict[str, Any]:
        square = providers.square_payment_configuration()
        return {
            "api_version": API_VERSION,
            "company": store.profile().get("company_name") or "Floodman",
            "time_zone": store.profile().get("timezone") or settings.ar_timezone,
            "payments": {
                "enabled": bool(settings.payments_enabled and square.get("application_id")),
                "environment": square.get("environment"),
                "application_id": square.get("application_id") or "",
                "native_card_entry": bool(square.get("application_id")),
            },
            "customer_public_url": settings.customer_public_url,
            "minimum_android_version": MIN_ANDROID_VERSION,
            "minimum_ios_version": MIN_IOS_VERSION,
            "capabilities": MOBILE_CAPABILITIES,
            "roomflow_import": {
                "enabled": True,
                "source": "Original RoomFlow Supabase",
            },
        }

    @router.post("/auth/login")
    async def login(payload: LoginRequest, request: Request) -> dict[str, Any]:
        email = payload.email.strip().lower()
        remote = str((request.client.host if request.client else "") or "unknown")
        limiter_key = f"{remote}:{email}"
        security.limiter.check(limiter_key)
        user: dict[str, Any] | None = None
        try:
            if payload.auth_source.strip().lower() == "local":
                user = store.authenticate(email, payload.password)
                if not user:
                    raise RuntimeError("Floodman did not accept that email and password.")
            else:
                identity = await providers.authenticate_gauzy_member(email, payload.password)
                user = store.upsert_gauzy_user(identity)
            if not user or str(user.get("status") or "") != "ACTIVE":
                raise RuntimeError("Floodman account is inactive.")
        except Exception as exc:
            audit("LOGIN_FAILED", request=request, device_id=payload.device_id, detail={"email_hash": _hash_token(email), "reason": str(exc)[:300]})
            raise HTTPException(401, str(exc)) from exc
        security.limiter.success(limiter_key)
        user_id = str(user.get("id") or "")
        device = store.record("mobile_devices", payload.device_id)
        if device and str(device.get("user_id") or "") != user_id:
            raise HTTPException(409, "That device registration belongs to another Floodman account")
        values = {
            "id": payload.device_id,
            "user_id": user_id,
            "name": payload.device_name.strip() or "Android device",
            "platform": payload.platform.strip().lower() or "android",
            "app_version": payload.app_version.strip(),
            "status": "ACTIVE",
            "last_seen_at": _now_iso(),
            "last_ip": remote,
            "last_user_agent": request.headers.get("user-agent", "")[:500],
            "source": "FLOODMAN_ANDROID",
        }
        if device:
            device = store.update_record("mobile_devices", payload.device_id, values, actor_id=user_id)
        else:
            device = store.create_record("mobile_devices", values, actor_id=user_id)
        # Revoke any old refresh tokens for this exact device before issuing a new chain.
        for record in store.records("mobile_refresh_tokens"):
            if str(record.get("user_id") or "") == user_id and str(record.get("device_id") or "") == payload.device_id:
                store.delete_record("mobile_refresh_tokens", str(record["id"]))
        access_token, access_expires = security.access_token(user, payload.device_id)
        refresh_token, refresh_expires = security.issue_refresh(user_id, payload.device_id, user_id)
        audit("LOGIN_SUCCEEDED", user_id=user_id, device_id=payload.device_id, request=request)
        return {
            "access_token": access_token,
            "access_expires_at": access_expires,
            "refresh_token": refresh_token,
            "refresh_expires_at": refresh_expires,
            "device_secret": security.device_secret(user_id, payload.device_id),
            "token_type": "Bearer",
            "user": {
                "id": user_id,
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role"),
                "permissions": sorted(permissions_for(user)),
            },
            "device": device,
        }

    @router.post("/auth/refresh")
    def refresh(payload: RefreshRequest, request: Request) -> dict[str, Any]:
        record = security.refresh_record(payload.refresh_token)
        if not record or record.get("revoked_at") or record.get("used_at"):
            raise HTTPException(401, "Refresh session is unavailable")
        try:
            expires = datetime.fromisoformat(str(record.get("expires_at") or "").replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(401, "Refresh session is invalid") from exc
        if expires <= _now():
            raise HTTPException(401, "Refresh session expired")
        security.verify_refresh_proof(payload, record)
        user = store.get_user(str(record.get("user_id") or ""))
        device = store.record("mobile_devices", payload.device_id)
        if not user or str(user.get("status") or "") != "ACTIVE" or not device or str(device.get("status") or "") != "ACTIVE":
            raise HTTPException(401, "Account or device is unavailable")
        store.update_record("mobile_refresh_tokens", str(record["id"]), {"used_at": _now_iso()}, actor_id=str(user["id"]))
        access_token, access_expires = security.access_token(user, payload.device_id)
        refresh_token, refresh_expires = security.issue_refresh(str(user["id"]), payload.device_id, str(user["id"]))
        store.update_record("mobile_devices", payload.device_id, {"last_seen_at": _now_iso()}, actor_id=str(user["id"]))
        audit("TOKEN_REFRESHED", user_id=str(user["id"]), device_id=payload.device_id, request=request)
        return {
            "access_token": access_token,
            "access_expires_at": access_expires,
            "refresh_token": refresh_token,
            "refresh_expires_at": refresh_expires,
            "token_type": "Bearer",
        }

    @router.post("/auth/logout")
    def logout(payload: LogoutRequest, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, bool]:
        if payload.refresh_token:
            record = security.refresh_record(payload.refresh_token)
            if record and str(record.get("user_id") or "") == str(user.get("id") or ""):
                store.delete_record("mobile_refresh_tokens", str(record["id"]))
        return {"ok": True}

    @router.get("/auth/me")
    def me(user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        return {
            "id": user.get("id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "role": user.get("role"),
            "permissions": sorted(permissions_for(user)),
            "device_id": user.get("mobile_device_id"),
        }

    @router.get("/devices")
    def devices(all_devices: bool = False, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        can_manage = has_permission(user, "members.manage")
        values = list(store.records("mobile_devices")) if all_devices and can_manage else [
            item for item in store.records("mobile_devices")
            if str(item.get("user_id") or "") == str(user.get("id") or "")
        ]
        values.sort(key=lambda item: str(item.get("last_seen_at") or ""), reverse=True)
        return {"items": values, "all_devices": bool(all_devices and can_manage)}

    @router.patch("/devices/{device_id}")
    def rename_device(device_id: str, payload: DeviceRenameRequest, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        device = store.record("mobile_devices", device_id)
        if not device or str(device.get("user_id") or "") != str(user.get("id") or ""):
            raise HTTPException(404, "Device not found")
        return store.update_record("mobile_devices", device_id, {"name": payload.name.strip()}, actor_id=str(user["id"]))

    @router.delete("/devices/{device_id}")
    def revoke_device(device_id: str, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, bool]:
        device = store.record("mobile_devices", device_id)
        can_manage = has_permission(user, "members.manage")
        if not device or (str(device.get("user_id") or "") != str(user.get("id") or "") and not can_manage):
            raise HTTPException(404, "Device not found")
        store.update_record("mobile_devices", device_id, {"status": "REVOKED", "revoked_at": _now_iso()}, actor_id=str(user["id"]))
        for record in store.records("mobile_refresh_tokens"):
            if str(record.get("device_id") or "") == device_id:
                store.delete_record("mobile_refresh_tokens", str(record["id"]))
        audit("DEVICE_REVOKED", user_id=str(user["id"]), device_id=device_id)
        return {"ok": True}

    @router.get("/dashboard")
    def dashboard(user: dict[str, Any] = permission("dashboard.view")) -> dict[str, Any]:
        invoices = store.records("invoices")
        estimates = store.records("estimates")
        tasks = store.records("tasks")
        user_id = str(user.get("id") or "")
        now = _now()
        balance = sum(max(0, _safe_int(item.get("balance_cents"))) for item in invoices if str(item.get("status") or "").upper() not in {"PAID", "VOID", "CANCELED"})

        def parsed_time(value: Any) -> datetime | None:
            try:
                return datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
            except ValueError:
                return None

        can_view_all_schedule = has_permission(user, "schedule.manage") or has_permission(user, "members.manage")
        upcoming: list[dict[str, Any]] = []
        for item in store.records("appointments"):
            start_at = parsed_time(item.get("start_at"))
            if not start_at or start_at < now - timedelta(hours=2):
                continue
            assigned = [str(value) for value in (item.get("assigned_user_ids") or [])]
            lead = str(item.get("lead_user_id") or "")
            if not can_view_all_schedule and user_id not in assigned and user_id != lead:
                continue
            upcoming.append({key: value for key, value in item.items() if key not in {"provider_response", "access_token"}})
        upcoming.sort(key=lambda value: str(value.get("start_at") or ""))

        active_announcements: list[dict[str, Any]] = []
        for item in store.records("announcements"):
            expires_at = parsed_time(item.get("expires_at"))
            if expires_at and expires_at < now:
                continue
            active_announcements.append({key: value for key, value in item.items() if key not in {"provider_response", "access_token"}})
        active_announcements.sort(key=lambda value: str(value.get("created_at") or ""), reverse=True)

        user_notifications = [
            item for item in store.records("notifications")
            if str(item.get("user_id") or item.get("recipient_user_id") or "") in {"", user_id}
        ]
        unread = len([item for item in user_notifications if str(item.get("status") or "UNREAD").upper() == "UNREAD"])

        return {
            "customers": len(store.records("contacts")),
            "properties": len(store.records("properties")),
            "open_estimates": len([item for item in estimates if str(item.get("status") or "").upper() in {"DRAFT", "SENT", "READY_FOR_REVIEW"}]),
            "open_invoices": len([item for item in invoices if _safe_int(item.get("balance_cents")) > 0]),
            "outstanding_balance_cents": balance,
            "assigned_tasks": len([item for item in tasks if str(item.get("assigned_user_id") or item.get("user_id") or "") == user_id and str(item.get("status") or "").upper() not in {"DONE", "COMPLETED", "CANCELED"}]),
            "clock": store.current_clock(user_id),
            "recent_estimates": [document_public(item) for item in estimates[:5]],
            "recent_invoices": [document_public(item) for item in invoices[:5]],
            "upcoming_appointments": upcoming[:8],
            "active_announcements": active_announcements[:5],
            "unread_notifications": unread,
        }

    @router.get("/customers")
    def customers(q: str = "", workspace_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("contacts.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        selected_workspace = workspace_id.strip()
        if selected_workspace:
            valid_ids = {
                str(record.get("id") or "")
                for record in ensure_roomflow_workspaces(store, actor_id=str(user.get("id") or ""))
            }
            if selected_workspace not in valid_ids:
                raise HTTPException(422, "Select a valid RoomFlow workspace.")
        values = []
        for record in store.records("contacts"):
            if selected_workspace and str(record.get("workspace_id") or "") not in {"", selected_workspace}:
                continue
            haystack = " ".join(str(record.get(key) or "") for key in ("name", "first_name", "last_name", "company", "email", "email_2", "phone", "mobile_phone", "address", "mailing_street", "mailing_city", "tags")).casefold()
            if query and query not in haystack:
                continue
            values.append(contact_public(record))
        return _paginate(values, page, page_size)

    @router.post("/customers")
    def create_customer(payload: CustomerCreateRequest, user: dict[str, Any] = permission("contacts.manage")) -> dict[str, Any]:
        name = " ".join(value for value in (payload.first_name.strip(), payload.last_name.strip()) if value).strip()
        if not name and not payload.company.strip():
            raise HTTPException(422, "Enter a customer name or company")
        normalized_email = payload.email.strip().lower()
        normalized_phone = "".join(ch for ch in payload.phone if ch.isdigit() or ch == "+")
        # Avoid duplicate mobile-created contacts when staff retries after a network interruption.
        for existing in store.records("contacts"):
            if normalized_email and str(existing.get("email") or "").strip().lower() == normalized_email:
                return contact_public(existing)
            existing_phone = "".join(ch for ch in str(existing.get("phone") or existing.get("mobile_phone") or "") if ch.isdigit() or ch == "+")
            if normalized_phone and existing_phone == normalized_phone and str(existing.get("name") or "").strip().casefold() == name.casefold():
                return contact_public(existing)
        record = store.create_record(
            "contacts",
            {
                "first_name": payload.first_name.strip() or None,
                "last_name": payload.last_name.strip() or None,
                "name": name or payload.company.strip(),
                "company": payload.company.strip() or None,
                "email": normalized_email or None,
                "phone": payload.phone.strip() or None,
                "mobile_phone": payload.phone.strip() or None,
                "mailing_street": payload.mailing_street.strip() or None,
                "mailing_city": payload.mailing_city.strip() or None,
                "mailing_state": payload.mailing_state.strip() or "MI",
                "mailing_postal_code": payload.mailing_postal_code.strip() or None,
                "address": ", ".join(value for value in (payload.mailing_street.strip(), payload.mailing_city.strip(), payload.mailing_state.strip(), payload.mailing_postal_code.strip()) if value),
                "lead_source": payload.lead_source.strip() or "Android app",
                "status": "ACTIVE",
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )
        if payload.initial_note.strip():
            store.create_record(
                "notes",
                {
                    "contact_id": record["id"],
                    "text": payload.initial_note.strip(),
                    "note": payload.initial_note.strip(),
                    "category": "GENERAL",
                    "pinned": False,
                    "author_name": user.get("name"),
                    "source": "FLOODMAN_ANDROID",
                },
                actor_id=str(user.get("id") or ""),
            )
        audit("CUSTOMER_CREATED", user_id=str(user.get("id") or ""), device_id=str(user.get("mobile_device_id") or ""), detail={"contact_id": record["id"]})
        return contact_public(record)


    @router.get("/customers/{contact_id}")
    def customer(contact_id: str, user: dict[str, Any] = permission("contacts.view")) -> dict[str, Any]:
        contact = store.record("contacts", contact_id)
        if not contact:
            raise HTTPException(404, "Customer not found")
        return {
            "customer": contact_public(contact),
            "properties": [property_public(item) for item in store.records("properties") if str(item.get("contact_id") or "") == contact_id],
            "notes": [document_public(item) for item in store.records("notes") if str(item.get("contact_id") or "") == contact_id],
            "estimates": [document_public(item) for item in store.records("estimates") if str(item.get("contact_id") or "") == contact_id],
            "invoices": [document_public(item) for item in store.records("invoices") if str(item.get("contact_id") or "") == contact_id],
            "payments": [document_public(item) for item in store.records("payments") if str(item.get("contact_id") or "") == contact_id],
            "documents": [document_public(item) for item in store.records("documents") if str(item.get("contact_id") or "") == contact_id],
        }

    @router.post("/customers/{contact_id}/notes")
    def add_note(contact_id: str, payload: NoteRequest, user: dict[str, Any] = permission("notes.manage")) -> dict[str, Any]:
        if not store.record("contacts", contact_id):
            raise HTTPException(404, "Customer not found")
        return store.create_record(
            "notes",
            {
                "contact_id": contact_id,
                "text": payload.text.strip(),
                "note": payload.text.strip(),
                "category": payload.category.strip().upper() or "GENERAL",
                "pinned": payload.pinned,
                "author_name": user.get("name"),
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )

    @router.put("/customers/{contact_id}/tags")
    def update_tags(contact_id: str, payload: TagsRequest, user: dict[str, Any] = permission("contacts.manage")) -> dict[str, Any]:
        contact = store.record("contacts", contact_id)
        if not contact:
            raise HTTPException(404, "Customer not found")
        tags = []
        seen = set()
        for value in payload.tags:
            item = _clean_text(value, 80)
            key = item.casefold()
            if item and key not in seen:
                tags.append(item)
                seen.add(key)
        return contact_public(store.update_record("contacts", contact_id, {"tags": tags}, actor_id=str(user.get("id") or "")))

    @router.get("/properties")
    def properties(contact_id: str = "", q: str = "", workspace_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("properties.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        selected_workspace = workspace_id.strip()
        if selected_workspace:
            valid_ids = {
                str(record.get("id") or "")
                for record in ensure_roomflow_workspaces(store, actor_id=str(user.get("id") or ""))
            }
            if selected_workspace not in valid_ids:
                raise HTTPException(422, "Select a valid RoomFlow workspace.")
        values = []
        for record in store.records("properties"):
            if selected_workspace and str(record.get("workspace_id") or "") not in {"", selected_workspace}:
                continue
            if contact_id and str(record.get("contact_id") or "") != contact_id:
                continue
            haystack = " ".join(str(record.get(key) or "") for key in ("name", "property_name", "property_type", "service_street", "service_city", "service_state", "service_postal_code", "claim_number")).casefold()
            if query and query not in haystack:
                continue
            values.append(property_public(record))
        return _paginate(values, page, page_size)

    @router.post("/properties")
    def create_property(payload: PropertyCreateRequest, user: dict[str, Any] = permission("properties.manage")) -> dict[str, Any]:
        contact = store.record("contacts", payload.contact_id)
        if not contact:
            raise HTTPException(422, "Choose a valid customer")
        street = payload.service_street.strip()
        city = payload.service_city.strip()
        state_value = payload.service_state.strip() or "MI"
        postal = payload.service_postal_code.strip()
        for existing in store.records("properties"):
            if str(existing.get("contact_id") or "") != payload.contact_id:
                continue
            signature = "|".join(str(existing.get(key) or "").strip().casefold() for key in ("service_street", "service_city", "service_state", "service_postal_code"))
            requested = "|".join(value.casefold() for value in (street, city, state_value, postal))
            if signature == requested:
                return property_public(existing)
        record = store.create_record(
            "properties",
            {
                "contact_id": payload.contact_id,
                "name": payload.property_name.strip() or street,
                "property_name": payload.property_name.strip() or street,
                "property_type": payload.property_type.strip() or None,
                "service_street": street,
                "service_city": city,
                "service_state": state_value,
                "service_postal_code": postal or None,
                "insurance_company": payload.insurance_company.strip() or None,
                "claim_number": payload.claim_number.strip() or None,
                "notes": payload.notes.strip() or None,
                "status": "ACTIVE",
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )
        audit("PROPERTY_CREATED", user_id=str(user.get("id") or ""), device_id=str(user.get("mobile_device_id") or ""), detail={"property_id": record["id"], "contact_id": payload.contact_id})
        return property_public(record)


    @router.get("/properties/{property_id}")
    def property_detail(property_id: str, user: dict[str, Any] = permission("properties.view")) -> dict[str, Any]:
        record = store.record("properties", property_id)
        if not record:
            raise HTTPException(404, "Property not found")
        return {
            "property": property_public(record),
            "customer": contact_public(store.record("contacts", str(record.get("contact_id") or "")) or {}),
            "estimates": [document_public(item) for item in store.records("estimates") if str(item.get("property_id") or "") == property_id],
            "invoices": [document_public(item) for item in store.records("invoices") if str(item.get("property_id") or "") == property_id],
            "documents": [document_public(item) for item in store.records("documents") if str(item.get("property_id") or "") == property_id],
        }

    @router.get("/catalog")
    def catalog(q: str = "", category: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        category_query = category.strip().casefold()
        values = []
        for record in store.records("catalog_items"):
            if record.get("active") is False:
                continue
            if category_query and str(record.get("category") or "").casefold() != category_query:
                continue
            pricing = ((record.get("formula") or {}).get("xactimate") or {})
            haystack = " ".join([
                *(str(record.get(key) or "") for key in ("name", "description", "category", "unit", "source_provider", "source_id", "external_key")),
                *(str(pricing.get(key) or "") for key in ("code", "price_list", "market", "effective_date")),
            ]).casefold()
            if query and query not in haystack:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.get("/estimates")
    def estimates(q: str = "", status: str = "", contact_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        status_query = status.strip().upper()
        values = []
        contacts = {str(item.get("id")): item for item in store.records("contacts")}
        for record in store.records("estimates"):
            if contact_id and str(record.get("contact_id") or "") != contact_id:
                continue
            if status_query and str(record.get("status") or "").upper() != status_query:
                continue
            contact = contacts.get(str(record.get("contact_id") or ""), {})
            haystack = " ".join(str(value or "") for value in (record.get("estimate_number"), record.get("title"), record.get("status"), contact.get("name"), contact.get("email"), contact.get("phone"))).casefold()
            if query and query not in haystack:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.get("/estimates/{estimate_id}")
    def estimate_detail(estimate_id: str, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        record = store.record("estimates", estimate_id)
        if not record:
            raise HTTPException(404, "Estimate not found")
        status = str(record.get("status") or "DRAFT").upper()
        deposit_total = _safe_int(record.get("deposit_cents") or record.get("deposit_balance_cents"))
        deposit_paid = _safe_int(record.get("deposit_paid_cents"))
        actions = ["view_pdf", "open_customer_view"]
        if status in {"DRAFT", "SENT", "VIEWED", "READY_FOR_REVIEW"}:
            actions += ["edit", "send", "resend", "send_work_authorization", "mark_accepted"]
        if deposit_total > 0 and not record.get("deposit_payable"):
            actions.append("activate_deposit")
        if max(0, deposit_total - deposit_paid) > 0:
            actions += ["take_payment", "open_payment_link"]
        if status in {"ACCEPTED", "APPROVED", "DEPOSIT_DUE", "DEPOSIT_PAID", "SENT", "VIEWED"} and not record.get("converted_invoice_id"):
            actions.append("convert_to_invoice")
        if status in {"DRAFT", "SENT", "VIEWED"} and not record.get("converted_invoice_id"):
            actions.append("delete")
        return {
            "estimate": document_public(record),
            "customer": contact_public(store.record("contacts", str(record.get("contact_id") or "")) or {}),
            "property": property_public(store.record("properties", str(record.get("property_id") or "")) or {}),
            "payments": [document_public(item) for item in store.records("payments") if str(item.get("estimate_id") or "") == estimate_id],
            "documents": [document_public(item) for item in store.records("documents") if str(item.get("estimate_id") or "") == estimate_id],
            "allowed_actions": list(dict.fromkeys(actions)),
        }

    @router.post("/estimates")
    def create_estimate(payload: EstimateCreateRequest, user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        contact = store.record("contacts", payload.contact_id)
        property_record = store.record("properties", payload.property_id)
        if not contact:
            raise HTTPException(422, "Choose a valid customer")
        if not property_record or str(property_record.get("contact_id") or "") != payload.contact_id:
            raise HTTPException(422, "Choose a property that belongs to the selected customer")
        sections: list[dict[str, Any]] = []
        line_items: list[dict[str, Any]] = []
        total_cents = 0
        for section_index, section in enumerate(payload.sections):
            section_id = str(uuid.uuid4())
            section_total = 0
            section_record = {
                "id": section_id,
                "title": section.title.strip(),
                "description": section.description.strip(),
                "sort_order": section_index,
            }
            sections.append(section_record)
            for line_index, line in enumerate(section.lines):
                quantity = max(0.0, _safe_float(line.quantity, 0.0))
                unit_price_cents = max(0, _safe_int(line.unit_price_cents))
                line_total = int(round(quantity * unit_price_cents))
                item = {
                    "id": str(uuid.uuid4()),
                    "section_id": section_id,
                    "section_name": section.title.strip(),
                    "catalog_item_id": line.catalog_item_id,
                    "name": line.name.strip(),
                    "description": line.description.strip(),
                    "category": line.category.strip() or "General Services",
                    "unit": line.unit.strip() or "each",
                    "quantity": quantity,
                    "unit_price_cents": unit_price_cents,
                    "unit_price": unit_price_cents / 100,
                    "line_total_cents": line_total,
                    "taxable": bool(line.taxable),
                    "optional": bool(line.optional),
                    "sort_order": line_index,
                }
                line_items.append(item)
                if not line.optional:
                    section_total += line_total
                if line.save_to_catalog and not line.catalog_item_id:
                    catalog_record = store.create_record(
                        "catalog_items",
                        {
                            "name": line.name.strip(),
                            "description": line.description.strip(),
                            "category": line.category.strip() or "General Services",
                            "unit": line.unit.strip() or "each",
                            "unit_price_cents": unit_price_cents,
                            "unit_price": unit_price_cents / 100,
                            "taxable": bool(line.taxable),
                            "active": True,
                            "source_provider": "FLOODMAN_ANDROID",
                            "external_key": f"android-{uuid.uuid4()}",
                        },
                        actor_id=str(user.get("id") or ""),
                    )
                    item["catalog_item_id"] = catalog_record["id"]
            section_record["subtotal_cents"] = section_total
            total_cents += section_total
        deposit_type = payload.deposit_type.strip().upper()
        if deposit_type not in {"NONE", "PERCENT", "FIXED"}:
            deposit_type = "PERCENT"
        deposit_percent = max(0.0, min(100.0, payload.deposit_percent))
        if deposit_type == "NONE":
            deposit_cents = 0
        elif deposit_type == "FIXED":
            deposit_cents = max(0, min(total_cents, payload.deposit_fixed_cents))
        else:
            deposit_cents = int(round(total_cents * deposit_percent / 100.0))
        record = store.create_record(
            "estimates",
            {
                "estimate_number": payload.estimate_number.strip() or next_estimate_number(),
                "contact_id": payload.contact_id,
                "property_id": payload.property_id,
                "title": payload.title.strip(),
                "project_category": payload.project_category.strip() or "general-restoration",
                "recommended_project_title": payload.recommended_project_title.strip(),
                "project_outcomes": payload.project_outcomes,
                "protections": payload.protections,
                "optional_upgrades": payload.optional_upgrades,
                "status": "DRAFT",
                "currency": "USD",
                "sections": sections,
                "line_items": line_items,
                "total_cents": total_cents,
                "summary": payload.project_summary.strip(),
                "project_summary": payload.project_summary.strip(),
                "estimated_duration": payload.estimated_duration.strip(),
                "assumptions": payload.assumptions.strip(),
                "exclusions": payload.exclusions.strip(),
                "customer_notes": payload.customer_notes.strip(),
                "terms": payload.terms.strip(),
                "expiration_days": max(1, min(365, payload.expiration_days)),
                "deposit_type": deposit_type,
                "deposit_percent": deposit_percent,
                "deposit_fixed_cents": max(0, payload.deposit_fixed_cents),
                "deposit_due_stage": payload.deposit_due_stage.strip().upper(),
                "deposit_cents": deposit_cents,
                "deposit_balance_cents": deposit_cents,
                "deposit_paid_cents": 0,
                "deposit_payable": payload.deposit_due_stage.strip().upper() == "IMMEDIATELY",
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )
        merged = merge_project_plan(record)
        plan_values = {key: merged.get(key) for key in ("project_category", "recommended_project_title", "project_summary", "summary", "estimated_duration", "project_outcomes", "assumptions", "exclusions", "protections", "optional_upgrades") if merged.get(key) is not None}
        record = store.update_record("estimates", str(record["id"]), plan_values, actor_id=str(user.get("id") or ""))
        audit("ESTIMATE_CREATED", user_id=str(user.get("id") or ""), device_id=str(user.get("mobile_device_id") or ""), detail={"estimate_id": record["id"], "total_cents": total_cents})
        return document_public(record)

    @router.get("/invoices")
    def invoices(q: str = "", status: str = "", contact_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("invoices.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        status_query = status.strip().upper()
        contacts = {str(item.get("id")): item for item in store.records("contacts")}
        values = []
        for record in store.records("invoices"):
            if contact_id and str(record.get("contact_id") or "") != contact_id:
                continue
            if status_query and str(record.get("status") or "").upper() != status_query:
                continue
            contact = contacts.get(str(record.get("contact_id") or ""), {})
            haystack = " ".join(str(value or "") for value in (record.get("invoice_number"), record.get("title"), record.get("status"), contact.get("name"), contact.get("email"), contact.get("phone"))).casefold()
            if query and query not in haystack:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.get("/invoices/{invoice_id}")
    def invoice_detail(invoice_id: str, user: dict[str, Any] = permission("invoices.view")) -> dict[str, Any]:
        record = store.record("invoices", invoice_id)
        if not record:
            raise HTTPException(404, "Invoice not found")
        status = str(record.get("status") or "DRAFT").upper()
        actions = ["view_pdf", "open_customer_view"]
        if status == "DRAFT":
            actions += ["edit", "send", "delete"]
        elif status not in {"PAID", "VOID", "CANCELED"}:
            actions += ["resend", "void"]
        if _safe_int(record.get("balance_cents")) > 0 and status not in {"VOID", "CANCELED"}:
            actions += ["take_payment", "open_payment_link"]
        return {
            "invoice": document_public(record),
            "customer": contact_public(store.record("contacts", str(record.get("contact_id") or "")) or {}),
            "property": property_public(store.record("properties", str(record.get("property_id") or "")) or {}),
            "payments": [document_public(item) for item in store.records("payments") if str(item.get("invoice_id") or "") == invoice_id],
            "documents": [document_public(item) for item in store.records("documents") if str(item.get("invoice_id") or "") == invoice_id],
            "allowed_actions": actions,
        }

    @router.post("/payments/card")
    async def card_payment(payload: MobileCardPaymentRequest, request: Request, user: dict[str, Any] = permission("payments.manage")) -> dict[str, Any]:
        kind = payload.target_kind.strip().lower()
        if kind not in {"estimate", "invoice"}:
            raise HTTPException(422, "Payment target must be estimate or invoice")
        collection = "estimates" if kind == "estimate" else "invoices"
        document = store.record(collection, payload.target_id)
        if not document:
            raise HTTPException(404, f"{kind.title()} not found")
        maximum = _safe_int(document.get("deposit_balance_cents" if kind == "estimate" else "balance_cents"), 0)
        if payload.amount_cents > maximum:
            raise HTTPException(422, "Payment amount exceeds the current balance")
        if payload.save_card and not payload.authorization_reference.strip():
            raise HTTPException(422, "Record the customer's card-on-file authorization reference before processing the payment")
        contact_id = str(document.get("contact_id") or "")
        contact = store.record("contacts", contact_id) or {}
        customer = await providers.ensure_square_customer(contact)
        square_customer_id = str(customer.get("id") or "")
        if square_customer_id and contact and str(contact.get("square_customer_id") or "") != square_customer_id:
            contact = store.update_record("contacts", contact_id, {"square_customer_id": square_customer_id}, actor_id=str(user.get("id") or ""))
        processor = await providers.create_square_payment(
            source_id=payload.source_id,
            amount_cents=payload.amount_cents,
            currency=str(document.get("currency") or "USD"),
            reference_id=str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or payload.target_id),
            note=payload.note.strip() or f"Floodman Android {kind} payment",
            customer_id=square_customer_id or None,
            customer_initiated=False,
            seller_keyed_in=True,
        )
        card = dict((processor.get("card_details") or {}).get("card") or {})
        payment_record = store.create_record(
            "payments",
            {
                "contact_id": contact_id,
                "property_id": document.get("property_id"),
                "estimate_id": payload.target_id if kind == "estimate" else document.get("estimate_id"),
                "invoice_id": payload.target_id if kind == "invoice" else None,
                "amount_cents": payload.amount_cents,
                "currency": str(document.get("currency") or "USD"),
                "method": "CARD_BY_PHONE",
                "status": "COMPLETED",
                "payment_date": processor.get("created_at") or _now_iso(),
                "processor_payment_id": processor.get("id"),
                "receipt_url": processor.get("receipt_url") or "",
                "card_brand": card.get("card_brand") or card.get("brand"),
                "last_4": card.get("last_4"),
                "authorization_reference": payload.authorization_reference.strip(),
                "note": payload.note.strip(),
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )
        update: dict[str, Any]
        if kind == "estimate":
            paid = _safe_int(document.get("deposit_paid_cents")) + payload.amount_cents
            due = max(0, _safe_int(document.get("deposit_cents") or document.get("deposit_balance_cents")) - paid)
            update = {"deposit_paid_cents": paid, "deposit_balance_cents": due}
        else:
            paid = _safe_int(document.get("paid_cents")) + payload.amount_cents
            due = max(0, _safe_int(document.get("total_cents")) - paid)
            update = {"paid_cents": paid, "balance_cents": due, "status": "PAID" if due == 0 else document.get("status") or "SENT"}
        document = store.update_record(collection, payload.target_id, update, actor_id=str(user.get("id") or ""))
        saved_card = None
        if payload.save_card:
            saved_card = await providers.create_square_card_from_payment(payment_id=str(processor.get("id") or ""), customer_id=square_customer_id)
            existing_cards = list(contact.get("square_cards") or [])
            existing_cards = [item for item in existing_cards if str(item.get("id") or "") != str(saved_card.get("id") or "")]
            existing_cards.append(saved_card)
            store.update_record("contacts", contact_id, {"square_cards": existing_cards, "default_square_card_id": saved_card.get("id")}, actor_id=str(user.get("id") or ""))
        audit("CARD_PAYMENT_COMPLETED", user_id=str(user.get("id") or ""), device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"kind": kind, "target_id": payload.target_id, "amount_cents": payload.amount_cents})
        return {"payment": document_public(payment_record), "document": document_public(document), "saved_card": saved_card}

    @router.post("/payments/manual")
    def manual_payment(payload: ManualPaymentRequest, request: Request, user: dict[str, Any] = permission("payments.manage")) -> dict[str, Any]:
        kind = payload.target_kind.strip().lower()
        if kind not in {"estimate", "invoice"}:
            raise HTTPException(422, "Payment target must be estimate or invoice")
        collection = "estimates" if kind == "estimate" else "invoices"
        document = store.record(collection, payload.target_id)
        if not document:
            raise HTTPException(404, f"{kind.title()} not found")
        maximum = _safe_int(document.get("deposit_balance_cents" if kind == "estimate" else "balance_cents"), 0)
        if payload.amount_cents > maximum:
            raise HTTPException(422, "Payment amount exceeds the current balance")
        method = payload.method.strip().upper().replace(" ", "_")
        allowed = {"CASH", "CHECK", "ACH", "BANK_TRANSFER", "EXTERNAL_CARD", "OTHER"}
        if method not in allowed:
            raise HTTPException(422, "Choose a supported payment method")
        check_status = payload.check_status.strip().upper() if method == "CHECK" else None
        if check_status not in {None, "RECEIVED", "DEPOSITED", "CLEARED", "RETURNED"}:
            raise HTTPException(422, "Choose a valid check status")
        payment = store.create_record(
            "payments",
            {
                "contact_id": document.get("contact_id"),
                "property_id": document.get("property_id"),
                "estimate_id": payload.target_id if kind == "estimate" else document.get("estimate_id"),
                "invoice_id": payload.target_id if kind == "invoice" else None,
                "amount_cents": payload.amount_cents,
                "currency": str(document.get("currency") or "USD"),
                "method": method,
                "status": "COMPLETED" if check_status != "RETURNED" else "RETURNED",
                "payment_date": _now_iso(),
                "reference": payload.reference.strip(),
                "note": payload.note.strip(),
                "check_date": payload.check_date.strip() or None,
                "bank_name": payload.bank_name.strip() or None,
                "check_status": check_status,
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )
        if kind == "estimate":
            paid = _safe_int(document.get("deposit_paid_cents")) + payload.amount_cents
            due = max(0, _safe_int(document.get("deposit_cents") or document.get("deposit_balance_cents")) - paid)
            update = {"deposit_paid_cents": paid, "deposit_balance_cents": due, "deposit_status": "PAID" if due == 0 else "PARTIAL"}
        else:
            paid = _safe_int(document.get("paid_cents")) + payload.amount_cents
            due = max(0, _safe_int(document.get("total_cents")) - paid)
            update = {"paid_cents": paid, "balance_cents": due, "status": "PAID" if due == 0 else document.get("status") or "SENT"}
        updated = store.update_record(collection, payload.target_id, update, actor_id=str(user.get("id") or ""))
        audit("MANUAL_PAYMENT_RECORDED", user_id=str(user.get("id") or ""), device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"kind": kind, "target_id": payload.target_id, "amount_cents": payload.amount_cents, "method": method})
        return {"payment": document_public(payment), "document": document_public(updated), "saved_card": None}


    @router.get("/payments")
    def payments(contact_id: str = "", invoice_id: str = "", estimate_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("payments.view")) -> dict[str, Any]:
        values = []
        for record in store.records("payments"):
            if contact_id and str(record.get("contact_id") or "") != contact_id:
                continue
            if invoice_id and str(record.get("invoice_id") or "") != invoice_id:
                continue
            if estimate_id and str(record.get("estimate_id") or "") != estimate_id:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.get("/documents")
    def documents(contact_id: str = "", property_id: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("documents.view")) -> dict[str, Any]:
        values = []
        for record in store.records("documents"):
            if contact_id and str(record.get("contact_id") or "") != contact_id:
                continue
            if property_id and str(record.get("property_id") or "") != property_id:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.post("/documents/upload")
    async def upload_document(contact_id: str, property_id: str = "", kind: str = "PHOTO", file: UploadFile = File(...), user: dict[str, Any] = permission("documents.manage")) -> dict[str, Any]:
        if not store.record("contacts", contact_id):
            raise HTTPException(404, "Customer not found")
        if property_id and not store.record("properties", property_id):
            raise HTTPException(404, "Property not found")
        content = await file.read()
        if not content or len(content) > settings.max_upload_bytes:
            raise HTTPException(413, "Upload is empty or too large")
        file_id, saved = store.save_upload(file.filename or "upload.bin", content)
        return store.create_record(
            "documents",
            {
                "contact_id": contact_id,
                "property_id": property_id or None,
                "kind": kind.strip().upper() or "PHOTO",
                "title": Path(saved.name).stem,
                "filename": saved.name,
                "file_id": file_id,
                "download_url": f"/office/uploads/{file_id}/{saved.name}",
                "mime_type": file.content_type or "application/octet-stream",
                "status": "UPLOADED",
                "source": "FLOODMAN_ANDROID",
            },
            actor_id=str(user.get("id") or ""),
        )

    @router.get("/documents/{document_id}/download")
    def download_document(document_id: str, signed: bool = False, user: dict[str, Any] = permission("documents.view")) -> FileResponse:
        record = store.record("documents", document_id)
        if not record:
            raise HTTPException(404, "Document not found")
        file_id = str(record.get("signed_file_id") if signed else record.get("file_id") or "")
        filename = str(record.get("signed_filename") if signed else record.get("filename") or "")
        if not file_id or not filename:
            raise HTTPException(404, "Document file is not available")
        path = store.upload_path(file_id, filename)
        if not path.exists() or not path.is_file():
            raise HTTPException(404, "Document file is missing")
        return FileResponse(path, media_type=str(record.get("mime_type") or "application/octet-stream"), filename=filename)


    def _roomflow_detail_payload(record: dict[str, Any]) -> dict[str, Any]:
        contact = store.record("contacts", str(record.get("contact_id") or ""))
        prop = store.record("properties", str(record.get("property_id") or ""))
        estimate = store.record("estimates", str(record.get("estimate_id") or ""))
        workspace = store.record("roomflow_workspaces", str(record.get("workspace_id") or ""))
        path = layout_path(store, record)
        return {
            "job": document_public(record),
            "customer": contact_public(contact) if contact else None,
            "property": property_public(prop) if prop else None,
            "estimate": document_public(estimate) if estimate else None,
            "workspace": workspace_public(workspace) if workspace else None,
            "layout_available": bool(path),
            "layout_url": f"{API_PREFIX}/roomflow/jobs/{record['id']}/layout" if path else None,
            "layout_capture_required": bool(record.get("layout_capture_required") and not path),
        }

    def _roomflow_workspace_context(user: dict[str, Any], preferred_workspace_id: str = "") -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
        actor_id = str(user.get("id") or "")
        workspaces = ensure_roomflow_workspaces(store, actor_id=actor_id)
        selected_id = selected_roomflow_workspace_id(
            store,
            actor_id,
            preferred_workspace_id=preferred_workspace_id,
            actor_id=actor_id,
        )
        active = next((record for record in workspaces if str(record.get("id") or "") == selected_id), workspaces[0])
        return workspaces, selected_id, active

    def _roomflow_bootstrap_payload(user: dict[str, Any], preferred_workspace_id: str = "") -> dict[str, Any]:
        workspaces, selected_id, active = _roomflow_workspace_context(user, preferred_workspace_id)
        jobs = [
            _roomflow_detail_payload(record)
            for record in store.records("roomflow_jobs")
            if str(record.get("workspace_id") or "") == selected_id
        ][:500]
        catalog = [
            document_public(record)
            for record in store.records("catalog_items")
            if bool(record.get("active", True))
            and str(record.get("workspace_id") or "") in {"", selected_id}
        ][:2_000]
        imports = [document_public(record) for record in store.records("roomflow_imports")[:10]]
        return {
            "api_version": API_VERSION,
            "server_release": settings.release,
            "minimum_android_version": MIN_ANDROID_VERSION,
            "minimum_ios_version": MIN_IOS_VERSION,
            "capabilities": MOBILE_CAPABILITIES,
            "workspaces": [workspace_public(record) for record in workspaces],
            "selected_workspace_id": selected_id,
            "active_workspace": workspace_public(active),
            "jobs": jobs,
            "catalog": catalog,
            "imports": imports,
        }

    @router.get("/roomflow/bootstrap")
    def roomflow_bootstrap(user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        return _roomflow_bootstrap_payload(user)

    @router.get("/roomflow/workspaces")
    def roomflow_workspaces(user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        workspaces, selected_id, active = _roomflow_workspace_context(user)
        return {
            "items": [workspace_public(record) for record in workspaces],
            "selected_workspace_id": selected_id,
            "active_workspace": workspace_public(active),
        }

    @router.post("/roomflow/workspaces")
    def create_roomflow_workspace_route(
        payload: RoomFlowWorkspaceCreateRequest,
        user: dict[str, Any] = permission("estimates.manage"),
    ) -> dict[str, Any]:
        actor_id = str(user.get("id") or "")
        try:
            workspace = create_roomflow_workspace(
                store,
                name=payload.name,
                timezone=payload.timezone,
                user_id=actor_id,
                actor_id=actor_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {
            "workspace": workspace_public(workspace),
            "bootstrap": _roomflow_bootstrap_payload(user, str(workspace["id"])),
        }

    @router.post("/roomflow/workspaces/{workspace_id}/select")
    def select_roomflow_workspace_route(
        workspace_id: str,
        user: dict[str, Any] = permission("estimates.view"),
    ) -> dict[str, Any]:
        actor_id = str(user.get("id") or "")
        try:
            workspace = select_roomflow_workspace(store, actor_id, workspace_id, actor_id=actor_id)
        except KeyError as exc:
            raise HTTPException(404, "RoomFlow workspace not found") from exc
        return {
            "workspace": workspace_public(workspace),
            "bootstrap": _roomflow_bootstrap_payload(user, workspace_id),
        }

    @router.get("/roomflow/imports")
    def roomflow_import_history(user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        return {"items": [document_public(record) for record in store.records("roomflow_imports")[:25]]}

    @router.post("/roomflow/import/supabase")
    def roomflow_supabase_import(
        payload: RoomFlowSupabaseImportRequest,
        request: Request,
        user: dict[str, Any] = permission("estimates.manage"),
    ) -> dict[str, Any]:
        actor_id = str(user.get("id") or "")
        try:
            result = import_roomflow_supabase(
                store,
                email=payload.email,
                password=payload.password,
                actor_id=actor_id,
                supabase_url=DEFAULT_ROOMFLOW_SUPABASE_URL,
                supabase_anon_key=DEFAULT_ROOMFLOW_SUPABASE_ANON_KEY,
            )
        except RoomFlowSupabaseError as exc:
            audit(
                "ROOMFLOW_SUPABASE_IMPORT_FAILED",
                user_id=actor_id,
                device_id=str(user.get("mobile_device_id") or ""),
                request=request,
                detail={"reason": str(exc)[:500]},
            )
            raise HTTPException(422, str(exc)) from exc
        audit(
            "ROOMFLOW_SUPABASE_IMPORT_COMPLETED",
            user_id=actor_id,
            device_id=str(user.get("mobile_device_id") or ""),
            request=request,
            detail={"run_id": result.get("run_id"), "counts": result.get("counts")},
        )
        selected_id = str(result.get("selected_workspace_id") or "")
        return {**result, "bootstrap": _roomflow_bootstrap_payload(user, selected_id)}

    @router.get("/roomflow/jobs")
    def roomflow_jobs(q: str = "", page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        _, selected_id, _ = _roomflow_workspace_context(user)
        values = []
        for record in store.records("roomflow_jobs"):
            if str(record.get("workspace_id") or "") != selected_id:
                continue
            haystack = " ".join(str(record.get(key) or "") for key in ("name", "job_name", "customer_name", "property_address", "estimate_number", "status")).casefold()
            if query and query not in haystack:
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)


    def _resolve_roomflow_workspace(
        payload: RoomFlowSaveRequest,
        user: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        actor_id = str(user.get("id") or "")
        preferred = str(payload.workspace_id or (existing or {}).get("workspace_id") or "").strip()
        workspaces, selected_id, active = _roomflow_workspace_context(user, preferred)
        if preferred:
            active = next((record for record in workspaces if str(record.get("id") or "") == preferred), None)
            if not active:
                raise HTTPException(422, "Select a valid RoomFlow workspace before saving.")
            selected_id = preferred
            select_roomflow_workspace(store, actor_id, preferred, actor_id=actor_id)
        return selected_id, active

    def _roomflow_identity(
        payload: RoomFlowSaveRequest,
        workspace_id: str,
        user: dict[str, Any],
    ) -> tuple[str, str]:
        actor_id = str(user.get("id") or "")
        contact_id = str(payload.contact_id or "").strip()
        property_id = str(payload.property_id or "").strip()
        snapshot = payload.snapshot if isinstance(payload.snapshot, dict) else {}
        costing = snapshot.get("costing") if isinstance(snapshot.get("costing"), dict) else {}
        customer_name = _clean_text(payload.customer_name or costing.get("customerName") or snapshot.get("customerName"), 300)
        customer_email = _clean_text(payload.customer_email or costing.get("customerEmail") or snapshot.get("customerEmail"), 320).lower()
        customer_phone = _clean_text(payload.customer_phone or costing.get("customerPhone") or snapshot.get("customerPhone"), 80)
        property_address = _clean_text(payload.property_address or costing.get("customerAddress") or snapshot.get("customerAddress"), 500)

        if contact_id:
            requested_contact = store.record("contacts", contact_id)
            if not requested_contact or str(requested_contact.get("workspace_id") or "") not in {"", workspace_id}:
                contact_id = ""
        if not contact_id:
            incoming_digits = re.sub(r"\D", "", customer_phone)[-10:]
            candidates = sorted(
                store.records("contacts"),
                key=lambda item: 0 if str(item.get("workspace_id") or "") == workspace_id else 1,
            )
            for candidate in candidates:
                candidate_workspace = str(candidate.get("workspace_id") or "")
                if candidate_workspace not in {"", workspace_id}:
                    continue
                if customer_email and str(candidate.get("email") or "").strip().lower() == customer_email:
                    contact_id = str(candidate["id"])
                    break
                candidate_digits = re.sub(r"\D", "", str(candidate.get("phone") or candidate.get("mobile_phone") or ""))[-10:]
                if incoming_digits and candidate_digits == incoming_digits:
                    contact_id = str(candidate["id"])
                    break
        if not contact_id:
            parts = customer_name.split(None, 1)
            contact = store.create_record(
                "contacts",
                {
                    "first_name": parts[0] if parts else "RoomFlow",
                    "last_name": parts[1] if len(parts) > 1 else "Customer",
                    "name": customer_name or "RoomFlow Customer",
                    "email": customer_email,
                    "phone": customer_phone,
                    "workspace_id": workspace_id,
                    "source": "ROOMFLOW_NATIVE",
                    "status": "CUSTOMER",
                },
                actor_id=actor_id,
            )
            contact_id = str(contact["id"])
        else:
            contact = store.record("contacts", contact_id) or {}
            if not contact.get("workspace_id"):
                store.update_record("contacts", contact_id, {"workspace_id": workspace_id}, actor_id=actor_id)

        if property_id:
            existing_property = store.record("properties", property_id)
            if (
                not existing_property
                or str(existing_property.get("contact_id") or "") != contact_id
                or str(existing_property.get("workspace_id") or "") not in {"", workspace_id}
            ):
                property_id = ""
        if not property_id and property_address:
            incoming_address = property_address.strip().casefold()
            for candidate in store.records("properties"):
                candidate_workspace = str(candidate.get("workspace_id") or "")
                if candidate_workspace not in {"", workspace_id}:
                    continue
                candidate_address = str(
                    candidate.get("full_address")
                    or candidate.get("service_address")
                    or " ".join(
                        str(candidate.get(key) or "")
                        for key in ("service_street", "service_city", "service_state", "service_postal_code")
                    )
                ).strip().casefold()
                if str(candidate.get("contact_id") or "") == contact_id and candidate_address == incoming_address:
                    property_id = str(candidate["id"])
                    break
        if not property_id:
            prop = store.create_record(
                "properties",
                {
                    "contact_id": contact_id,
                    "name": payload.job_name.strip() or "RoomFlow Service Property",
                    "property_name": payload.job_name.strip() or "RoomFlow Service Property",
                    "service_street": property_address,
                    "full_address": property_address,
                    "service_address": property_address,
                    "property_type": "SERVICE_PROPERTY",
                    "workspace_id": workspace_id,
                    "source": "ROOMFLOW_NATIVE",
                },
                actor_id=actor_id,
            )
            property_id = str(prop["id"])
        else:
            prop = store.record("properties", property_id) or {}
            if not prop.get("workspace_id"):
                store.update_record("properties", property_id, {"workspace_id": workspace_id}, actor_id=actor_id)
        return contact_id, property_id


    def _roomflow_estimate(
        payload: RoomFlowSaveRequest,
        job_id: str,
        contact_id: str,
        property_id: str,
        workspace_id: str,
        user: dict[str, Any],
        *,
        preferred_estimate_id: str = "",
    ) -> dict[str, Any] | None:
        estimate_id = preferred_estimate_id or str(payload.estimate_id or "").strip()
        if estimate_id:
            requested_estimate = store.record("estimates", estimate_id)
            if requested_estimate and str(requested_estimate.get("workspace_id") or "") not in {"", workspace_id}:
                estimate_id = ""
        if not payload.sync_estimate or not payload.sections:
            return store.record("estimates", estimate_id) if estimate_id else None

        sections: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        total_cents = 0
        actor_id = str(user.get("id") or "")

        def ensure_catalog_item(line: CatalogLine, unit_price_cents: int) -> str | None:
            existing_id = str(line.catalog_item_id or "").strip()
            if existing_id:
                existing_catalog = store.record("catalog_items", existing_id)
                if existing_catalog and str(existing_catalog.get("workspace_id") or "") in {"", workspace_id}:
                    return existing_id
                existing_id = ""
            if not line.save_to_catalog:
                return existing_id or None
            wanted_name = line.name.strip().casefold()
            wanted_category = (line.category.strip() or "General Services").casefold()
            wanted_unit = (line.unit.strip() or "each").casefold()
            for candidate in store.records("catalog_items"):
                if not bool(candidate.get("active", True)):
                    continue
                if str(candidate.get("workspace_id") or "") not in {"", workspace_id}:
                    continue
                if str(candidate.get("name") or "").strip().casefold() != wanted_name:
                    continue
                if str(candidate.get("category") or "General Services").strip().casefold() != wanted_category:
                    continue
                if str(candidate.get("unit") or "each").strip().casefold() != wanted_unit:
                    continue
                candidate_price = _safe_int(candidate.get("unit_price_cents"), int(round(_safe_float(candidate.get("unit_price"), 0.0) * 100)))
                if candidate_price == unit_price_cents:
                    return str(candidate.get("id") or "") or None
            created = store.create_record(
                "catalog_items",
                {
                    "name": line.name.strip(),
                    "description": line.description.strip(),
                    "category": line.category.strip() or "General Services",
                    "unit": line.unit.strip() or "each",
                    "unit_price_cents": unit_price_cents,
                    "unit_price": unit_price_cents / 100,
                    "taxable": bool(line.taxable),
                    "active": True,
                    "source_provider": "FLOODMAN_ROOMFLOW_NATIVE",
                    "external_key": f"roomflow-native-{uuid.uuid4()}",
                    "workspace_id": workspace_id,
                },
                actor_id=actor_id,
            )
            return str(created.get("id") or "") or None

        for section_index, section in enumerate(payload.sections):
            section_id = str(uuid.uuid4())
            section_total = 0
            sections.append(
                {
                    "id": section_id,
                    "title": section.title.strip(),
                    "description": section.description.strip(),
                    "sort_order": section_index,
                }
            )
            for line_index, line in enumerate(section.lines):
                quantity = max(0.0, _safe_float(line.quantity, 0.0))
                unit_price_cents = max(0, _safe_int(line.unit_price_cents))
                line_total_cents = int(round(quantity * unit_price_cents))
                catalog_item_id = ensure_catalog_item(line, unit_price_cents)
                lines.append(
                    {
                        "id": str(uuid.uuid4()),
                        "section_id": section_id,
                        "section_name": section.title.strip(),
                        "catalog_item_id": catalog_item_id,
                        "name": line.name.strip(),
                        "description": line.description.strip(),
                        "category": line.category.strip() or "General Services",
                        "unit": line.unit.strip() or "each",
                        "quantity": quantity,
                        "unit_price_cents": unit_price_cents,
                        "unit_price": unit_price_cents / 100,
                        "line_total_cents": line_total_cents,
                        "taxable": bool(line.taxable),
                        "optional": bool(line.optional),
                        "sort_order": line_index,
                    }
                )
                if not line.optional:
                    section_total += line_total_cents
            sections[-1]["subtotal_cents"] = section_total
            total_cents += section_total

        values = merge_project_plan(
            {
                "contact_id": contact_id,
                "property_id": property_id,
                "workspace_id": workspace_id,
                "title": payload.title.strip() or payload.job_name.strip() or "RoomFlow Estimate",
                "project_category": payload.project_category.strip() or "general-restoration",
                "status": "DRAFT",
                "currency": "USD",
                "sections": sections,
                "line_items": lines,
                "total_cents": total_cents,
                "roomflow_job_id": job_id,
                "source": "ROOMFLOW_NATIVE",
            }
        )
        if estimate_id and store.record("estimates", estimate_id):
            return store.update_record("estimates", estimate_id, values, actor_id=actor_id)

        values["estimate_number"] = payload.estimate_number.strip() or next_estimate_number()
        values.update(
            {
                "deposit_type": "PERCENT",
                "deposit_percent": 50.0,
                "deposit_cents": int(round(total_cents * 0.5)),
                "deposit_balance_cents": int(round(total_cents * 0.5)),
                "deposit_paid_cents": 0,
                "deposit_due_stage": "AFTER_AUTHORIZATION",
            }
        )
        return store.create_record("estimates", values, actor_id=actor_id)

    @router.get("/roomflow/jobs/{job_id}")
    def roomflow_job(job_id: str, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        record = store.record("roomflow_jobs", job_id)
        _, selected_workspace_id, _ = _roomflow_workspace_context(user)
        if not record or str(record.get("workspace_id") or "") != selected_workspace_id:
            raise HTTPException(404, "RoomFlow job not found")
        return _roomflow_detail_payload(record)

    def _capture_error(exc: Exception) -> None:
        if isinstance(exc, CaptureOperationNotFound):
            raise HTTPException(404, str(exc).strip("'")) from exc
        if isinstance(exc, CaptureOperationConflict):
            raise HTTPException(409, str(exc)) from exc
        raise HTTPException(422, str(exc)) from exc

    @router.get("/roomflow/jobs/{job_id}/capture/rooms")
    def capture_rooms(job_id: str, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        try:
            return {"schemaVersion": 2, "items": capture_service.list_rooms(workspace_id=workspace_id, job_id=job_id)}
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    @router.get("/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
    def capture_room(job_id: str, room_id: str, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        try:
            return capture_service.get_room(workspace_id=workspace_id, job_id=job_id, room_id=room_id)
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    @router.post("/roomflow/jobs/{job_id}/capture/rooms")
    def create_capture_room(job_id: str, payload: dict[str, Any], user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        room = payload.get("room") if isinstance(payload.get("room"), dict) else payload
        try:
            return capture_service.apply(
                action="CREATE",
                operation_id=str(payload.get("operationId") or ""),
                workspace_id=workspace_id,
                job_id=job_id,
                actor_id=str(user.get("id") or ""),
                room_id=str(payload.get("roomId") or room.get("roomId") or room.get("id") or ""),
                expected_revision=int(payload.get("expectedRevision") or 0),
                room=room,
            )
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    @router.put("/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
    def update_capture_room(job_id: str, room_id: str, payload: dict[str, Any], user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        room = payload.get("room") if isinstance(payload.get("room"), dict) else payload
        try:
            return capture_service.apply(
                action="UPDATE",
                operation_id=str(payload.get("operationId") or ""),
                workspace_id=workspace_id,
                job_id=job_id,
                actor_id=str(user.get("id") or ""),
                room_id=room_id,
                expected_revision=int(payload.get("expectedRevision") or 0),
                room=room,
            )
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    @router.delete("/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
    def delete_capture_room(
        job_id: str,
        room_id: str,
        operation_id: str,
        expected_revision: int,
        user: dict[str, Any] = permission("estimates.manage"),
    ) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        try:
            return capture_service.apply(
                action="DELETE",
                operation_id=operation_id,
                workspace_id=workspace_id,
                job_id=job_id,
                actor_id=str(user.get("id") or ""),
                room_id=room_id,
                expected_revision=expected_revision,
            )
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    @router.post("/roomflow/jobs/{job_id}/capture/operations")
    def replay_capture_operations(job_id: str, payload: dict[str, Any], user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        _, workspace_id, _ = _roomflow_workspace_context(user)
        try:
            return capture_service.apply_batch(
                workspace_id=workspace_id,
                job_id=job_id,
                actor_id=str(user.get("id") or ""),
                operations=payload.get("operations") if isinstance(payload.get("operations"), list) else [],
            )
        except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
            _capture_error(exc)

    def _save_roomflow_job(
        payload: RoomFlowSaveRequest,
        user: dict[str, Any],
        *,
        existing_id: str = "",
    ) -> dict[str, Any]:
        existing = store.record("roomflow_jobs", existing_id) if existing_id else None
        if existing_id and not existing:
            raise HTTPException(404, "RoomFlow job not found")
        requested_workspace_id = str(payload.workspace_id or "").strip()
        existing_workspace_id = str((existing or {}).get("workspace_id") or "")
        if existing and requested_workspace_id and existing_workspace_id and requested_workspace_id != existing_workspace_id:
            raise HTTPException(409, "A RoomFlow job cannot be moved between company workspaces. Start a new job in the selected company.")
        if existing and existing_workspace_id:
            _, selected_workspace_id, _ = _roomflow_workspace_context(user)
            if existing_workspace_id != selected_workspace_id:
                raise HTTPException(404, "RoomFlow job not found")
        workspace_id, workspace = _resolve_roomflow_workspace(payload, user, existing)
        contact_id, property_id = _roomflow_identity(payload, workspace_id, user)
        job_id = existing_id or str(uuid.uuid4())
        layout_values: dict[str, Any] = {}
        if payload.layout_data_url.strip():
            try:
                layout_values = store_layout_image(
                    store,
                    payload.layout_data_url,
                    filename=f"roomflow-{job_id}.jpg",
                ) or {}
            except ValueError as error:
                raise HTTPException(413, str(error)) from error

        preferred_estimate_id = str((existing or {}).get("estimate_id") or payload.estimate_id or "").strip()
        estimate = _roomflow_estimate(
            payload,
            job_id,
            contact_id,
            property_id,
            workspace_id,
            user,
            preferred_estimate_id=preferred_estimate_id,
        )
        customer = store.record("contacts", contact_id) or {}
        prop = store.record("properties", property_id) or {}
        snapshot = deepcopy(payload.snapshot if isinstance(payload.snapshot, dict) else {})
        snapshot["workspaceId"] = workspace_id
        snapshot["organizationId"] = workspace_id
        snapshot["currentOrganization"] = workspace_public(workspace)
        values = {
            "roomflow_job_id": str(payload.roomflow_job_id or (existing or {}).get("roomflow_job_id") or job_id),
            "job_name": payload.job_name.strip() or str((existing or {}).get("job_name") or "RoomFlow Job"),
            "name": payload.job_name.strip() or str((existing or {}).get("name") or "RoomFlow Job"),
            "contact_id": contact_id,
            "property_id": property_id,
            "workspace_id": workspace_id,
            "roomflow_organization_id": workspace.get("roomflow_organization_id"),
            "roomflow_organization_name": workspace.get("name"),
            "estimate_id": str((estimate or {}).get("id") or preferred_estimate_id or "") or None,
            "estimate_number": str((estimate or {}).get("estimate_number") or payload.estimate_number or ""),
            "status": payload.status.strip().upper() or "DRAFT",
            "project_category": payload.project_category.strip() or "general-restoration",
            "customer_name": str(customer.get("name") or customer.get("company") or payload.customer_name or ""),
            "property_address": str(
                prop.get("full_address")
                or prop.get("service_address")
                or payload.property_address
                or ""
            ),
            "snapshot": snapshot,
            "summary": payload.summary,
            "sections": [section.model_dump(mode="json") for section in payload.sections],
            "source": "ROOMFLOW_NATIVE",
            "layout_capture_required": False if layout_values else bool((existing or {}).get("layout_capture_required")),
            **layout_values,
        }
        actor_id = str(user.get("id") or "")
        if existing:
            job = store.update_record("roomflow_jobs", job_id, values, actor_id=actor_id)
        else:
            job = store.create_record("roomflow_jobs", {**values, "id": job_id}, actor_id=actor_id)
        if estimate and str(estimate.get("roomflow_job_id") or "") != job_id:
            estimate = store.update_record("estimates", str(estimate["id"]), {"roomflow_job_id": job_id}, actor_id=actor_id)
        return {
            "job": document_public(job),
            "customer": contact_public(customer),
            "property": property_public(prop),
            "estimate": document_public(estimate) if estimate else None,
            "workspace": workspace_public(workspace),
            "layout_available": bool(layout_path(store, job)),
        }

    @router.post("/roomflow/jobs")
    def create_roomflow_job(payload: RoomFlowSaveRequest, user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        return _save_roomflow_job(payload, user)

    @router.put("/roomflow/jobs/{job_id}")
    def update_roomflow_job(job_id: str, payload: RoomFlowSaveRequest, user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        return _save_roomflow_job(payload, user, existing_id=job_id)

    @router.get("/roomflow/jobs/{job_id}/layout")
    def roomflow_layout(job_id: str, user: dict[str, Any] = permission("estimates.view")) -> FileResponse:
        record = store.record("roomflow_jobs", job_id)
        _, selected_workspace_id, _ = _roomflow_workspace_context(user)
        if not record or str(record.get("workspace_id") or "") != selected_workspace_id:
            raise HTTPException(404, "RoomFlow job not found")
        path = layout_path(store, record)
        if not path:
            raise HTTPException(404, "RoomFlow layout is not available")
        return FileResponse(path, media_type="image/jpeg", filename=path.name)

    @router.get("/tasks")
    def tasks(assigned_to_me: bool = True, page: int = 1, page_size: int = 50, user: dict[str, Any] = permission("tasks.view")) -> dict[str, Any]:
        values = []
        for record in store.records("tasks"):
            assigned = str(record.get("assigned_user_id") or record.get("user_id") or "")
            if assigned_to_me and assigned and assigned != str(user.get("id") or ""):
                continue
            values.append(document_public(record))
        return _paginate(values, page, page_size)

    @router.get("/time/status")
    def time_status(user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        if not (has_permission(user, "time.self") or has_permission(user, "time.view") or has_permission(user, "time.manage")):
            raise HTTPException(403, "Time permission required")
        return {"clock": store.current_clock(str(user.get("id") or ""))}

    @router.post("/time/clock-in")
    def clock_in(payload: ClockRequest, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        if not (has_permission(user, "time.self") or has_permission(user, "time.manage")):
            raise HTTPException(403, "Time permission required")
        return store.clock_in(str(user.get("id") or ""), payload.job_reference, payload.note)

    @router.post("/time/clock-out")
    def clock_out(payload: ClockRequest, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        if not (has_permission(user, "time.self") or has_permission(user, "time.manage")):
            raise HTTPException(403, "Time permission required")
        value = store.clock_out(str(user.get("id") or ""), payload.note)
        if not value:
            raise HTTPException(409, "You are not currently clocked in")
        return value

    router.include_router(build_operations_router(
        store, providers, settings,
        require_mobile_user=require_mobile_user, permission=permission, audit=audit,
    ))
    return router
