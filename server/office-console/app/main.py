from __future__ import annotations

import asyncio
import hashlib
import io
import html
import json
import mimetypes
import os
import zipfile
import re
import secrets
import uuid
from collections import defaultdict
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response, StreamingResponse
from pydantic import ValidationError

from .auth import ROLE_PERMISSIONS, has_permission
from .call_intake import CallIntakeLinksRequest, CallIntakeProjectionRequest
from .config import Settings
from .customer_csv import CustomerCsvError, customer_template, parse_customer_csv
from .estimate_catalog import default_document, document_payload, group_document_lines, normalize_catalog_item, normalize_document_payload
from .importer import (
    ImportValidationError,
    bundle_files,
    create_zip,
    sample_files,
    template_files,
    unpack_zip,
    validate,
)
from .providers import ProviderClient
from .pdf_documents import build_estimate_pdf, build_invoice_pdf, calculate_deposit
from .project_plans import merge_project_plan, project_plan, project_plan_options
from .roomflow_assets import enrich_estimate_with_roomflow, store_layout_image
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
from .customer_portal import page as customer_page, grouped_lines as customer_grouped_lines, payment_page as customer_payment_page
from .security import SignedRequestError, verify_signed_body
from .store import CaptureOperationConflict, CaptureOperationNotFound, OfficeStore
from .mobile_api import build_mobile_router
from .ui import badge, esc, json_pre, layout, money_cents, money_units, progress, simple_page, table
from .xactimate_catalog import (
    IMPORT_KIND as XACTIMATE_IMPORT_KIND,
    MAX_ROWS as XACTIMATE_MAX_ROWS,
    MAX_UPLOAD_BYTES as XACTIMATE_MAX_UPLOAD_BYTES,
    ProtectedXactimatePlxError,
    SOURCE_PROVIDER as XACTIMATE_SOURCE_PROVIDER,
    XactimateCatalogError,
    parse_xactimate_catalog_upload,
    xactimate_catalog_template,
)


settings = Settings.from_env()
store = OfficeStore(settings.data_dir)
roomflow_capture_service = RoomFlowCaptureService(store)
providers = ProviderClient(settings)
app = FastAPI(title="Floodman Operations", version="4.7.3", docs_url=None, redoc_url=None)
_current_user: ContextVar[dict[str, Any] | None] = ContextVar("office_current_user", default=None)
app.include_router(build_mobile_router(store, providers, settings))

PUBLIC_PATHS = {
    "/health/live",
    "/health/ready",
    "/login",
    "/login/local",
    "/login/platform",
    "/login/gauzy",
    "/login/erp-session",
    "/login/status",
    "/logout",
    "/setup/owner",
    "/office/api/erp/login",
    "/office/api/roomflow/auth-check",
}
PUBLIC_PREFIXES = ("/invite/", "/customer/", "/mobile-api/")


@app.middleware("http")
async def office_auth(request: Request, call_next):
    path = request.url.path
    if path.startswith("/internal/v1/"):
        return await call_next(request)
    if not settings.auth_enabled:
        token = _current_user.set(store.list_users()[0] if store.has_users() else None)
        try:
            return await call_next(request)
        finally:
            _current_user.reset(token)
    if not store.has_users():
        if path not in PUBLIC_PATHS and path != "/setup" and not any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            return RedirectResponse("/setup", status_code=303)
        token = _current_user.set(None)
        try:
            return await call_next(request)
        finally:
            _current_user.reset(token)
    user = store.user_for_session(request.cookies.get("floodman_session"))
    is_public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
    if not user and not is_public:
        return RedirectResponse(f"/login?next={quote(path, safe='/')}", status_code=303)
    token = _current_user.set(user)
    request.state.user = user
    try:
        return await call_next(request)
    finally:
        _current_user.reset(token)


def _user() -> dict[str, Any] | None:
    return _current_user.get()


def _require(permission: str) -> dict[str, Any]:
    user = _user()
    if not has_permission(user, permission):
        raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
    return user or {}


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "floodman-office-console", "version": "4.7.3"}


@app.get("/health/ready")
async def ready() -> dict[str, Any]:
    try:
        state = _merge_archive_state(await providers.lab_state())
        return {"status": "ready", "local_lab": True, "test_job_id": state.get("test_job_id") or state.get("demo_job_id")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc




async def _reconcile_local_signatures_once() -> int:
    """Attach completed local signing envelopes to the matching customer file."""
    completed = 0
    for record in store.records("documents"):
        envelope_id = str(record.get("envelope_id") or "").strip()
        if not envelope_id or str(record.get("status") or "").upper() in {"COMPLETED", "SIGNED", "EXECUTED"}:
            continue
        try:
            envelope = await providers.get_signing_envelope(envelope_id)
            status = str(envelope.get("status") or "").upper()
            if status not in {"COMPLETED", "SIGNED", "EXECUTED"}:
                continue
            items = list(envelope.get("items") or [])
            item_id = str((items[0] if items else {}).get("id") or "")
            if not item_id:
                continue
            signed_pdf = await providers.download_signing_item(item_id)
            if not signed_pdf.startswith(b"%PDF"):
                raise RuntimeError("The signing provider did not return a PDF")
            digest = hashlib.sha256(signed_pdf).hexdigest()
            signed_name = f"signed-{Path(str(record.get('filename') or 'document.pdf')).name}"
            file_id, saved = store.save_upload(signed_name, signed_pdf)
            contact_id = str(record.get("contact_id") or "")
            if not contact_id:
                contact, _ = store.ensure_workflow_client(
                    customer={
                        "name": record.get("recipient_name"),
                        "email": record.get("recipient_email"),
                    },
                    property_data=None,
                    external_contact_id=None,
                    external_project_id=None,
                )
                contact_id = str(contact.get("id") or "")
            store.update_record(
                "documents",
                str(record["id"]),
                {
                    "status": "COMPLETED",
                    "contact_id": contact_id or None,
                    "completed_at": envelope.get("completedAt") or datetime.now(UTC).isoformat(),
                    "signed_pdf_sha256": digest,
                    "signed_file_id": file_id,
                    "signed_filename": saved.name,
                    "signed_download_url": f"/office/uploads/{file_id}/{quote(saved.name)}",
                    "provider_response": envelope,
                    "attached_to_client_file": bool(contact_id),
                },
                actor_id="floodman-signing",
            )
            completed += 1
        except Exception:
            # Reconciliation is retried by the background loop. A single provider
            # error must never prevent the Office application from starting.
            continue
    return completed


async def _signature_reconciliation_loop() -> None:
    while True:
        try:
            await _reconcile_local_signatures_once()
        except Exception:
            pass
        await asyncio.sleep(30)


_signature_reconciliation_task: asyncio.Task[Any] | None = None


@app.on_event("startup")
async def start_signature_reconciliation() -> None:
    global _signature_reconciliation_task
    _signature_reconciliation_task = asyncio.create_task(_signature_reconciliation_loop())


@app.on_event("shutdown")
async def stop_signature_reconciliation() -> None:
    global _signature_reconciliation_task
    if _signature_reconciliation_task:
        _signature_reconciliation_task.cancel()
        try:
            await _signature_reconciliation_task
        except (asyncio.CancelledError, Exception):
            pass
        _signature_reconciliation_task = None


@app.post("/internal/v1/client-files/attach")
async def attach_signed_document_to_client_file(request: Request) -> dict[str, Any]:
    body = await request.body()
    try:
        verify_signed_body(request.headers, body, settings.internal_hmac_keys, max_age_seconds=300)
        payload = json.loads(body or b"{}")
    except (SignedRequestError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    document_id = str(payload.get("workflow_document_id") or "").strip()
    stored_path = str(payload.get("stored_path") or "").strip()
    signed_hash = str(payload.get("signed_pdf_sha256") or "").strip().lower()
    if not document_id or not stored_path or len(signed_hash) != 64:
        raise HTTPException(422, "Signed document ID, immutable path, and SHA-256 are required")

    contact, property_record = store.ensure_workflow_client(
        customer=dict(payload.get("customer") or {}),
        property_data=dict(payload.get("property") or {}),
        external_contact_id=str(payload.get("floodman_contact_id") or "") or None,
        external_project_id=str(payload.get("floodman_project_id") or "") or None,
    )
    record = store.upsert_client_file(
        {
            "id": document_id,
            "workflow_document_id": document_id,
            "job_id": str(payload.get("job_id") or ""),
            "contact_id": contact["id"],
            "property_id": (property_record or {}).get("id"),
            "document_type": str(payload.get("kind") or "SIGNED_DOCUMENT"),
            "title": str(payload.get("title") or "Signed Floodman document"),
            "revision": int(payload.get("revision") or 1),
            "status": "COMPLETED",
            "recipient_name": str(payload.get("recipient_name") or ""),
            "recipient_email": str(payload.get("recipient_email") or "").lower(),
            "envelope_id": str(payload.get("envelope_id") or ""),
            "completed_at": payload.get("completed_at") or datetime.now(UTC).isoformat(),
            "signed_pdf_sha256": signed_hash,
            "signed_stored_path": stored_path,
            "signed_download_url": f"/office/client-files/{document_id}/download",
            "floodman_contact_id": payload.get("floodman_contact_id"),
            "floodman_project_id": payload.get("floodman_project_id"),
            "floodman_estimate_id": payload.get("floodman_estimate_id"),
            "floodman_invoice_id": payload.get("floodman_invoice_id"),
            "source": "FLOODMAN_SIGNING",
            "created_by_name": "Josh Aldrich",
            "creator_display": "Created by Josh Aldrich",
        }
    )
    return {
        "status": "ATTACHED",
        "client_file_id": record["id"],
        "contact_id": contact["id"],
        "property_id": (property_record or {}).get("id"),
    }


async def _deliver_call_intake_notifications(result: dict[str, Any]) -> None:
    """Deliver staff email/SMS after the durable Office projection has committed."""

    intake_id = str(result.get("intake_id") or result.get("id") or "")
    caller = dict(result.get("caller") or {})
    caller_name = str(caller.get("name") or "").strip() or "Incoming caller"
    summary = str(result.get("summary") or result.get("service_reason") or "Open Floodman for call details.")
    action_url = f"{settings.public_url.rstrip('/')}/office/calls/{quote(intake_id)}"
    for notification_id in result.get("notification_ids") or []:
        notification = store.record("notifications", str(notification_id))
        if not notification:
            continue
        user = store.get_user(str(notification.get("user_id") or "")) or {}
        email = str(user.get("email") or "").strip()
        if str(notification.get("email_status") or "") == "PENDING":
            try:
                await providers.send_email(
                    to=email,
                    subject=f"Floodman incoming call: {caller_name}",
                    text=f"{summary}\n\nOpen the live call intake: {action_url}",
                )
                store.update_record(
                    "notifications",
                    str(notification_id),
                    {"email_status": "SENT", "email_sent_at": datetime.now(UTC).isoformat()},
                    actor_id="floodman-system",
                )
            except Exception:
                store.update_record(
                    "notifications",
                    str(notification_id),
                    {"email_status": "FAILED"},
                    actor_id="floodman-system",
                )
        phone = str(user.get("phone") or "").strip()
        if str(notification.get("sms_status") or "") == "PENDING":
            try:
                await providers.send_sms(phone, f"Floodman incoming call from {caller_name}. Open: {action_url}")
                store.update_record(
                    "notifications",
                    str(notification_id),
                    {"sms_status": "SENT", "sms_sent_at": datetime.now(UTC).isoformat()},
                    actor_id="floodman-system",
                )
            except Exception:
                store.update_record(
                    "notifications",
                    str(notification_id),
                    {"sms_status": "FAILED"},
                    actor_id="floodman-system",
                )


@app.post("/internal/v1/call-intakes/project")
async def project_ai_call_intake(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > 256 * 1024:
        raise HTTPException(413, "Call intake projection is too large")
    try:
        verify_signed_body(request.headers, body, settings.internal_hmac_keys, max_age_seconds=300)
    except SignedRequestError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        payload = CallIntakeProjectionRequest.model_validate_json(body)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    try:
        result = store.project_call_intake(payload.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await _deliver_call_intake_notifications(result)
    return result


@app.post("/internal/v1/call-intakes/{intake_id}/links")
async def update_ai_call_intake_links(intake_id: str, request: Request) -> dict[str, Any]:
    body = await request.body()
    try:
        verify_signed_body(request.headers, body, settings.internal_hmac_keys, max_age_seconds=300)
    except SignedRequestError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    try:
        payload = CallIntakeLinksRequest.model_validate_json(body)
        return store.update_call_intake_links(intake_id, **payload.model_dump())
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Call intake not found") from exc


@app.get("/office/client-files/{document_id}/download")
def download_client_file(document_id: str) -> Response:
    _require("documents.view")
    record = store.record("documents", document_id)
    if not record:
        raise HTTPException(404, "Client-file document not found")
    stored = str(record.get("signed_stored_path") or "").strip()
    if not stored:
        raise HTTPException(404, "Signed PDF is not attached to this client file")
    root = Path(settings.documents_dir).resolve()
    path = Path(stored).resolve()
    if path != root and root not in path.parents:
        raise HTTPException(400, "Signed document path is outside the Floodman document archive")
    if not path.is_file():
        raise HTTPException(404, "Signed PDF is missing from the document archive")
    content = path.read_bytes()
    expected = str(record.get("signed_pdf_sha256") or "").lower()
    if expected and hashlib.sha256(content).hexdigest() != expected:
        raise HTTPException(409, "Signed PDF integrity verification failed")
    filename = f"{str(record.get('document_type') or 'signed-document').lower().replace('_','-')}.pdf"
    return Response(
        content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


def _safe_login_target(value: str, fallback: str = "/office") -> str:
    candidate = str(value or "").strip()
    unsafe = (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or any(ord(character) < 32 for character in candidate)
    )
    return fallback if unsafe else candidate


def _set_office_session(response: Response, user: dict[str, Any]) -> Response:
    response.set_cookie(
        "floodman_session",
        store.create_session(str(user["id"])),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=14 * 86400,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return response


def _local_login_page(next: str) -> HTMLResponse:
    target = _safe_login_target(next)
    body = f"""<h1>Emergency local sign in</h1>
    <div class='callout'>This fallback is for the installation Owner or a module-only recovery account. Staff should use the main Floodman ERP login.</div>
    <div class='card'><form method='post' action='/login'><input type='hidden' name='next' value='{esc(target)}'>
    <div class='field'><label>Email</label><input type='email' name='email' required autofocus></div>
    <div class='field' style='margin-top:12px'><label>Password</label><input type='password' name='password' required></div>
    <button style='margin-top:16px;width:100%'>Sign in locally</button></form></div>
    <p><a class='button secondary' href='/login?next={quote(target, safe="")}'>Use the main Floodman ERP login</a></p>"""
    return HTMLResponse(simple_page("Emergency local sign in", body), headers={"Cache-Control": "no-store"})


@app.get("/login/local")
def local_login_page(next: str = "/office") -> HTMLResponse:
    return _local_login_page(next)


@app.get("/login")
def login_page(next: str = "/office", local: bool = False) -> Response:
    if not store.has_users():
        return RedirectResponse("/setup", status_code=303)
    target = _safe_login_target(next)
    if _user():
        return RedirectResponse(target, status_code=303)
    if local:
        return _local_login_page(target)
    javascript_target = json.dumps(target).replace("<", "\\u003c")
    local_href = f"/login/local?next={quote(target, safe='')}"
    body = f"""<h1>Floodman sign in</h1>
    <div class='card'><h2>One login for ERP, Office, and RoomFlow</h2>
    <p class='muted'>Floodman is opening the main ERP login. After it verifies your account, this browser will return to the requested Floodman workspace automatically.</p>
    <div id='floodman-login-status' class='callout' role='status' aria-live='polite'>Checking for an existing Floodman ERP session…</div>
    <p><a id='floodman-open-erp' class='button good' href='/full-erp?target=login'>Open Floodman ERP login</a></p></div>
    <p class='muted' style='font-size:12px'>Installation recovery only: <a href='{local_href}'>use an emergency local account</a>.</p>
<script>
(() => {{
  'use strict';
  const target = {javascript_target};
  const pendingKey = 'floodmanLoginNext';
  const status = document.getElementById('floodman-login-status');
  const open = document.getElementById('floodman-open-erp');
  const candidates = new Set();
  const tokenPattern = /eyJ[A-Za-z0-9_-]{{8,}}\\.[A-Za-z0-9_-]{{8,}}\\.[A-Za-z0-9_-]{{8,}}/g;

  function collect(value, depth = 0) {{
    if (depth > 4 || value === null || value === undefined) return;
    if (typeof value === 'string') {{
      for (const match of value.matchAll(tokenPattern)) candidates.add(match[0]);
      if ((value.startsWith('{{') || value.startsWith('[') || value.startsWith('"')) && value.length < 100000) {{
        try {{ collect(JSON.parse(value), depth + 1); }} catch (_) {{}}
      }}
      return;
    }}
    if (Array.isArray(value)) {{ value.forEach(item => collect(item, depth + 1)); return; }}
    if (typeof value === 'object') Object.values(value).forEach(item => collect(item, depth + 1));
  }}

  function rememberReturn() {{
    try {{ sessionStorage.setItem(pendingKey, target); }} catch (_) {{}}
  }}

  async function exchangeExistingSession() {{
    for (const storage of [window.localStorage, window.sessionStorage]) {{
      try {{ for (let index = 0; index < storage.length; index += 1) collect(storage.getItem(storage.key(index))); }} catch (_) {{}}
    }}
    for (const token of candidates) {{
      try {{
        const response = await fetch('/login/erp-session', {{
          method: 'POST', cache: 'no-store', credentials: 'same-origin',
          headers: {{ accept: 'application/json', authorization: `Bearer ${{token}}` }}
        }});
        if (response.ok) {{
          try {{ sessionStorage.removeItem(pendingKey); }} catch (_) {{}}
          window.location.replace(target);
          return true;
        }}
      }} catch (_) {{}}
    }}
    return false;
  }}

  async function begin() {{
    rememberReturn();
    if (await exchangeExistingSession()) return;
    status.textContent = 'Opening the main Floodman ERP login…';
    window.setTimeout(() => window.location.replace('/full-erp?target=login'), 900);
  }}

  open.addEventListener('click', rememberReturn);
  begin();
}})();
</script>"""
    return HTMLResponse(simple_page("Floodman sign in", body), headers={"Cache-Control": "no-store"})


@app.get("/login/status")
def login_status() -> JSONResponse:
    return JSONResponse({"authenticated": bool(_user())}, headers={"Cache-Control": "no-store"})


@app.post("/login/erp-session")
async def login_from_erp_session(request: Request, next: str = "/office") -> Response:
    authorization = str(request.headers.get("authorization") or "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return JSONResponse({"authenticated": False, "message": "An active Floodman ERP session is required."}, status_code=401)
    try:
        identity = await providers.authenticate_gauzy_session(token)
        user = store.upsert_gauzy_user(identity)
    except (RuntimeError, ValueError):
        return JSONResponse({"authenticated": False, "message": "The Floodman ERP session could not be connected."}, status_code=401)
    target = _safe_login_target(next)
    return _set_office_session(JSONResponse({"authenticated": True, "next": target}), user)


@app.post("/office/api/erp/login")
async def unified_erp_login(request: Request) -> Response:
    """Proxy the genuine ERP login and establish its Office/RoomFlow session."""
    try:
        supplied = await request.json()
        if not isinstance(supplied, dict):
            raise ValueError
        email = str(supplied.get("email") or "").strip()[:320]
        password = str(supplied.get("password") or "")[:4096]
        identity, login_payload = await providers.authenticate_gauzy_login(email, password)
        user = store.upsert_gauzy_user(identity)
    except (RuntimeError, ValueError):
        return JSONResponse(
            {"statusCode": 401, "message": "Floodman ERP did not accept that email and password."},
            status_code=401,
            headers={"Cache-Control": "no-store"},
        )
    return _set_office_session(JSONResponse(login_payload), user)


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), next: str = Form(default="/office")) -> Response:
    user = store.authenticate(email, password)
    if not user:
        body = "<h1>Sign in</h1><div class='callout danger'>The email or password was not accepted.</div><a class='button' href='/login'>Try again</a>"
        return HTMLResponse(simple_page("Sign in", body), status_code=401)
    response = RedirectResponse(_safe_login_target(next), status_code=303)
    return _set_office_session(response, user)


@app.post("/login/platform")
@app.post("/login/gauzy", include_in_schema=False)
async def login_with_gauzy(
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/office"),
) -> Response:
    try:
        identity = await providers.authenticate_gauzy_member(email, password)
        user = store.upsert_gauzy_user(identity)
    except (RuntimeError, ValueError) as exc:
        body = f"<h1>Floodman sign in</h1><div class='callout danger'>{esc(exc)}</div><a class='button' href='/login'>Try again</a>"
        if not store.has_users():
            body += " <a class='button secondary' href='/setup'>Return to owner setup</a>"
        return HTMLResponse(simple_page("Floodman sign in", body), status_code=401)
    response = RedirectResponse(_safe_login_target(next), status_code=303)
    return _set_office_session(response, user)


@app.post("/logout")
def logout(request: Request) -> Response:
    store.delete_session(request.cookies.get("floodman_session"))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("floodman_session", path="/")
    return response


@app.post("/setup/owner")
def create_owner(
    owner_name: str = Form(...),
    owner_email: str = Form(...),
    owner_password: str = Form(...),
    owner_password_confirm: str = Form(...),
) -> Response:
    if store.has_users():
        raise HTTPException(409, "Owner already exists")
    if owner_password != owner_password_confirm:
        return HTMLResponse(simple_page("Create owner", "<h1>Create owner</h1><div class='callout danger'>Passwords do not match.</div><a class='button' href='/setup'>Return</a>"), status_code=422)
    try:
        user = store.create_owner(owner_name, owner_email, owner_password)
    except ValueError as exc:
        return HTMLResponse(simple_page("Create owner", f"<h1>Create owner</h1><div class='callout danger'>{esc(exc)}</div><a class='button' href='/setup'>Return</a>"), status_code=422)
    response = RedirectResponse("/setup", status_code=303)
    response.set_cookie(
        "floodman_session",
        store.create_session(user["id"]),
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        max_age=14 * 86400,
        path="/",
    )
    return response


@app.get("/")
def root() -> RedirectResponse:
    # The guided review is not a server-installation gate. Once an Owner
    # exists, open the operational dashboard and keep the review available
    # through its status chip and navigation item.
    target = "/office/desktop" if store.has_users() else "/setup"
    return RedirectResponse(target, status_code=302)


def _page(title: str, body: str, active: str) -> HTMLResponse:
    snapshot = store.snapshot()
    user = _user()
    unread_notifications = sum(
        1
        for item in store.records("notifications")
        if str(item.get("user_id") or "") == str((user or {}).get("id") or "")
        and str(item.get("status") or "UNREAD").upper() == "UNREAD"
    )
    return HTMLResponse(
        layout(
            title,
            body,
            active=active,
            notice=snapshot.get("last_notice", ""),
            setup_complete=bool(snapshot["checklist"].get("setup_complete")),
            release=settings.release,
            user=user,
            unread_notifications=unread_notifications,
        )
    )


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [dict(item) for item in items if isinstance(item, dict)]
    return []


def _square_remaining(invoice: dict[str, Any]) -> int:
    return int((invoice.get("next_payment_amount_money") or {}).get("amount") or 0)


def _invoice_number(item: dict[str, Any]) -> str:
    return str(item.get("invoiceNumber") or item.get("invoice_number") or item.get("id") or "")


def _merge_archive_state(value: dict[str, Any]) -> dict[str, Any]:
    """Overlay the durable Office archive onto the disposable provider simulator.

    The v1.1.x local provider lab intentionally stores its mock objects in memory.
    Historical migration records therefore remain authoritative in the Office
    volume and are projected into the same view shape after any simulator restart.
    """
    state = dict(value)

    def merge(existing: Any, archived: list[dict[str, Any]], id_fields: tuple[str, ...]) -> list[dict[str, Any]]:
        combined = _rows(existing)
        seen: set[str] = set()
        for item in combined:
            identity = next((str(item[field]) for field in id_fields if item.get(field)), "")
            if identity:
                seen.add(identity)
        for item in archived:
            identity = next((str(item[field]) for field in id_fields if item.get(field)), "")
            if identity and identity in seen:
                continue
            combined.append(dict(item))
            if identity:
                seen.add(identity)
        return combined

    def cents(row: dict[str, Any], field: str) -> int:
        try:
            return int(row.get(f"_{field}") or row.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    def archive_url(row: dict[str, Any], *fields: str) -> str | None:
        run_id = str(row.get("import_run_id") or row.get("_import_run_id") or "").strip()
        filename = next((str(row.get(field) or "").strip() for field in fields if row.get(field)), "")
        if not run_id or not filename:
            return None
        normalized = filename.replace("\\", "/")
        while normalized.startswith("./"):
            normalized = normalized[2:]
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            return None
        return f"/office/imports/{quote(run_id, safe='')}/files/{quote(path.as_posix(), safe='/')}"

    archived_contacts = store.archive_records("contacts")
    archived_properties = store.archive_records("properties")
    archived_estimates = store.archive_records("estimates")
    archived_lines = store.archive_records("estimate_lines")
    archived_invoices = store.archive_records("invoices")
    archived_payments = store.archive_records("payments")
    archived_documents = store.archive_records("documents")
    archived_notes = store.archive_records("notes")

    contact_names: dict[str, str] = {}
    projected_contacts: list[dict[str, Any]] = []
    for row in archived_contacts:
        legacy_id = str(row.get("legacy_contact_id") or "")
        name = " ".join(value for value in (row.get("first_name"), row.get("last_name")) if value).strip()
        contact_names[legacy_id] = name or legacy_id
        projected_contacts.append({
            **row,
            "id": f"archive-contact:{legacy_id}",
            "name": name or legacy_id,
            "primaryEmail": row.get("email"),
            "primaryPhone": row.get("phone"),
            "legacySource": "townsquare",
            "legacyContactId": legacy_id,
            "importMode": "HISTORICAL_ARCHIVE",
        })

    lines_by_estimate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in archived_lines:
        lines_by_estimate[str(row.get("legacy_estimate_id") or "")].append(row)

    def invoice_items(estimate_id: str) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for row in lines_by_estimate.get(estimate_id, []):
            try:
                quantity = float(row.get("_quantity") or row.get("quantity") or 1)
            except (TypeError, ValueError):
                quantity = 1.0
            values.append({
                **row,
                "id": f"archive-line:{row.get('legacy_line_id')}",
                "name": row.get("name") or "Imported line item",
                "description": row.get("description") or row.get("name") or "Imported line item",
                "quantity": quantity,
                "price": cents(row, "unit_price_cents") / 100,
                "totalValue": cents(row, "line_total_cents") / 100,
                "legacyLineId": row.get("legacy_line_id"),
            })
        return values

    projected_properties: list[dict[str, Any]] = []
    for row in archived_properties:
        legacy_id = str(row.get("legacy_property_id") or "")
        contact_id = str(row.get("legacy_contact_id") or "")
        projected_properties.append({
            **row,
            "id": f"archive-property:{legacy_id}",
            "contact_id": f"archive-contact:{contact_id}" if contact_id else "",
            "name": row.get("property_name") or legacy_id,
            "insurance_company": row.get("insurer"),
            "legacySource": "townsquare",
            "legacyPropertyId": legacy_id,
            "importMode": "HISTORICAL_ARCHIVE",
        })

    projected_estimates: list[dict[str, Any]] = []
    for row in archived_estimates:
        legacy_id = str(row.get("legacy_estimate_id") or "")
        contact_id = str(row.get("legacy_contact_id") or "")
        property_id = str(row.get("legacy_property_id") or "")
        projected_estimates.append({
            **row,
            "id": f"archive-estimate:{legacy_id}",
            "contact_id": f"archive-contact:{contact_id}" if contact_id else "",
            "property_id": f"archive-property:{property_id}" if property_id else "",
            "invoiceNumber": row.get("estimate_number"),
            "invoiceDate": row.get("created_at"),
            "dueDate": row.get("accepted_at") or row.get("created_at"),
            "status": str(row.get("status") or "DRAFT").upper(),
            "totalValue": cents(row, "total_cents") / 100,
            "currency": str(row.get("currency") or "USD").upper(),
            "isEstimate": True,
            "isAccepted": str(row.get("status") or "").upper() == "ACCEPTED",
            "organizationContactName": contact_names.get(contact_id, contact_id),
            "invoiceItems": invoice_items(legacy_id),
            "legacySource": "townsquare",
            "legacyEstimateId": legacy_id,
            "importMode": "HISTORICAL_ARCHIVE",
            "pdfUrl": archive_url(row, "_stored_file_path", "pdf_path"),
        })

    paid_by_invoice: dict[str, int] = defaultdict(int)
    for row in archived_payments:
        if str(row.get("status") or "").upper() not in {"FAILED", "CANCELLED", "VOID", "REFUNDED"}:
            paid_by_invoice[str(row.get("legacy_invoice_id") or "")] += cents(row, "amount_cents")

    projected_invoices: list[dict[str, Any]] = []
    for row in archived_invoices:
        legacy_id = str(row.get("legacy_invoice_id") or "")
        estimate_id = str(row.get("legacy_estimate_id") or "")
        contact_id = str(row.get("legacy_contact_id") or "")
        property_id = str(row.get("legacy_property_id") or "")
        total_cents = cents(row, "total_cents")
        paid_cents = paid_by_invoice.get(legacy_id, 0)
        projected_invoices.append({
            **row,
            "id": f"archive-invoice:{legacy_id}",
            "contact_id": f"archive-contact:{contact_id}" if contact_id else "",
            "property_id": f"archive-property:{property_id}" if property_id else "",
            "invoiceNumber": row.get("invoice_number"),
            "invoiceDate": row.get("issued_at"),
            "dueDate": row.get("due_at") or row.get("issued_at"),
            "status": str(row.get("status") or "SENT").upper(),
            "totalValue": total_cents / 100,
            "alreadyPaid": min(total_cents, paid_cents) / 100,
            "amountDue": max(0, total_cents - paid_cents) / 100,
            "currency": str(row.get("currency") or "USD").upper(),
            "paid": total_cents > 0 and paid_cents >= total_cents,
            "isEstimate": False,
            "organizationContactName": contact_names.get(contact_id, contact_id),
            "invoiceItems": invoice_items(estimate_id),
            "legacySource": "townsquare",
            "legacyInvoiceId": legacy_id,
            "legacyEstimateId": estimate_id or None,
            "importMode": "HISTORICAL_ARCHIVE",
            "pdfUrl": archive_url(row, "_stored_file_path", "pdf_path"),
        })

    projected_payments: list[dict[str, Any]] = []
    for row in archived_payments:
        legacy_id = str(row.get("legacy_payment_id") or "")
        projected_payments.append({
            **row,
            "id": f"archive-payment:{legacy_id}",
            "invoiceId": f"archive-invoice:{row.get('legacy_invoice_id')}",
            "amount": cents(row, "amount_cents") / 100,
            "currency": str(row.get("currency") or "USD").upper(),
            "paymentDate": row.get("paid_at"),
            "paymentMethod": str(row.get("payment_method") or "ONLINE").upper(),
            "providerStatus": str(row.get("status") or "COMPLETED").upper(),
            "providerReference": row.get("provider_reference"),
            "legacySource": "townsquare",
            "legacyPaymentId": legacy_id,
            "importMode": "HISTORICAL_ARCHIVE",
        })

    projected_documents: list[dict[str, Any]] = []
    for row in archived_documents:
        projected_documents.append({
            **row,
            "archive_url": archive_url(row, "_stored_file_path", "file_path"),
        })

    state["gauzy_contacts"] = merge(
        state.get("gauzy_contacts"), projected_contacts, ("legacyContactId", "legacy_contact_id", "id")
    )
    state["properties"] = merge(
        state.get("properties"), projected_properties, ("legacyPropertyId", "legacy_property_id", "id")
    )
    state["gauzy_invoices"] = merge(
        state.get("gauzy_invoices"),
        projected_estimates,
        ("legacyEstimateId", "legacy_estimate_id", "id"),
    )
    state["gauzy_invoices"] = merge(
        state.get("gauzy_invoices"),
        projected_invoices,
        ("legacyInvoiceId", "legacy_invoice_id", "id"),
    )
    state["gauzy_payments"] = merge(
        state.get("gauzy_payments"), projected_payments, ("legacyPaymentId", "legacy_payment_id", "id")
    )
    state["imported_documents"] = merge(
        state.get("imported_documents"), projected_documents, ("legacy_document_id", "legacyDocumentId", "id")
    )
    state["notes"] = merge(
        state.get("notes"), archived_notes, ("legacy_note_id", "legacyNoteId", "id")
    )
    return state

@app.get("/office/settings")
def settings_workspace() -> HTMLResponse:
    """Give owners one plain-language home for every staff-visible setting."""
    _require("connections.manage")
    snapshot = store.snapshot()
    profile = snapshot.get("profile") or {}
    checklist = snapshot.get("checklist") or {}
    connections = snapshot.get("connections") or {}
    active_members = [item for item in store.list_users() if item.get("status") == "ACTIVE"]
    catalog_count = len(store.records("catalog_items"))
    workspace_count = len(store.records("roomflow_workspaces"))
    import_count = len(store.list_imports())
    payment_config = providers.square_payment_configuration()

    business_ready = len(str(profile.get("company_name") or "").strip()) >= 2 and bool(profile.get("office_email"))
    catalog_ready = catalog_count > 0
    payment_ready = bool(payment_config.get("local_mock") or payment_config.get("live"))
    roomflow_ready = True  # The default workspace is created safely on first RoomFlow open.
    review_ready = bool(checklist.get("setup_complete"))
    core_checks = (business_ready, bool(active_members), catalog_ready, roomflow_ready, payment_ready, review_ready)
    ready_count = sum(1 for value in core_checks if value)
    ready_percent = round(ready_count / len(core_checks) * 100)

    def card(
        number: str,
        title: str,
        description: str,
        summary: str,
        href: str,
        action: str,
        *,
        ready: bool | None = None,
    ) -> str:
        state = badge("READY", "good") if ready is True else badge("NEEDS ATTENTION", "warn") if ready is False else badge("OPTIONAL", "neutral")
        return (
            "<article class='card settings-card'>"
            f"<div class='settings-card-head'><span class='settings-card-number'>{esc(number)}</span>{state}</div>"
            f"<h3>{esc(title)}</h3><p>{esc(description)}</p>"
            f"<div class='settings-summary'>{esc(summary)}</div>"
            f"<div class='actions'><a class='button {'good' if ready is False else 'secondary'}' href='{esc(href)}'>{esc(action)}</a></div>"
            "</article>"
        )

    connection_failures = sum(1 for item in connections.values() if str(item.get("status") or "").upper() == "FAILED")
    connection_summary = (
        "Not tested yet"
        if not connections
        else f"{len(connections) - connection_failures} passing · {connection_failures} need attention"
    )
    roomflow_summary = (
        f"{workspace_count} company workspace{'s' if workspace_count != 1 else ''} · {len(store.records('roomflow_jobs'))} saved jobs"
        if workspace_count
        else "Your company workspace will be created automatically on first open"
    )
    payment_summary = (
        "Safe local test mode is ready"
        if payment_config.get("local_mock")
        else "Production processor is connected"
        if payment_config.get("live")
        else "Processor setup is incomplete"
    )
    daily_cards = "".join(
        (
            card("1", "Business details", "Set the name and contact details customers see. Eastern Time (Detroit) remains the safe business default.", f"Company: {profile.get('company_name') or 'Not set'} · Office email: {profile.get('office_email') or 'Not set'}", "/setup#company-profile", "Review business details", ready=business_ready),
            card("2", "Team and access", "Add staff through the main ERP, then give each person only the access needed for their job.", f"{len(active_members)} active team member{'s' if len(active_members) != 1 else ''}", "/office/members", "Review team access", ready=bool(active_members)),
            card("3", "Services and prices", "Keep one reusable service list for office estimates, invoices, and RoomFlow field estimates.", f"{catalog_count} reusable service{'s' if catalog_count != 1 else ''}", "/office/catalog", "Review services and prices", ready=catalog_ready),
            card("4", "RoomFlow", "Use the same ERP sign-in, choose a customer and property, build the scope, and save it back to Floodman.", roomflow_summary, "/office/roomflow", "Open RoomFlow", ready=roomflow_ready),
        )
    )
    owner_cards = "".join(
        (
            card("5", "Card payments", "Confirm whether payments are in safe test mode or connected to the production processor. Card details are never entered here.", payment_summary, "/office/payment-settings", "Check payment readiness", ready=payment_ready),
            card("6", "Documents and signing", "Review customer PDFs, signing templates, and the local test workflow before sending production agreements.", "Signing review complete" if checklist.get("legal_reviewed") else "Production documents still need review", "/office/signing", "Review documents and signing", ready=bool(checklist.get("legal_reviewed"))),
            card("7", "Bring in existing customers", "Preview a customer CSV or business archive before Floodman writes any records. Skip this when starting fresh.", f"{import_count} import preview{'s' if import_count != 1 else ''}", "/office/imports", "Open safe import", ready=None),
            card("8", "Advanced connections", "For the server owner or installer: test provider health and download configuration values. Daily staff do not need this page.", connection_summary, "/office/linking", "Open advanced connections", ready=(bool(connections) and connection_failures == 0)),
        )
    )
    body = f"""
<section class='card settings-hero'><div class='settings-hero-copy'><span class='settings-eyebrow'>OWNER START HERE</span><h2>Set up Floodman in the order people actually use it</h2><p>Complete the four everyday choices first. Technical provider addresses and server secrets stay in a separate advanced area, so office and field staff never have to guess what an infrastructure setting means.</p></div><div class='settings-progress'><strong>{ready_count}/{len(core_checks)}</strong><small>recommended areas ready</small><div class='progress' style='margin-top:10px'><span style='width:{ready_percent}%'></span></div></div></section>
<div class='settings-section-head'><div><h2>Everyday setup</h2><p>Most businesses only need these four areas to begin working.</p></div><a class='button good' href='/setup'>Open go-live checklist</a></div><div class='settings-grid'>{daily_cards}</div>
<div class='settings-section-head'><div><h2>Owner-only setup</h2><p>Review these when you are preparing imports, payments, documents, or external providers.</p></div></div><div class='settings-grid'>{owner_cards}</div>
<div class='callout success'><b>Nothing here changes a live database or turns on customer communication by itself.</b> Imports always preview first, production payments require server credentials, and the final go-live checklist only records your review.</div>
"""
    return _page("Settings & Setup", body, "settings")


@app.get("/setup")
async def setup_page() -> HTMLResponse:
    if not store.has_users():
        body = """<h1>Create the primary owner</h1><p class='muted'>Floodman ERP is the main identity and ERP hub. The Floodman owner created during business initialization can become the first Floodman module owner, or you can create a separate local recovery owner.</p>
        <div class='card'><h2>Recommended: use the Floodman ERP owner</h2><form method='post' action='/login/gauzy'><input type='hidden' name='next' value='/setup'>
        <div class='field'><label>Floodman ERP owner email</label><input type='email' name='email' value='' placeholder='owner@your-domain.com' required autofocus></div>
        <div class='field' style='margin-top:12px'><label>Floodman ERP password</label><input type='password' name='password' required></div>
        <button class='good' style='margin-top:16px;width:100%'>Use Floodman ERP owner</button></form></div>
        <div class='card'><h2>Local recovery owner</h2><p class='muted'>This account controls Floodman-specific modules even if Floodman ERP is temporarily unavailable.</p>
        <form method='post' action='/setup/owner'><div class='field'><label>Your name</label><input name='owner_name' required></div>
        <div class='field' style='margin-top:12px'><label>Owner email</label><input type='email' name='owner_email' required></div>
        <div class='field' style='margin-top:12px'><label>Password</label><input type='password' name='owner_password' minlength='10' required></div>
        <div class='field' style='margin-top:12px'><label>Confirm password</label><input type='password' name='owner_password_confirm' minlength='10' required></div>
        <button style='margin-top:16px;width:100%'>Create local recovery owner</button></form></div>"""
        return HTMLResponse(simple_page("Create owner", body))
    _require("connections.manage")
    snapshot = store.snapshot()
    profile = snapshot["profile"]
    checklist = snapshot["checklist"]
    connections = snapshot.get("connections") or {}
    done, total, percentage = progress(checklist)
    steps = [
        ("Owner", checklist.get("owner_created")),
        ("Company", checklist.get("profile_saved")),
        ("Connections", checklist.get("connections_tested")),
        ("Import", checklist.get("import_reviewed")),
        ("Documents", checklist.get("legal_reviewed")),
        ("Messaging", checklist.get("messaging_reviewed")),
    ]
    step_html = "".join(
        f"<div class='step {'done' if complete else ''}'>{'✓ ' if complete else ''}{esc(label)}</div>"
        for label, complete in steps
    )
    connection_cards = "".join(
        f"<div class='card metric'><small>{esc(name.replace('_', ' ').title())}</small>"
        f"<strong>{badge(result.get('status'))}</strong><div class='muted'>{esc(result.get('detail'))}</div></div>"
        for name, result in connections.items()
    ) or "<div class='callout'>Run the connection test after the containers are up.</div>"

    body = f"""
<div class='callout success'><b>Floodman is installed and ready to use.</b> This checklist helps the owner confirm business details and test workflows. It never blocks the dashboard and does not turn on live payments, texts, or contracts.</div>
<div class='card'><div class='actions spread'><div><h2>Go-live progress</h2><p class='muted'>{done} of {total} areas reviewed. Work from top to bottom; you can leave and return at any time.</p></div><a class='button secondary' href='/office/settings'>Back to Settings &amp; Setup</a></div><div class='progress'><span style='width:{percentage}%'></span></div><div class='steps'>{step_html}</div></div>
<div class='card' id='company-profile'><div class='settings-eyebrow'>STEP 1 · REQUIRED</div><h2>Business details customers will recognize</h2><p class='muted'>Use the everyday company name on estimates and messages. Legal, billing, and address fields can be filled in now or later.</p>
<form method='post' action='/setup/profile'><div class='form-grid'>
<div class='field'><label>Company display name <span class='required-mark'>Required</span></label><input name='company_name' value='{esc(profile.get('company_name'))}' minlength='2' maxlength='160' autocomplete='organization' required><small class='field-help'>The short name staff and customers normally use.</small></div>
<div class='field'><label>Legal company name <span class='muted'>Optional</span></label><input name='legal_name' value='{esc(profile.get('legal_name'))}' maxlength='200' autocomplete='organization'><small class='field-help'>Only needed when it differs from the display name.</small></div>
<div class='field'><label>Main office email <span class='muted'>Optional</span></label><input type='email' name='office_email' value='{esc(profile.get('office_email'))}' placeholder='office@example.com' autocomplete='email'><small class='field-help'>General replies and office contact.</small></div>
<div class='field'><label>Billing email <span class='muted'>Optional</span></label><input type='email' name='billing_email' value='{esc(profile.get('billing_email'))}' placeholder='billing@example.com' autocomplete='email'><small class='field-help'>Use the office email when there is no separate billing inbox.</small></div>
<div class='field'><label>Main phone <span class='muted'>Optional</span></label><input type='tel' name='office_phone' value='{esc(profile.get('office_phone'))}' placeholder='(313) 555-0100' autocomplete='tel' maxlength='40'></div>
<div class='field'><label>Business time zone</label><select name='timezone'><option value='America/Detroit' selected>Eastern Time (Detroit)</option></select><small class='field-help'>Recommended and required for Floodman scheduling; timestamps are stored safely in UTC.</small></div>
<div class='field full'><label>Office street address <span class='muted'>Optional</span></label><input name='street' value='{esc(profile.get('street'))}' maxlength='240' autocomplete='street-address'></div>
<div class='field'><label>City <span class='muted'>Optional</span></label><input name='city' value='{esc(profile.get('city'))}' maxlength='120' autocomplete='address-level2'></div>
<div class='field'><label>State</label><input name='state' value='{esc(profile.get('state') or 'MI')}' maxlength='2' pattern='[A-Za-z]{{2}}' autocomplete='address-level1' inputmode='text'><small class='field-help'>Two-letter abbreviation, such as MI.</small></div>
<div class='field'><label>ZIP code <span class='muted'>Optional</span></label><input name='postal_code' value='{esc(profile.get('postal_code'))}' maxlength='10' pattern='[0-9]{{5}}(-[0-9]{{4}})?' autocomplete='postal-code' inputmode='numeric'></div>
</div><div class='actions' style='margin-top:14px'><button class='good'>Save business details</button></div></form></div>
<div class='card'><div class='settings-eyebrow'>STEP 2 · OWNER OR INSTALLER</div><h2>Check connected services</h2><p>One button checks whether the local ERP, RoomFlow bridge, signing, payments, email, messaging, and research services can answer. It does not send anything to a customer.</p>
<details class='plain-details'><summary>Show individual service results</summary><div class='grid' style='margin-top:12px'>{connection_cards}</div></details><div class='actions' style='margin-top:14px'><form method='post' action='/setup/test-connections'><button>Run safe connection check</button></form><a class='button secondary' href='/office/linking'>Installer connection details</a></div></div>
<div class='card'><div class='settings-eyebrow'>STEP 3 · OPTIONAL</div><h2>Bring in existing customer information</h2><p>Starting fresh? You can simply mark this reviewed. If you have a customer CSV or archive ZIP, Floodman shows a preview and validation report before it writes any records.</p><div class='actions'><a class='button' href='/office/imports'>Preview an import</a><a class='button secondary' href='/office/imports/customers/template.csv'>Download customer template</a></div></div>
<div class='card'><div class='settings-eyebrow'>STEP 4 · REVIEW</div><h2>Confirm your operating choices</h2><p class='muted'>Check an item only after the owner understands it. These acknowledgements do not activate the feature.</p><form method='post' action='/setup/checklist' class='checks'>
<label><input type='checkbox' name='legal_reviewed' value='true' {'checked' if checklist.get('legal_reviewed') else ''}><span><b>Customer documents:</b> I tested Work Authorization, Change Order, and Completion of Service. I understand local templates must be approved before production use.</span></label>
<label><input type='checkbox' name='messaging_reviewed' value='true' {'checked' if checklist.get('messaging_reviewed') else ''}><span><b>Customer communication:</b> I reviewed text consent and STOP/START behavior, staff escalation, invoices, and past-due reminders.</span></label>
<label><input type='checkbox' name='import_reviewed' value='true' {'checked' if checklist.get('import_reviewed') else ''}><span><b>Existing data:</b> I previewed the import format, or I am starting fresh and do not need an import.</span></label>
<button>Save these choices</button></form></div>
<div class='card'><div class='settings-eyebrow'>FINAL STEP</div><h2>Mark the owner review complete</h2><p>This changes only the setup badge. Live payment, messaging, and signing credentials still require deliberate server configuration.</p><form method='post' action='/setup/finish'><button class='good'>Mark go-live review complete</button></form></div>
"""
    return _page("Go-Live Checklist", body, "setup")


@app.post("/setup/profile")
def save_profile(
    company_name: str = Form(...),
    legal_name: str = Form(default=""),
    office_email: str = Form(default=""),
    billing_email: str = Form(default=""),
    office_phone: str = Form(default=""),
    timezone: str = Form(default="America/Detroit"),
    street: str = Form(default=""),
    city: str = Form(default=""),
    state: str = Form(default="MI"),
    postal_code: str = Form(default=""),
) -> RedirectResponse:
    _require("connections.manage")
    company_name = company_name.strip()
    office_email = office_email.strip().lower()
    billing_email = billing_email.strip().lower()
    if len(company_name) < 2:
        store.set_notice("Enter a company display name with at least two characters.")
        return RedirectResponse("/setup#company-profile", status_code=303)
    if timezone.strip() != "America/Detroit":
        store.set_notice("Floodman business scheduling must use Eastern Time (Detroit).")
        return RedirectResponse("/setup#company-profile", status_code=303)
    email_pattern = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    if office_email and not email_pattern.fullmatch(office_email):
        store.set_notice("Enter a valid main office email address, or leave it blank.")
        return RedirectResponse("/setup#company-profile", status_code=303)
    if billing_email and not email_pattern.fullmatch(billing_email):
        store.set_notice("Enter a valid billing email address, or leave it blank.")
        return RedirectResponse("/setup#company-profile", status_code=303)
    state_value = state.strip().upper() or "MI"
    if not re.fullmatch(r"[A-Z]{2}", state_value):
        store.set_notice("Use the two-letter state abbreviation, such as MI.")
        return RedirectResponse("/setup#company-profile", status_code=303)
    postal_value = postal_code.strip()
    if postal_value and not re.fullmatch(r"\d{5}(?:-\d{4})?", postal_value):
        store.set_notice("Enter a five-digit ZIP code, optionally followed by four digits.")
        return RedirectResponse("/setup#company-profile", status_code=303)
    store.update_profile(
        {
            "company_name": company_name,
            "legal_name": legal_name.strip(),
            "office_email": office_email,
            "billing_email": billing_email,
            "office_phone": office_phone.strip(),
            "timezone": "America/Detroit",
            "street": street.strip(),
            "city": city.strip(),
            "state": state_value,
            "postal_code": postal_value,
        }
    )
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/test-connections")
async def test_connections() -> RedirectResponse:
    _require("connections.manage")
    results = await providers.connection_tests()
    store.save_connections(results)
    failed = [name for name, result in results.items() if result.get("status") == "FAILED"]
    if failed:
        store.set_notice(f"Connection test finished with failures: {', '.join(failed)}")
    else:
        store.set_notice("All local provider connections passed.")
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/checklist")
def save_checklist(
    legal_reviewed: str | None = Form(default=None),
    messaging_reviewed: str | None = Form(default=None),
    import_reviewed: str | None = Form(default=None),
) -> RedirectResponse:
    _require("connections.manage")
    store.update_checklist(
        {
            "legal_reviewed": legal_reviewed == "true",
            "messaging_reviewed": messaging_reviewed == "true",
            "import_reviewed": import_reviewed == "true",
        }
    )
    store.set_notice("Review checklist saved.")
    return RedirectResponse("/setup", status_code=303)


@app.post("/setup/finish")
def finish_setup() -> RedirectResponse:
    _require("connections.manage")
    checklist = store.checklist()
    required = ["owner_created", "profile_saved", "connections_tested", "import_reviewed", "legal_reviewed", "messaging_reviewed"]
    missing = [key.replace("_", " ") for key in required if not checklist.get(key)]
    if missing:
        store.set_notice(f"Finish the remaining setup areas first: {', '.join(missing)}.")
        return RedirectResponse("/setup", status_code=303)
    store.update_checklist({"setup_complete": True})
    store.set_notice("Full local setup is complete. Welcome to Floodman Operations.")
    return RedirectResponse("/office/desktop", status_code=303)



async def _dashboard_state(timeout_seconds: float = 3.5) -> dict[str, Any]:
    """Return the durable dashboard immediately even if a provider is warming up.

    Desktop navigation is controlled by a service worker. A long provider timeout
    can look like a lost network connection even though the private proxied
    route is healthy. Bound only the optional provider snapshot; the durable
    Floodman Office records remain available through ``_merge_archive_state``.
    """
    try:
        value = await asyncio.wait_for(providers.lab_state(), timeout=timeout_seconds)
        return _merge_archive_state(value)
    except Exception as exc:
        return _merge_archive_state({"provider_warning": str(exc)})


@app.get("/mobile")
def mobile_shortcut() -> RedirectResponse:
    return RedirectResponse("/office/mobile?mobile=1", status_code=307)


@app.get("/m")
def mobile_shortcut_short() -> RedirectResponse:
    return RedirectResponse("/office/mobile?mobile=1", status_code=307)


@app.get("/desktop")
def desktop_shortcut() -> RedirectResponse:
    return RedirectResponse("/office/desktop?desktop=1", status_code=307)


@app.get("/d")
def desktop_shortcut_short() -> RedirectResponse:
    return RedirectResponse("/office/desktop?desktop=1", status_code=307)


@app.get("/office/mobile")
async def mobile_operations() -> HTMLResponse:
    _require("dashboard.view")
    state = await _dashboard_state()

    contacts = store.records("contacts")
    properties = store.records("properties")
    invoices = store.records("invoices")
    payments = store.records("payments")
    documents = store.records("documents")
    tasks = store.records("tasks")
    messages = _rows(state.get("messages")) + _rows(state.get("message_threads")) + store.records("customer_threads")
    ar_cases = _rows(state.get("ar_cases"))
    current_user_id = str((_user() or {}).get("id") or "")
    local_alerts = [
        item for item in store.records("notifications")
        if str(item.get("user_id") or "") == current_user_id
        and str(item.get("status") or "UNREAD").upper() == "UNREAD"
    ]
    alerts = _rows(state.get("staff_alerts")) + local_alerts

    open_invoices = [item for item in invoices if str(item.get("status") or "").upper() not in {"PAID", "VOID", "CANCELED", "CANCELLED"}]
    completed_documents = [item for item in documents if str(item.get("status") or "").upper() in {"COMPLETED", "SIGNED", "EXECUTED"}]
    open_tasks = [item for item in tasks if str(item.get("status") or "").upper() not in {"DONE", "COMPLETED", "CLOSED"}]

    launch_items = [
        ("Customers", "Customer files, contact details, properties, notes, and signed documents.", "/office/contacts", "◎"),
        ("RoomFlow Estimator", "Draw rooms, build scopes, price work, and save estimates into the customer file.", "/office/roomflow", "⌑"),
        ("Jobs & Properties", "Service properties, active jobs, assignments, and field details.", "/office/properties", "▦"),
        ("Estimates", "Build, review, send, and convert estimates.", "/office/estimates", "▤"),
        ("Invoices", "Create invoices, review balances, and collect payment.", "/office/invoices", "$"),
        ("Payments", "Record and review deposits, partial payments, and final payments.", "/office/payments", "✓"),
        ("Documents", "Send authorizations and completion documents, then file signed PDFs.", "/office/documents", "✎"),
        ("Time Clock", "Clock in, clock out, and review your time entries.", "/office/time", "◷"),
        ("Messages", "Customer conversations, SMS status, and staff handoff.", "/office/messages", "✉"),
        ("Import CSV or ZIP", "Upload your customer CSV directly or a complete archive ZIP.", "/office/imports", "⇩"),
        ("AI Competition", "Competitor monitors, evidence, changes, and sales talking points.", "/office/intelligence", "⌁"),
        ("Members", "Invite staff and control Floodman module access.", "/office/members", "♙"),
        ("Install Floodman", "Add the full-screen Floodman app to Android, iPhone, iPad, Windows, or macOS.", "/install-app", "⇩"),
        ("All Tools", "Open every Floodman operation and administration area.", "/office/apps", "☰"),
    ]
    launch_html = "".join(
        f"<a class='mobile-launch-card' href='{href}'><span class='mobile-launch-icon'>{esc(icon)}</span>"
        f"<span><b>{esc(label)}</b><small>{esc(description)}</small></span><span class='mobile-launch-arrow'>›</span></a>"
        for label, description, href, icon in launch_items
    )

    body = f"""
<section class='mobile-hero'>
  <div><span class='mobile-hero-kicker'>PHONE & TABLET WORKSPACE</span><h2>Run Floodman from the field</h2><p>Large touch controls, card-based lists, direct CSV/ZIP importing, customer files, job tools, billing, documents, time, messages, and intelligence without the desktop ERP shell.</p></div>
  <div class='actions mobile-hero-actions'><a class='button good' href='/install-app'>Install Floodman app</a><a class='button secondary mobile-desktop-link' href='/office/desktop?desktop=1' data-use-desktop>Open desktop workspace</a><a class='button secondary mobile-desktop-link' href='/full-erp' data-use-desktop>Open full ERP</a></div>
</section>
<div class='mobile-kpi-grid'>
  <a href='/office/contacts'><small>Customers</small><strong>{len(contacts)}</strong></a>
  <a href='/office/properties'><small>Jobs</small><strong>{len(properties)}</strong></a>
  <a href='/office/invoices'><small>Open invoices</small><strong>{len(open_invoices)}</strong></a>
  <a href='/office/receivables'><small>A/R cases</small><strong>{len(ar_cases)}</strong></a>
  <a href='/office/documents'><small>Signed files</small><strong>{len(completed_documents)}</strong></a>
  <a href='/office/tasks'><small>Open tasks</small><strong>{len(open_tasks)}</strong></a>
</div>
<section class='mobile-launch-grid'>{launch_html}</section>
<div class='card mobile-attention-card'><h2>Needs attention</h2><div class='grid metrics-grid'>
  <div class='metric'><small>Staff alerts</small><strong>{len(alerts)}</strong></div>
  <div class='metric'><small>Open messages</small><strong>{len(messages)}</strong></div>
  <div class='metric'><small>Payments recorded</small><strong>{len(payments)}</strong></div>
</div></div>
"""
    return _page("Mobile Operations", body, "mobile")


@app.get("/office")
@app.get("/office/desktop")
async def office_dashboard() -> HTMLResponse:
    state = await _dashboard_state()
    def combine(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in primary + secondary:
            identity = str(item.get("id") or item.get("legacy_id") or "")
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            result.append(item)
        return result

    contacts = combine(store.records("contacts"), _rows(state.get("gauzy_contacts")))
    properties = combine(store.records("properties"), _rows(state.get("properties")))
    gauzy_invoices = _rows(state.get("gauzy_invoices"))
    estimates = combine(store.records("estimates"), [item for item in gauzy_invoices if item.get("isEstimate") is True])
    invoices = combine(store.records("invoices"), [item for item in gauzy_invoices if item.get("isEstimate") is not True])
    payments = combine(store.records("payments"), _rows(state.get("gauzy_payments")))
    square = _rows(state.get("square_invoices"))
    documents = combine(store.records("documents"), _rows(state.get("envelopes")) + _rows(state.get("imported_documents")))
    notes = combine(store.records("notes"), _rows(state.get("notes")))
    current_user_id = str((_user() or {}).get("id") or "")
    local_alerts = [
        item for item in store.records("notifications")
        if str(item.get("user_id") or "") == current_user_id
        and str(item.get("status") or "UNREAD").upper() == "UNREAD"
    ]
    alerts = _rows(state.get("staff_alerts")) + local_alerts
    ar_cases = _rows(state.get("ar_cases"))
    outstanding = sum(_square_remaining(item) for item in square)
    imported_due = sum(
        int(round(float(item.get("amountDue") or 0) * 100))
        for item in invoices
        if item.get("importMode") or item.get("legacy_source") or item.get("legacySource")
    )
    paid_cents = sum(
        int(item.get("amount_cents") or round(float(item.get("amount") or 0) * 100))
        for item in payments
    )
    job = state.get("job") or {}
    job_card = f"<details class='card'><summary>Current workflow job</summary><div style='margin-top:12px'>{json_pre(job)}</div></details>" if job else ""
    body = f"""
<div class='card'><h2>Start work</h2><div class='actions'><a class='button good' href='/office/contacts'>Customers</a><a class='button' href='/office/estimates/new'>New estimate</a><a class='button' href='/office/calls'>Calls</a><a class='button secondary' href='/office/roomflow'>RoomFlow</a><a class='button secondary' href='/office/invoices'>Billing</a></div></div>
<div class='grid metrics-grid'>
<div class='card metric'><small>Customers</small><strong>{len(contacts)}</strong></div>
<div class='card metric'><small>Properties</small><strong>{len(properties)}</strong></div>
<div class='card metric'><small>Estimates</small><strong>{len(estimates)}</strong></div>
<div class='card metric'><small>Live balance</small><strong>{money_cents(outstanding)}</strong></div>
<div class='card metric'><small>Open alerts</small><strong>{len(alerts)}</strong></div>
</div>
<details class='card'><summary>More totals</summary><div class='grid metrics-grid' style='margin-top:15px'><div class='metric'><small>Invoices</small><strong>{len(invoices) + len(square)}</strong></div><div class='metric'><small>Imported balance</small><strong>{money_cents(imported_due)}</strong></div><div class='metric'><small>Payments recorded</small><strong>{money_cents(paid_cents)}</strong></div><div class='metric'><small>Documents</small><strong>{len(documents)}</strong></div><div class='metric'><small>Notes</small><strong>{len(notes)}</strong></div><div class='metric'><small>Open A/R cases</small><strong>{len(ar_cases)}</strong></div></div></details>{job_card}
"""
    return _page("Operations Dashboard", body, "dashboard")


@app.get("/office/linking")
async def linking_page() -> HTMLResponse:
    _require("connections.manage")
    snapshot = store.snapshot()
    connections = snapshot.get("connections") or {}
    config = snapshot.get("link_config") or {}
    rows = []
    advanced_rows = []
    definitions = [
        ("RoomFlow", "roomflow", settings.roomflow_sync_endpoint, "Saves field layouts and estimates into Floodman"),
        ("Floodman ERP workflow", "gauzy_workflow_bridge", settings.gauzy_base_url, "Keeps customer, project, estimate, invoice, and payment records together"),
        ("Floodman ERP screen", "gauzy_full_ui", settings.gauzy_web_url, "Opens the full employee and business-management system"),
        ("Card payments", "square", settings.square_base_url, "Processes test or production card payments without storing card numbers"),
        ("Document workflow", "documenso_workflow_bridge", settings.documenso_base_url, "Sends PDFs into the signing process"),
        ("Signing application", "documenso_full_ui", settings.documenso_web_url, "Manages reusable documents, signing fields, and history"),
        ("Customer texts", "twilio", settings.twilio_base_url, "Handles approved two-way text messages and delivery results"),
        ("Outgoing email", "smtp", f"{settings.smtp_host}:{settings.smtp_port}", "Sends workflow email or captures it safely during testing"),
        ("Test email inbox", "mailpit", settings.mailpit_url, "Shows locally captured messages without contacting customers"),
        ("Message assistant", "messaging_ai", settings.messaging_ai_url, f"Drafting policy: {settings.messaging_ai_provider}"),
        ("Market research", "competitor_intelligence", settings.competitor_url, "Checks approved public sites for useful business changes"),
    ]
    for label, key, endpoint, purpose in definitions:
        result = connections.get(key) or {"status": "NOT TESTED", "detail": "Run connection test"}
        rows.append([esc(label), badge(result.get("status")), esc(purpose)])
        advanced_rows.append([esc(label), f"<span class='mono'>{esc(endpoint)}</span>", esc(result.get("detail") or "")])
    connection_table = table(("Service", "Status", "What it does"), rows)
    endpoint_table = table(("Service", "Server address", "Last result"), advanced_rows)
    mode_options = lambda current: "".join(
        f"<option value='{value}' {'selected' if current == value else ''}>{label}</option>"
        for value, label in (("FULL_LOCAL", "Full local application"), ("LOCAL_MOCK", "Local simulator"), ("SANDBOX", "Provider sandbox"), ("PRODUCTION", "Production later"))
    )
    body = f"""
<div class='callout advanced-banner'><b>Installer area:</b> everyday staff do not need to change anything on this page. Use <a href='/office/settings'>Settings &amp; Setup</a> for normal business choices. This page never displays or accepts provider passwords, access tokens, or card credentials.</div>
<div class='card'><div class='actions spread'><div><h2>Are Floodman services answering?</h2><p class='muted'>The check is safe: it reads service health and does not send customer messages, charge a card, or change production data.</p></div><form method='post' action='/setup/test-connections'><button class='good'>Run connection check</button></form></div><div class='connection-simple-table'>{connection_table}</div><div class='actions' style='margin-top:14px'><a class='button' href='/office/apps'>Open applications</a><a class='button secondary' href='/office/linking/checklist.txt'>Download installer checklist</a></div></div>
<details class='card plain-details'><summary>Advanced: server addresses and connection plan</summary><div style='margin-top:14px'>{endpoint_table}</div><p class='muted'>Change these planning values only when an installer gives you reviewed replacements. Saving this form records a plan; the server owner must still apply secrets outside the browser.</p><form method='post' action='/office/linking/plan'><div class='form-grid'>
<div class='field full'><label>RoomFlow web address</label><input type='url' name='roomflow_url' value='{esc(config.get('roomflow_url'))}'></div>
<div class='field'><label>Floodman ERP mode</label><select name='gauzy_mode'>{mode_options(config.get('gauzy_mode'))}</select></div><div class='field'><label>Floodman ERP API base URL</label><input name='gauzy_base_url' value='{esc(config.get('gauzy_base_url'))}'></div>
<div class='field'><label>Payment processor mode</label><select name='square_mode'>{mode_options(config.get('square_mode'))}</select></div><div class='field'><label>Payment processor API base URL</label><input name='square_base_url' value='{esc(config.get('square_base_url'))}'></div>
<div class='field'><label>Payment location ID</label><input name='square_location_id' value='{esc(config.get('square_location_id'))}'></div><div class='field'><label>Documenso mode</label><select name='documenso_mode'>{mode_options(config.get('documenso_mode'))}</select></div>
<div class='field'><label>Documenso API base URL</label><input name='documenso_base_url' value='{esc(config.get('documenso_base_url'))}'></div><div class='field'><label>Twilio mode</label><select name='twilio_mode'>{mode_options(config.get('twilio_mode'))}</select></div>
<div class='field'><label>Twilio API base URL</label><input name='twilio_base_url' value='{esc(config.get('twilio_base_url'))}'></div><div class='field'><label>Twilio Account SID</label><input name='twilio_account_sid' value='{esc(config.get('twilio_account_sid'))}'></div>
<div class='field'><label>Twilio Messaging Service SID</label><input name='twilio_messaging_service_sid' value='{esc(config.get('twilio_messaging_service_sid'))}'></div><div class='field'><label>SMTP mode</label><select name='smtp_mode'><option value='LOCAL_CAPTURE' {'selected' if config.get('smtp_mode') == 'LOCAL_CAPTURE' else ''}>Local capture</option><option value='SANDBOX' {'selected' if config.get('smtp_mode') == 'SANDBOX' else ''}>Test mailbox</option><option value='PRODUCTION' {'selected' if config.get('smtp_mode') == 'PRODUCTION' else ''}>Production later</option></select></div>
<div class='field'><label>SMTP host</label><input name='smtp_host' value='{esc(config.get('smtp_host'))}'></div><div class='field'><label>SMTP port</label><input type='number' name='smtp_port' value='{esc(config.get('smtp_port'))}'></div>
<div class='field'><label>Messaging AI provider</label><select name='messaging_ai_provider'><option value='deterministic' {'selected' if config.get('messaging_ai_provider') == 'deterministic' else ''}>Deterministic local policy</option><option value='openai' {'selected' if config.get('messaging_ai_provider') == 'openai' else ''}>OpenAI after approval</option></select></div>
</div><div class='actions' style='margin-top:14px'><button>Save reviewed connection plan</button><a class='button secondary' href='/office/linking/env-snippet.txt'>Download server configuration template</a></div></form></details>
<div class='card'><h2>Application launch</h2><div class='actions'><a class='button' href='{esc(settings.gauzy_web_url)}' target='_blank'>Floodman ERP</a><a class='button' href='{esc(settings.documenso_web_url)}' target='_blank'>Documenso</a><a class='button' href='{esc(settings.roomflow_url)}' target='_blank'>RoomFlow</a><a class='button secondary' href='{esc(settings.mailpit_url)}' target='_blank'>Mailpit</a><a class='button secondary' href='{esc(settings.engineering_public_url)}/lab' target='_blank'>Engineering Sandbox</a></div><p class='muted'>Start everything with <code>Start-Floodman-Full-System.cmd</code>.</p></div>
<details class='card plain-details'><summary>Advanced: RoomFlow server bridge values</summary><p>The HMAC secret belongs in the authenticated Supabase Edge Function or another server-side worker, never browser JavaScript.</p><pre>FLOODMAN_ORCHESTRATOR_URL={settings.api_public_url}
FLOODMAN_ORCHESTRATOR_KEY_ID=v1
FLOODMAN_ORCHESTRATOR_HMAC_SECRET=&lt;base64 secret from server configuration&gt;</pre></details>
"""
    return _page("Advanced Connections", body, "linking")


@app.post("/office/linking/plan")
def save_link_plan(
    roomflow_url: str = Form(default=""),
    gauzy_mode: str = Form(default="LOCAL_MOCK"),
    gauzy_base_url: str = Form(default=""),
    square_mode: str = Form(default="LOCAL_MOCK"),
    square_base_url: str = Form(default=""),
    square_location_id: str = Form(default=""),
    documenso_mode: str = Form(default="LOCAL_MOCK"),
    documenso_base_url: str = Form(default=""),
    twilio_mode: str = Form(default="LOCAL_MOCK"),
    twilio_base_url: str = Form(default=""),
    twilio_account_sid: str = Form(default=""),
    twilio_messaging_service_sid: str = Form(default=""),
    smtp_mode: str = Form(default="LOCAL_CAPTURE"),
    smtp_host: str = Form(default=""),
    smtp_port: int = Form(default=1025),
    messaging_ai_provider: str = Form(default="deterministic"),
) -> RedirectResponse:
    _require("connections.manage")
    mode_values = {"FULL_LOCAL", "LOCAL_MOCK", "SANDBOX", "PRODUCTION"}
    if any(value not in mode_values for value in (gauzy_mode, square_mode, documenso_mode, twilio_mode)):
        store.set_notice("Choose one of the listed connection modes.")
        return RedirectResponse("/office/linking", status_code=303)
    if smtp_mode not in {"LOCAL_CAPTURE", "SANDBOX", "PRODUCTION"}:
        store.set_notice("Choose one of the listed email modes.")
        return RedirectResponse("/office/linking", status_code=303)
    if messaging_ai_provider not in {"deterministic", "openai"}:
        store.set_notice("Choose one of the listed message-assistant policies.")
        return RedirectResponse("/office/linking", status_code=303)
    store.update_link_config(
        {
            "roomflow_url": roomflow_url.strip(), "gauzy_mode": gauzy_mode, "gauzy_base_url": gauzy_base_url.strip(),
            "square_mode": square_mode, "square_base_url": square_base_url.strip(),
            "square_location_id": square_location_id.strip(), "documenso_mode": documenso_mode,
            "documenso_base_url": documenso_base_url.strip(), "twilio_mode": twilio_mode,
            "twilio_base_url": twilio_base_url.strip(), "twilio_account_sid": twilio_account_sid.strip(),
            "twilio_messaging_service_sid": twilio_messaging_service_sid.strip(), "smtp_mode": smtp_mode,
            "smtp_host": smtp_host.strip(), "smtp_port": max(1, min(int(smtp_port), 65535)),
            "messaging_ai_provider": messaging_ai_provider,
        }
    )
    return RedirectResponse("/office/linking", status_code=303)


def _environment_snippet() -> str:
    config = store.link_config()
    return f"""# Floodman connection plan generated by the Business Suite
# Copy reviewed values into C:\\FloodmanLab\\.env.windows. Replace every CHANGE_ME value.

# RoomFlow server-side bridge
ROOMFLOW_WEB_URL={config.get('roomflow_url', '')}
FLOODMAN_ORCHESTRATOR_URL={settings.api_public_url}
FLOODMAN_ORCHESTRATOR_KEY_ID=v1
FLOODMAN_ORCHESTRATOR_HMAC_SECRET=CHANGE_ME_SERVER_SIDE_ONLY

# Floodman ERP
# The embedded ERP connection is configured automatically by the Floodman runtime.

# Square ({config.get('square_mode')})
SQUARE_BASE_URL={config.get('square_base_url', '')}
SQUARE_ACCESS_TOKEN=CHANGE_ME
SQUARE_LOCATION_ID={config.get('square_location_id', '')}
SQUARE_WEBHOOK_SIGNATURE_KEY=CHANGE_ME

# Documenso ({config.get('documenso_mode')})
DOCUMENSO_BASE_URL={config.get('documenso_base_url', '')}
DOCUMENSO_API_TOKEN=CHANGE_ME
DOCUMENSO_WEBHOOK_SECRET=CHANGE_ME

# Twilio ({config.get('twilio_mode')})
TWILIO_BASE_URL={config.get('twilio_base_url', '')}
TWILIO_ACCOUNT_SID={config.get('twilio_account_sid', '')}
TWILIO_AUTH_TOKEN=CHANGE_ME
TWILIO_MESSAGING_SERVICE_SID={config.get('twilio_messaging_service_sid', '')}

# Email ({config.get('smtp_mode')})
SMTP_HOST={config.get('smtp_host', '')}
SMTP_PORT={config.get('smtp_port', 1025)}
SMTP_USERNAME=CHANGE_ME_IF_REQUIRED
SMTP_PASSWORD=CHANGE_ME_IF_REQUIRED

# AI
MESSAGING_AI_PROVIDER={config.get('messaging_ai_provider', 'deterministic')}
OPENAI_MESSAGING_API_KEY=CHANGE_ME_ONLY_IF_APPROVED
"""


@app.get("/office/linking/env-snippet.txt", response_class=PlainTextResponse)
def environment_snippet() -> str:
    return _environment_snippet()


@app.get("/office/linking/checklist.txt", response_class=PlainTextResponse)
def linking_checklist() -> str:
    return f"""Floodman Business Suite linking checklist

Current mode: local simulator
Floodman Operations Hub: {settings.gauzy_hub_url}
Floodman modules: {settings.public_url}/office
Direct Office diagnostic: internal port 8700 (not a public Pterodactyl allocation)
Engineering lab: {esc(settings.engineering_public_url)}
Orchestrator: {esc(settings.api_public_url)}

1. Save a non-secret connection plan in Floodman Office.
2. Download /office/linking/env-snippet.txt.
3. Put credentials only in C:\\FloodmanLab\\.env.windows.
4. Restart the Floodman Pterodactyl server.
5. Run Test all running connections.
6. Complete sandbox acceptance before any production credentials are used.

Never paste provider tokens into RoomFlow browser JavaScript, Android assets, GitHub, screenshots, or customer-facing pages.
"""


@app.get("/office/imports")
def imports_page() -> HTMLResponse:
    _require("imports.manage")
    imports = store.list_imports()
    history_rows = []
    for run in imports:
        counts = run.get("counts") or {}
        if run.get("import_kind") == "CUSTOMERS_CSV":
            total_records = int(counts.get("customers_ready") or 0)
            import_type = "Customer CSV"
            attachments = 0
        elif run.get("import_kind") == XACTIMATE_IMPORT_KIND:
            total_records = int(counts.get("items_ready") or 0)
            import_type = "Xactimate pricing CSV"
            attachments = 0
        else:
            total_records = sum(int(counts.get(key) or 0) for key in (
                "contacts", "properties", "estimates", "estimate_lines", "invoices", "payments", "documents", "notes"
            ))
            import_type = "Business archive ZIP"
            attachments = counts.get("attachments", counts.get("pdfs", 0))
        history_rows.append([
            esc(run.get("created_at", "")[:19].replace("T", " ")),
            esc(import_type),
            badge(run.get("status")),
            esc(total_records),
            esc(attachments),
            f"<a href='/office/imports/{esc(run.get('id'))}'>Review</a>",
        ])
    history = table(
        ("Created", "Import type", "Status", "Records", "Attachments", "Open"),
        history_rows,
        "No imports have been uploaded.",
    )
    body = f"""
<div class='callout success'><b>Your original file is never changed.</b> Floodman first opens a private preview, explains anything that needs correction, and waits for your confirmation before saving records.</div>
<div class='role-guide'><div><b>1. Choose your file</b><small>Use the customer CSV you already have, or a complete business archive ZIP.</small></div><div><b>2. Review the preview</b><small>Floodman lists matched customers, new records, warnings, and files before writing.</small></div><div><b>3. Confirm the import</b><small>Only an owner-approved confirmation saves the validated records.</small></div></div>
<div class='card import-upload-card'>
  <div class='import-upload-copy'><span class='mobile-hero-kicker'>SAFE PREVIEW</span><h2>Choose a customer CSV or business archive ZIP</h2><p>Choose the exact <b>Clients.csv</b> export you already have, or a ZIP with complete business history. Floodman recognizes the format for you.</p></div>
  <form method='post' action='/office/imports/upload-any' enctype='multipart/form-data' class='import-upload-form'>
    <label class='file-drop-field'><span class='file-drop-icon'>⇩</span><b>Select a CSV or ZIP file</b><small>Accepted: .csv and .zip · Maximum request size 50 MB through the Hub</small><input type='file' name='import_file' accept='.csv,.zip,text/csv,application/zip,application/x-zip-compressed' required></label>
    <button class='good'>Open safe preview</button>
  </form>
  <div class='import-format-grid'>
    <div><b>Customer CSV</b><span>Creates or matches customer files and service properties. No emails, texts, invoices, charges, or reminders are sent.</span></div>
    <div><b>Business archive ZIP</b><span>Imports the normalized multi-file archive with estimates, invoices, payments, documents, notes, and attachments.</span></div>
  </div>
  <div class='actions'><a class='button secondary' href='/office/imports/customers/template.csv'>Customer CSV template</a><a class='button secondary' href='/office/imports/templates.zip'>Archive templates ZIP</a><a class='button secondary' href='/office/imports/sample.zip'>Sample archive ZIP</a></div>
</div>
<div class='card'><h2>Import history</h2>{history}</div>
<details class='card plain-details'><summary>What Floodman keeps and how duplicates are prevented</summary><p>Original customer IDs, names, company, email, phone, service address, notes, lead source, properties, estimate revisions, invoices, payments, PDFs, signed documents, timestamps, and provider references are retained whenever available. Stable source identifiers update an existing imported record instead of duplicating it. Historical balances remain archive values and are not enrolled in payment reminders automatically.</p></details>
"""
    return _page("Import CSV or ZIP", body, "imports")


def _looks_like_zip(filename: str, data: bytes) -> bool:
    return filename.lower().endswith(".zip") or data.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))


def _customer_csv_from_zip(data: bytes) -> tuple[str, bytes, dict[str, bytes]] | None:
    files = unpack_zip(data)
    csv_files = [(path, content) for path, content in files.items() if Path(path).suffix.lower() == ".csv"]
    if not csv_files:
        return None
    archive_markers = {"contacts.csv", "properties.csv", "estimates.csv", "estimate_lines.csv", "invoices.csv", "payments.csv"}
    bases = {Path(path).name.lower() for path, _content in csv_files}
    if bases & archive_markers:
        return None
    preferred = [item for item in csv_files if Path(item[0]).name.lower() in {"clients.csv", "customers.csv", "client.csv", "customer.csv"}]
    if len(preferred) == 1:
        path, content = preferred[0]
        return path, content, files
    if len(csv_files) == 1:
        path, content = csv_files[0]
        return path, content, files
    return None


@app.post("/office/imports/upload-any")
async def upload_any_import(import_file: UploadFile = File(...)) -> RedirectResponse:
    _require("imports.manage")
    filename = Path(import_file.filename or "import").name
    data = await import_file.read()
    if not data:
        store.set_notice("Import upload failed: the selected file is empty.")
        return RedirectResponse("/office/imports", status_code=303)

    try:
        if _looks_like_zip(filename, data):
            customer_zip = _customer_csv_from_zip(data)
            if customer_zip is not None:
                csv_name, csv_data, extracted = customer_zip
                result = parse_customer_csv(csv_data, Path(csv_name).name)
                summary = {
                    **result.summary,
                    "included_files": sorted(extracted),
                    "uploaded_container": filename,
                    "totals": result.summary.get("totals") or {},
                }
                run_id = store.create_import(summary, result.normalized, extracted)
            else:
                files = bundle_files(filename, data, {})
                summary, normalized = validate(files)
                run_id = store.create_import(summary, normalized, files)
        else:
            if not filename.lower().endswith(".csv"):
                raise CustomerCsvError("Choose a .csv customer list or a .zip business archive.")
            result = parse_customer_csv(data, filename)
            summary = {
                **result.summary,
                "included_files": [filename],
                "totals": result.summary.get("totals") or {},
            }
            run_id = store.create_import(summary, result.normalized, {filename: data})
    except (CustomerCsvError, ImportValidationError, zipfile.BadZipFile) as exc:
        store.set_notice(f"Import upload failed: {exc}")
        return RedirectResponse("/office/imports", status_code=303)
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.get("/office/imports/customers/template.csv")
def download_customer_template() -> Response:
    _require("imports.manage")
    return Response(
        customer_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="floodman-customer-import-template.csv"'},
    )


@app.post("/office/imports/customers/upload")
async def upload_customer_csv(customers_csv: UploadFile = File(...)) -> RedirectResponse:
    _require("imports.manage")
    data = await customers_csv.read()
    try:
        result = parse_customer_csv(data, customers_csv.filename or "customers.csv")
        summary = {
            **result.summary,
            "included_files": [customers_csv.filename or "customers.csv"],
            "totals": {},
        }
        run_id = store.create_import(
            summary,
            result.normalized,
            {customers_csv.filename or "customers.csv": data},
        )
    except CustomerCsvError as exc:
        store.set_notice(f"Customer CSV upload failed: {exc}")
        return RedirectResponse("/office/imports", status_code=303)
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.post("/office/imports/upload")
async def upload_import(
    bundle: UploadFile | None = File(default=None),
    contacts: UploadFile | None = File(default=None),
    properties: UploadFile | None = File(default=None),
    estimates: UploadFile | None = File(default=None),
    estimate_lines: UploadFile | None = File(default=None),
    invoices: UploadFile | None = File(default=None),
    payments: UploadFile | None = File(default=None),
    documents: UploadFile | None = File(default=None),
    notes: UploadFile | None = File(default=None),
) -> RedirectResponse:
    bundle_data = await bundle.read() if bundle and bundle.filename else None
    individual: dict[str, bytes] = {}
    uploads = (
        ("contacts.csv", contacts),
        ("properties.csv", properties),
        ("estimates.csv", estimates),
        ("estimate_lines.csv", estimate_lines),
        ("invoices.csv", invoices),
        ("payments.csv", payments),
        ("documents.csv", documents),
        ("notes.csv", notes),
    )
    for name, upload in uploads:
        if upload and upload.filename:
            individual[name] = await upload.read()
    try:
        files = bundle_files(bundle.filename if bundle else None, bundle_data, individual)
        summary, normalized = validate(files)
        run_id = store.create_import(summary, normalized, files)
    except ImportValidationError as exc:
        store.set_notice(f"Import upload failed: {exc}")
        return RedirectResponse("/office/imports", status_code=303)
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.get("/office/imports/templates.zip")
def download_templates() -> Response:
    return Response(
        create_zip(template_files()),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="floodman-migration-templates.zip"'},
    )


@app.get("/office/imports/sample.zip")
def download_sample() -> Response:
    return Response(
        create_zip(sample_files()),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="floodman-sample-import.zip"'},
    )



def _customer_import_detail(run: dict[str, Any]) -> HTMLResponse:
    run_id = str(run["id"])
    counts = run.get("counts") or {}
    totals = run.get("totals") or {}
    profile = str(run.get("import_profile") or "GENERIC_CUSTOMER_CSV")
    mapping = run.get("column_mapping") or {}
    mapping_rows = [[esc(target.replace("_", " ").title()), esc(source)] for target, source in sorted(mapping.items())]
    errors = "".join(f"<li>{esc(value)}</li>" for value in run.get("errors") or []) or "<li>None</li>"
    warning_values = list(run.get("warnings") or [])
    warnings = "".join(f"<li>{esc(value)}</li>" for value in warning_values[:100]) or "<li>None</li>"
    if len(warning_values) > 100:
        warnings += f"<li>…and {esc(len(warning_values) - 100)} additional row warnings retained in the validation record.</li>"
    try:
        normalized = store.read_normalized(run_id)
        customers = list(normalized.get("customers") or [])
    except Exception:
        customers = []

    def display_address(item: dict[str, Any]) -> str:
        mailing = item.get("mailing_address") or {}
        raw = str(mailing.get("raw") or "")
        if raw:
            return raw
        properties = list(item.get("properties") or [])
        return str((properties[0] if properties else {}).get("raw_address") or "")

    preview_rows = [
        [
            esc(item.get("name") or ""),
            esc(item.get("email") or item.get("email_raw") or ""),
            esc(item.get("phone") or ""),
            esc(display_address(item)),
            esc(len(item.get("properties") or [])),
            badge(item.get("status") or "ACTIVE"),
            esc(", ".join(item.get("quality_flags") or [])),
        ]
        for item in customers[:50]
    ]
    action = ""
    if run.get("status") == "PREVIEWED" and not run.get("errors"):
        action = (
            f"<form method='post' action='/office/imports/{esc(run_id)}/commit'>"
            f"<button class='good'>Import {esc(counts.get('customers_ready', 0))} customer files and "
            f"{esc(counts.get('properties_ready', 0))} properties</button></form>"
        )
    elif run.get("status") == "COMMITTED":
        result = run.get("commit_result") or {}
        remaining = int(run.get("sync_remaining") or 0)
        sync_action = ""
        if remaining and settings.gauzy_sync_enabled:
            sync_action = f"<form method='post' action='/office/imports/{esc(run_id)}/sync-customers'><button>Sync next 100 to Floodman ERP</button></form>"
        action = f"""<div class='callout success'><b>Customer import completed.</b><br>
        Created: {esc(result.get('created',0))} · Updated/matched: {esc(result.get('matched',0))} ·
        Properties created: {esc(result.get('properties_created', result.get('properties',0)))} ·
        Properties matched: {esc(result.get('properties_matched',0))} ·
        Duplicate contact rows merged: {esc(counts.get('duplicate_contact_rows_merged',0))}<br>
        Waiting for ERP sync: {remaining}</div>{sync_action}"""
    elif run.get("status") == "FAILED":
        action = f"<div class='callout danger'>{esc(run.get('commit_error') or 'Customer import failed.')}</div>"

    profile_label = "Floodman client export detected" if profile == "MATTER_CLIENT_EXPORT_V1" else "Generic customer CSV"
    status_rows = [[esc(key.replace("_", " ").title()), esc(value)] for key, value in sorted((run.get("status_counts") or {}).items())]
    body = f"""
<div class='callout success'><b>{esc(profile_label)}</b><br>Floodman recognized all {esc(len(run.get('headers') or []))} source columns and will retain the original row values with each customer file.</div>
<div class='grid metrics-grid'>
  <div class='card metric'><small>CSV rows</small><strong>{esc(counts.get('rows_read',0))}</strong></div>
  <div class='card metric'><small>Customer files</small><strong>{esc(counts.get('customers_ready',0))}</strong></div>
  <div class='card metric'><small>Properties</small><strong>{esc(counts.get('properties_ready',0))}</strong></div>
  <div class='card metric'><small>Duplicate rows merged</small><strong>{esc(counts.get('duplicate_contact_rows_merged',0))}</strong></div>
  <div class='card metric'><small>With email</small><strong>{esc(counts.get('with_email',0))}</strong></div>
  <div class='card metric'><small>With phone</small><strong>{esc(counts.get('with_phone',0))}</strong></div>
  <div class='card metric'><small>No email or phone</small><strong>{esc(counts.get('without_email_or_phone',0))}</strong></div>
  <div class='card metric'><small>Needs review</small><strong>{esc(counts.get('needs_review',0))}</strong></div>
</div>
<div class='grid two'>
  <div class='card'><h2>Historical values retained as reference</h2><p class='muted'>These amounts are saved as source metadata only. They do not create estimates, invoices, payments, or receivables.</p>
    <div class='grid'><div class='metric'><small>Pending estimates</small><strong>{money_cents(totals.get('historical_pending_estimates_cents'))}</strong></div>
    <div class='metric'><small>Open payments</small><strong>{money_cents(totals.get('historical_open_payments_cents'))}</strong></div>
    <div class='metric'><small>Approved estimates</small><strong>{money_cents(totals.get('historical_approved_estimates_cents'))}</strong></div></div>
  </div>
  <div class='card'><h2>Communication safeguards</h2><div class='grid'><div class='metric'><small>Transactional opt-in</small><strong>{esc(counts.get('transactional_opt_in',0))}</strong></div><div class='metric'><small>Promotional opt-in</small><strong>{esc(counts.get('promotional_opt_in',0))}</strong></div><div class='metric'><small>Unsubscribed</small><strong>{esc(counts.get('unsubscribed',0))}</strong></div><div class='metric'><small>Email blocked</small><strong>{esc(counts.get('email_blocked',0))}</strong></div></div></div>
</div>
<div class='card'><h2>Detected column mapping</h2>{table(('Floodman field','CSV column'), mapping_rows, 'No columns were mapped.')}{('<p class="muted"><b>Ignored columns:</b> '+esc(', '.join(run.get('ignored_columns') or []))+'</p>') if run.get('ignored_columns') else '<p class="muted">Every source column is recognized or retained as source metadata.</p>'}</div>
<div class='grid two'><div class='card'><h2>Customer status summary</h2>{table(('Status','Customers'), status_rows, 'No statuses found.')}</div><div class='card'><h2>Validation warnings</h2><ul>{warnings}</ul><details><summary>Errors</summary><ul>{errors}</ul></details></div></div>
<div class='card'><h2>Customer preview</h2>{table(('Name','Email','Phone','Address','Properties','Status','Review flags'), preview_rows, 'No valid customers were found.')}{'<p class="muted">Showing the first 50 customer files after duplicate rows were merged.</p>' if len(customers)>50 else ''}</div>
<div class='card'><h2>Import action</h2><p>Floodman matches customer files by original customer ID, email, phone, and stable name/address identity. Multiple rows for the same person are merged while distinct property addresses remain attached. Nothing is emailed, texted, invoiced, charged, or enrolled in receivables during this import.</p><div class='actions'>{action}<a class='button secondary' href='/office/imports'>Back to imports</a></div></div>
<div class='card'><details><summary>Full validation record</summary>{json_pre(run)}</details></div>
"""
    return _page("Customer CSV Review", body, "imports")


def _customer_identity(source_sha: str, item: dict[str, Any]) -> str:
    # Prefer a stable customer identity that survives later exports of the same
    # list. Use the file hash only as a last resort when a row has no usable ID,
    # contact method, name, or address.
    value = str(
        item.get("external_id")
        or item.get("email")
        or item.get("dedupe_key")
        or item.get("phone_normalized")
        or item.get("name")
        or source_sha
        or uuid.uuid4()
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-customer-csv:{value.lower().strip()}"))


async def _commit_customer_csv(run_id: str, run: dict[str, Any], actor: dict[str, Any]) -> dict[str, Any]:
    normalized = store.read_normalized(run_id)
    customers = list(normalized.get("customers") or [])
    source_sha = str(normalized.get("source_sha256") or run.get("source_sha256") or run_id)
    actor_id = str(actor.get("id") or "")

    current_contacts = {str(item.get("id") or ""): item for item in store.records("contacts") if item.get("id")}
    current_properties = {str(item.get("id") or ""): item for item in store.records("properties") if item.get("id")}
    email_index: dict[str, str] = {}
    phone_index: dict[str, list[str]] = {}
    external_index: dict[str, str] = {}
    for contact_id, item in current_contacts.items():
        email_key = str(item.get("email") or item.get("primaryEmail") or "").strip().lower()
        if email_key:
            email_index[email_key] = contact_id
        phone_key = re.sub(r"\D", "", str(item.get("phone_normalized") or item.get("phone") or item.get("primaryPhone") or ""))
        if len(phone_key) == 11 and phone_key.startswith("1"):
            phone_key = phone_key[1:]
        if len(phone_key) >= 10:
            phone_index.setdefault(phone_key[-10:], []).append(contact_id)
        for field in ("legacy_contact_id", "customer_external_id", "external_id", "provider_id", "erp_contact_id", "full_gauzy_id"):
            value = str(item.get(field) or "").strip()
            if value:
                external_index[value] = contact_id

    contact_payloads: list[dict[str, Any]] = []
    property_payloads: list[dict[str, Any]] = []
    contact_ids: list[str] = []
    created = 0
    matched = 0
    properties_created = 0
    properties_matched = 0

    for item in customers:
        deterministic_contact_id = _customer_identity(source_sha, item)
        external_key = str(item.get("external_id") or "").strip()
        email_key = str(item.get("email") or "").strip().lower()
        phone_key = re.sub(r"\D", "", str(item.get("phone_normalized") or item.get("phone") or ""))
        if len(phone_key) == 11 and phone_key.startswith("1"):
            phone_key = phone_key[1:]
        phone_key = phone_key[-10:] if len(phone_key) >= 10 else ""
        contact_id = ""
        if deterministic_contact_id in current_contacts:
            contact_id = deterministic_contact_id
        elif external_key and external_index.get(external_key):
            contact_id = external_index[external_key]
        elif email_key and email_index.get(email_key):
            contact_id = email_index[email_key]
        elif phone_key and not email_key:
            # Phone numbers are sometimes shared by spouses, companies, or
            # stale exports. Match by phone only when the customer name also
            # agrees; otherwise preserve separate customer files.
            wanted_name = re.sub(r"[^a-z0-9]+", "", str(item.get("name") or "").lower())
            for candidate_id in phone_index.get(phone_key, []):
                candidate = current_contacts.get(candidate_id) or {}
                candidate_name = re.sub(r"[^a-z0-9]+", "", str(candidate.get("name") or "").lower())
                candidate_email = str(candidate.get("email") or candidate.get("primaryEmail") or "").strip()
                if not candidate_email and wanted_name and candidate_name and wanted_name == candidate_name:
                    contact_id = candidate_id
                    break
        contact_id = contact_id or deterministic_contact_id
        exists = contact_id in current_contacts
        created += 0 if exists else 1
        matched += 1 if exists else 0

        mailing = dict(item.get("mailing_address") or {})
        values: dict[str, Any] = {
            "id": contact_id,
            "first_name": str(item.get("first_name") or ""),
            "last_name": str(item.get("last_name") or ""),
            "name": str(item.get("name") or "Customer"),
            "company": str(item.get("company") or ""),
            "email": str(item.get("email") or ""),
            "email_raw": str(item.get("email_raw") or ""),
            "secondary_emails": list(item.get("secondary_emails") or []),
            "phone": str(item.get("phone") or ""),
            "phone_normalized": str(item.get("phone_normalized") or ""),
            "mailing_address_raw": str(mailing.get("raw") or ""),
            "mailing_street": str(mailing.get("street") or ""),
            "mailing_street2": str(mailing.get("street2") or ""),
            "mailing_city": str(mailing.get("city") or ""),
            "mailing_state": str(mailing.get("state") or ""),
            "mailing_postal_code": str(mailing.get("postal_code") or ""),
            "mailing_country": str(mailing.get("country") or "US"),
            "mailing_address": mailing,
            "additional_mailing_addresses": list(item.get("additional_mailing_addresses") or []),
            "lead_source": str(item.get("lead_source") or ""),
            "source_channel": str(item.get("source_channel") or ""),
            "source_campaign": str(item.get("source_campaign") or ""),
            "source_url": str(item.get("source_url") or ""),
            "notes": str(item.get("notes") or ""),
            "tags": list(item.get("tags") or []),
            "assigned_staff": str(item.get("assigned_staff") or ""),
            "assigned_staff_history": list(item.get("assigned_staff_history") or []),
            "last_activity_at": str(item.get("last_activity_at") or ""),
            "last_activity_action": str(item.get("last_activity_action") or ""),
            "next_booking": str(item.get("next_booking") or ""),
            "time_zone": str(item.get("time_zone") or "America/Detroit"),
            "preferred_language": str(item.get("preferred_language") or "en"),
            "review_score": str(item.get("review_score") or ""),
            "birthday": str(item.get("birthday") or ""),
            "referred_by": str(item.get("referred_by") or ""),
            "unsubscribed": bool(item.get("unsubscribed")),
            "email_blocked": bool(item.get("email_blocked")),
            "transactional_opt_in": bool(item.get("transactional_opt_in")),
            "promotional_opt_in": bool(item.get("promotional_opt_in")),
            "historical_pending_estimates_cents": int(item.get("pending_estimates_cents") or 0),
            "historical_open_payments_cents": int(item.get("open_payments_cents") or 0),
            "historical_approved_estimates_cents": int(item.get("approved_estimates_cents") or 0),
            "source_status": str(item.get("source_status") or ""),
            "status": str(item.get("status") or "ACTIVE"),
            "quality_flags": list(item.get("quality_flags") or []),
            "legacy_contact_id": external_key or None,
            "customer_external_id": external_key or None,
            "import_run_id": run_id,
            "import_profile": str(run.get("import_profile") or normalized.get("import_profile") or "CUSTOMER_CSV"),
            "source_rows": list(item.get("source_rows") or []),
            "source_row_count": int(item.get("source_row_count") or 1),
            "source_records": list(item.get("source_records") or []),
            "source_file_sha256": source_sha,
            "source": "CUSTOMER_CSV",
            "created_by_name": "Josh Aldrich",
            "creator_display": "Created by Josh Aldrich",
        }
        source_created_at = str(item.get("created_at") or "")
        if source_created_at:
            values["source_created_at"] = source_created_at
        contact_payloads.append(values)
        contact_ids.append(contact_id)
        current_contacts[contact_id] = {**current_contacts.get(contact_id, {}), **values}
        if external_key:
            external_index[external_key] = contact_id
        if email_key:
            email_index[email_key] = contact_id
        if phone_key:
            bucket = phone_index.setdefault(phone_key, [])
            if contact_id not in bucket:
                bucket.append(contact_id)

        for property_item in list(item.get("properties") or []):
            raw_address = str(property_item.get("raw_address") or property_item.get("raw") or "").strip()
            if not raw_address:
                continue
            property_identity = re.sub(r"[^a-z0-9]+", "", raw_address.lower()) or raw_address.lower()
            property_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-customer-property:{contact_id}:{property_identity}"))
            street = str(property_item.get("street") or "").strip() or raw_address
            property_values = {
                "id": property_id,
                "contact_id": contact_id,
                "name": str(property_item.get("name") or property_item.get("property_name") or raw_address),
                "property_name": str(property_item.get("property_name") or property_item.get("name") or raw_address),
                "service_street": street,
                "service_street2": str(property_item.get("street2") or ""),
                "service_city": str(property_item.get("city") or ""),
                "service_state": str(property_item.get("state") or ""),
                "service_postal_code": str(property_item.get("postal_code") or ""),
                "country": str(property_item.get("country") or "US"),
                "property_type": str(property_item.get("property_type") or "Unspecified"),
                "record_type": "SERVICE_PROPERTY",
                "raw_service_address": raw_address,
                "service_address": {
                    "raw": raw_address,
                    "street": street,
                    "street2": str(property_item.get("street2") or ""),
                    "city": str(property_item.get("city") or ""),
                    "state": str(property_item.get("state") or ""),
                    "postal_code": str(property_item.get("postal_code") or ""),
                    "country": str(property_item.get("country") or "US"),
                    "parse_confidence": str(property_item.get("parse_confidence") or ""),
                },
                "help_request": str(property_item.get("help_request") or ""),
                "special_instructions": str(property_item.get("special_instructions") or ""),
                "source_row": int(property_item.get("source_row") or 0),
                "source": "CUSTOMER_CSV",
                "import_run_id": run_id,
                "created_by_name": "Josh Aldrich",
                "creator_display": "Created by Josh Aldrich",
            }
            if property_id in current_properties:
                properties_matched += 1
            else:
                properties_created += 1
            current_properties[property_id] = {**current_properties.get(property_id, {}), **property_values}
            property_payloads.append(property_values)

    store.bulk_upsert_records(
        {"contacts": contact_payloads, "properties": property_payloads},
        actor_id=actor_id,
    )
    gauzy_mappings = store.external_mappings("gauzy")
    remaining = sum(1 for contact_id in contact_ids if not gauzy_mappings.get(f"contact:{contact_id}"))
    return {
        "created": created,
        "matched": matched,
        "properties": properties_created,
        "properties_created": properties_created,
        "properties_matched": properties_matched,
        "contact_ids": contact_ids,
        "sync_remaining": remaining,
    }


def _xactimate_import_detail(run: dict[str, Any]) -> HTMLResponse:
    _require("estimates.manage")
    run_id = str(run["id"])
    counts = run.get("counts") or {}
    try:
        normalized = store.read_normalized(run_id)
        items = list(normalized.get("catalog_items") or [])
    except Exception:
        items = []
    preview_rows = []
    for item in items[:100]:
        metadata = ((item.get("formula") or {}).get("xactimate") or {})
        preview_rows.append([
            esc(metadata.get("code") or item.get("source_id") or ""),
            esc(item.get("name") or ""),
            esc(item.get("category") or ""),
            esc(item.get("unit") or ""),
            money_cents(item.get("unit_price_cents")),
            esc(metadata.get("effective_date") or "Needs review"),
        ])
    warning_values = list(run.get("warnings") or [])
    warnings = "".join(f"<li>{esc(value)}</li>" for value in warning_values[:100]) or "<li>None</li>"
    if len(warning_values) > 100:
        warnings += f"<li>…and {esc(len(warning_values) - 100)} additional warnings retained with this preview.</li>"
    action = ""
    if run.get("status") == "PREVIEWED" and not run.get("errors"):
        action = (
            f"<form method='post' action='/office/imports/{esc(run_id)}/commit'>"
            f"<button class='good'>Import {esc(counts.get('items_ready', 0))} reviewed prices</button></form>"
        )
    elif run.get("status") == "COMMITTED":
        result = run.get("commit_result") or {}
        action = (
            "<div class='callout success'><b>Pricing import completed.</b><br>"
            f"Added: {esc(result.get('added', 0))} · Updated: {esc(result.get('updated', 0))} · "
            f"Skipped: {esc(result.get('skipped', 0))}</div>"
        )
    elif run.get("status") == "FAILED":
        action = f"<div class='callout danger'>{esc(run.get('commit_error') or 'Pricing import failed.')}</div>"
    body = f"""
<div class='callout success'><b>Nothing has been added yet.</b> Review the detected codes, descriptions, units, prices, and effective dates below. Floodman will use the market + category + selector + activity as the stable identity, so a later pricing worksheet updates matching items instead of duplicating them.</div>
<div class='grid metrics-grid'>
  <div class='card metric'><small>Line items ready</small><strong>{esc(counts.get('items_ready', 0))}</strong></div>
  <div class='card metric'><small>Categories</small><strong>{esc(counts.get('categories', 0))}</strong></div>
  <div class='card metric'><small>Markets</small><strong>{esc(counts.get('markets', 0))}</strong></div>
  <div class='card metric'><small>Need date review</small><strong>{esc(counts.get('needs_review', 0))}</strong></div>
</div>
<div class='card'><h2>Source pricing</h2><p><b>Price list:</b> {esc(', '.join(run.get('price_lists') or []))}</p><p><b>Market:</b> {esc(', '.join(run.get('markets') or []) or 'Not supplied')}</p><p><b>Effective date:</b> {esc(', '.join(run.get('effective_dates') or []) or 'Not supplied')}</p><p><b>Unit price range:</b> {money_cents(run.get('minimum_unit_price_cents'))} to {money_cents(run.get('maximum_unit_price_cents'))}</p></div>
<div class='card'><h2>Line-item preview</h2>{table(('Code','Description','Section','Unit','Unit price','Effective'), preview_rows, 'No valid line items were found.')}{'<p class="muted">Showing the first 100 line items. All validated items will be imported after confirmation.</p>' if len(items) > 100 else ''}</div>
<div class='card'><h2>Review warnings</h2><ul>{warnings}</ul></div>
<div class='card'><h2>Import action</h2><p>Only the normalized line-item values are written to the reusable Floodman catalog. This does not contact Xactimate, modify the original file, create an estimate, or send anything to a customer or insurer.</p><div class='actions'>{action}<a class='button secondary' href='/office/catalog'>Back to Services &amp; Prices</a></div></div>
"""
    return _page("Xactimate Pricing Review", body, "catalog")


@app.get("/office/imports/{run_id}")
def import_detail(run_id: str) -> HTMLResponse:
    run = store.get_import(run_id)
    if not run:
        raise HTTPException(404, "Import run not found")
    _require("estimates.manage" if run.get("import_kind") == XACTIMATE_IMPORT_KIND else "imports.manage")
    if run.get("import_kind") == "CUSTOMERS_CSV":
        return _customer_import_detail(run)
    if run.get("import_kind") == XACTIMATE_IMPORT_KIND:
        return _xactimate_import_detail(run)
    errors = "".join(f"<li>{esc(value)}</li>" for value in run.get("errors") or []) or "<li>None</li>"
    warnings = "".join(f"<li>{esc(value)}</li>" for value in run.get("warnings") or []) or "<li>None</li>"
    files = "".join(
        f"<li><a href='/office/imports/{esc(run_id)}/files/{quote(str(name), safe='/')}'>{esc(name)}</a></li>"
        for name in run.get("included_files") or []
    )
    counts = run.get("counts") or {}
    totals = run.get("totals") or {}
    count_cards = "".join(
        f"<div class='card metric'><small>{esc(key.replace('_',' ').title())}</small><strong>{esc(counts.get(key, 0))}</strong></div>"
        for key in ("contacts", "properties", "estimates", "estimate_lines", "invoices", "payments", "documents", "notes", "attachments")
    )
    commit = ""
    if run.get("status") == "PREVIEWED" and not run.get("errors"):
        commit = f"<form method='post' action='/office/imports/{esc(run_id)}/commit'><button class='good'>Commit to local archive</button></form>"
    elif run.get("status") == "COMMITTED":
        commit = f"<div class='callout'><b>Committed:</b> {esc(run.get('commit_result'))}</div>"
    body = f"""
<div class='grid'>{count_cards}</div>
<div class='card'><h2>Financial reconciliation</h2><div class='grid'><div><small>Estimate total</small><h3>{money_cents(totals.get('estimate_cents'))}</h3></div><div><small>Estimate-line total</small><h3>{money_cents(totals.get('estimate_line_cents'))}</h3></div><div><small>Invoice total</small><h3>{money_cents(totals.get('invoice_cents'))}</h3></div><div><small>Payment total</small><h3>{money_cents(totals.get('payment_cents'))}</h3></div><div><small>Outstanding</small><h3>{money_cents(totals.get('outstanding_cents'))}</h3></div><div><small>Overpaid amount</small><h3>{money_cents(totals.get('overpaid_cents'))}</h3></div></div></div>
<div class='grid'><div class='card'><h2>Errors</h2><ul>{errors}</ul></div><div class='card'><h2>Warnings</h2><ul>{warnings}</ul></div></div>
<div class='card'><h2>Included files</h2><ul>{files}</ul></div>
<div class='card'><h2>Import action</h2><p>Committing writes contacts, properties, estimates, estimate lines, invoices, payments, document references, and notes into the local archive. Imported balances remain historical and are not enrolled in A/R.</p><div class='actions'>{commit}<a class='button secondary' href='/office/imports'>Back to imports</a></div></div>
<div class='card'><details><summary>Validation record</summary>{json_pre(run)}</details></div>
"""
    return _page("Import Review", body, "imports")


@app.post("/office/imports/{run_id}/commit")
async def commit_import(run_id: str) -> RedirectResponse:
    run = store.get_import(run_id)
    if not run:
        raise HTTPException(404, "Import run not found")
    _require("estimates.manage" if run.get("import_kind") == XACTIMATE_IMPORT_KIND else "imports.manage")
    if run.get("errors"):
        store.set_notice("This import cannot be committed until its validation errors are fixed.")
        return RedirectResponse(f"/office/imports/{run_id}", status_code=303)
    if run.get("status") == "COMMITTED":
        store.set_notice("That import was already committed; no duplicates were created.")
        return RedirectResponse(f"/office/imports/{run_id}", status_code=303)
    store.update_import(run_id, status="IMPORTING")
    try:
        if run.get("import_kind") == "CUSTOMERS_CSV":
            actor = _require("imports.manage")
            result = await _commit_customer_csv(run_id, run, actor)
            store.update_import(
                run_id,
                status="COMMITTED",
                commit_result=result,
                imported_contact_ids=result["contact_ids"],
                sync_remaining=result["sync_remaining"],
            )
            store.set_notice(
                f"Customer import completed. {result['created']} created and {result['matched']} matched. "
                f"No messages or invoices were sent."
            )
        elif run.get("import_kind") == XACTIMATE_IMPORT_KIND:
            actor = _require("estimates.manage")
            normalized = store.read_normalized(run_id)
            raw_items = normalized.get("catalog_items")
            if not isinstance(raw_items, list):
                raise ValueError("The validated pricing preview no longer contains catalog items.")
            result = _import_xactimate_catalog_rows(raw_items, actor_id=str(actor.get("id") or ""))
            store.update_import(run_id, status="COMMITTED", commit_result=result)
            store.set_notice(
                f"Pricing import completed: {result['added']} added and {result['updated']} updated. "
                "No estimates or messages were created."
            )
        else:
            normalized = store.read_normalized(run_id)
            result = await providers.commit_import(normalized, run_id)
            archived = store.archive_import(run_id, normalized)
            result["office_archive"] = archived
            store.update_import(run_id, status="COMMITTED", commit_result=result)
            store.set_notice("Import committed to the local historical archive. Automatic reminders remain off.")
    except Exception as exc:
        store.update_import(run_id, status="FAILED", commit_error=str(exc))
        store.set_notice(f"Import commit failed: {exc}")
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.post("/office/imports/{run_id}/sync-customers")
async def sync_customer_import(run_id: str) -> RedirectResponse:
    actor = _require("connections.manage")
    run = store.get_import(run_id)
    if not run or run.get("import_kind") != "CUSTOMERS_CSV":
        raise HTTPException(404, "Customer import not found")
    if run.get("status") != "COMMITTED":
        raise HTTPException(409, "Commit the customer import before synchronizing it")
    if not settings.gauzy_sync_enabled:
        raise HTTPException(409, "Floodman ERP synchronization is currently locked")

    contact_ids = list(run.get("imported_contact_ids") or (run.get("commit_result") or {}).get("contact_ids") or [])
    pending = [contact_id for contact_id in contact_ids if not store.external_mapping("gauzy", f"contact:{contact_id}")]
    synced = 0
    errors: list[str] = []
    for contact_id in pending[:100]:
        contact = store.record("contacts", str(contact_id))
        if not contact:
            continue
        try:
            await _sync_contact_to_real_gauzy(contact, str(actor.get("id") or ""))
            for property_record in [item for item in store.records("properties") if str(item.get("contact_id") or "") == str(contact_id)]:
                try:
                    await _sync_property_to_real_gauzy(property_record, str(actor.get("id") or ""))
                except Exception as exc:
                    errors.append(f"{contact.get('name')}: property sync: {exc}")
            synced += 1
        except Exception as exc:
            errors.append(f"{contact.get('name') or contact_id}: {exc}")
    remaining = sum(1 for contact_id in contact_ids if not store.external_mapping("gauzy", f"contact:{contact_id}"))
    previous = run.get("sync_result") or {}
    store.update_import(
        run_id,
        sync_remaining=remaining,
        sync_result={
            "synced_total": int(previous.get("synced_total") or 0) + synced,
            "last_batch_synced": synced,
            "remaining": remaining,
            "errors": errors[-100:],
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    if errors:
        store.set_notice(f"Synced {synced} customers to Floodman ERP. {len(errors)} records need review; {remaining} remain.")
    else:
        store.set_notice(f"Synced {synced} customers to Floodman ERP. {remaining} remain.")
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.get("/office/imports/{run_id}/files/{filename:path}")
def import_file(run_id: str, filename: str) -> Response:
    run = store.get_import(run_id)
    if not run:
        raise HTTPException(404, "Import run not found")
    _require("estimates.manage" if run.get("import_kind") == XACTIMATE_IMPORT_KIND else "imports.manage")
    try:
        path = store.file_path(run_id, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not path.exists():
        raise HTTPException(404, "Imported file not found")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return Response(path.read_bytes(), media_type=media_type, headers={"Content-Disposition": f'inline; filename="{path.name}"'})


async def _state_page_data() -> dict[str, Any]:
    try:
        return _merge_archive_state(await providers.lab_state())
    except Exception as exc:
        return _merge_archive_state({"error": str(exc)})


def _operation_contacts() -> list[dict[str, Any]]:
    return store.records("contacts")


def _all_contact_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    # Provider records and Floodman-owned customer-file metadata frequently
    # share the same ID. Merge them instead of discarding tags, company,
    # notes, billing permissions, or imported fields from the local record.
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in _rows(state.get("gauzy_contacts")):
        identity = str(item.get("id") or "")
        if not identity:
            continue
        merged[identity] = dict(item)
        order.append(identity)
    for item in _operation_contacts():
        identity = str(item.get("id") or "")
        if not identity:
            continue
        if identity not in merged:
            merged[identity] = {}
            order.append(identity)
        merged[identity].update(dict(item))
    values: list[dict[str, Any]] = []
    for identity in order:
        item = merged[identity]
        item["name"] = item.get("name") or " ".join(
            filter(None, [item.get("first_name"), item.get("last_name")])
        )
        item["primaryEmail"] = item.get("email") or item.get("primaryEmail")
        item["primaryPhone"] = item.get("phone") or item.get("primaryPhone")
        values.append(item)
    return values


def _contact_name(contact_id: str, state: dict[str, Any] | None = None) -> str:
    if state:
        for item in _all_contact_rows(state):
            if str(item.get("id")) == str(contact_id):
                return str(item.get("name") or item.get("primaryEmail") or contact_id)
    item = store.record("contacts", contact_id)
    return str((item or {}).get("name") or (item or {}).get("email") or contact_id)


def _contact_options(state: dict[str, Any], selected: str = "") -> str:
    options = ["<option value=''>Select a customer</option>"]
    for item in _all_contact_rows(state):
        contact_id = str(item.get("id") or "")
        if not contact_id:
            continue
        label = item.get("name") or item.get("primaryEmail") or contact_id
        selected_attr = " selected" if contact_id == selected else ""
        options.append(f"<option value='{esc(contact_id)}'{selected_attr}>{esc(label)}</option>")
    return "".join(options)


def _property_options(selected: str = "") -> str:
    options = ["<option value=''>No property selected</option>"]
    for item in store.records("properties"):
        property_id = str(item.get("id") or "")
        label = item.get("name") or item.get("service_street") or property_id
        selected_attr = " selected" if property_id == selected else ""
        options.append(f"<option value='{esc(property_id)}'{selected_attr}>{esc(label)}</option>")
    return "".join(options)


def _contact_label(item: dict[str, Any]) -> str:
    return str(
        item.get("name")
        or " ".join(value for value in (item.get("first_name"), item.get("last_name")) if value)
        or item.get("company")
        or item.get("primaryEmail")
        or item.get("email")
        or item.get("id")
        or "Customer"
    ).strip()


def _contact_address(item: dict[str, Any]) -> str:
    return str(
        item.get("mailing_address_raw")
        or item.get("address")
        or ", ".join(
            value
            for value in (
                item.get("mailing_street"),
                item.get("mailing_city"),
                " ".join(value for value in (item.get("mailing_state"), item.get("mailing_postal_code")) if value),
            )
            if value
        )
    ).strip()


def _contact_search_text(item: dict[str, Any]) -> str:
    values = [
        _contact_label(item),
        item.get("company"),
        item.get("primaryEmail"),
        item.get("email"),
        item.get("email_raw"),
        item.get("primaryPhone"),
        item.get("phone"),
        _contact_address(item),
        item.get("lead_source"),
        item.get("assigned_staff"),
        " ".join(str(value) for value in item.get("tags") or []),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _all_property_rows(state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    values = list(store.records("properties"))
    if state:
        values.extend(_rows(state.get("properties")))
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in values:
        identity = str(item.get("id") or item.get("legacyPropertyId") or item.get("legacy_property_id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def _property_label(item: dict[str, Any]) -> str:
    name = str(item.get("property_name") or item.get("name") or "Property").strip()
    address = item.get("service_address") or {}
    street = str(address.get("street") or item.get("service_street") or "").strip()
    city = str(address.get("city") or item.get("service_city") or "").strip()
    suffix = ", ".join(value for value in (street, city) if value)
    return f"{name} — {suffix}" if suffix else name


def _entity_picker(
    *,
    kind: str,
    name: str,
    label: str,
    selected_id: str = "",
    selected_label: str = "",
    required: bool = False,
    contact_source: str = "",
) -> str:
    endpoint = "/office/api/search/contacts" if kind == "contacts" else "/office/api/search/properties"
    required_attr = " required" if required else ""
    contact_attr = f" data-contact-source='{esc(contact_source)}'" if contact_source else ""
    help_text = "Type at least two characters to search thousands of records."
    if kind == "properties":
        help_text = "Choose a customer first, then search by property name, street, city, or ZIP."
    return f"""<div class='field'><label>{esc(label)}</label><div class='fm-picker' data-fm-picker data-endpoint='{endpoint}' data-required={'true' if required else 'false'}{contact_attr}><input type='hidden' class='fm-picker-value' id='{esc(name)}' name='{esc(name)}' value='{esc(selected_id)}'><input type='search' class='fm-picker-input' value='{esc(selected_label)}' data-selected-label='{esc(selected_label)}' autocomplete='off' placeholder='Search {esc(label.lower())}…'{required_attr}><div class='fm-picker-results' hidden></div></div><div class='muted'>{help_text}</div></div>"""


def _ensure_local_contact(contact_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    existing = store.record("contacts", contact_id)
    if existing:
        return existing
    state = state or {}
    source = next((item for item in _all_contact_rows(state) if str(item.get("id") or "") == contact_id), None)
    if not source:
        raise HTTPException(404, "Customer not found")
    name = _contact_label(source)
    parts = name.split(None, 1)
    return store.create_record(
        "contacts",
        {
            "id": contact_id,
            "first_name": str(source.get("first_name") or (parts[0] if parts else "")),
            "last_name": str(source.get("last_name") or (parts[1] if len(parts) > 1 else "")),
            "name": name,
            "company": str(source.get("company") or ""),
            "email": str(source.get("primaryEmail") or source.get("email") or ""),
            "phone": str(source.get("primaryPhone") or source.get("phone") or ""),
            "lead_source": str(source.get("lead_source") or source.get("source") or "ERP"),
            "notes": str(source.get("notes") or ""),
            "tags": list(source.get("tags") or []),
            "status": str(source.get("status") or "ACTIVE"),
            "provider_id": contact_id,
            "source": "FLOODMAN_ERP_SHADOW",
        },
        actor_id=str((_user() or {}).get("id") or "floodman-office"),
    )


def _contact_notes(contact_id: str) -> list[dict[str, Any]]:
    return [
        item for item in store.records("notes")
        if str(item.get("entity_type") or "").upper() == "CONTACT"
        and str(item.get("entity_id") or "") == contact_id
    ]


def _square_amounts(invoice: dict[str, Any]) -> tuple[int, int, int]:
    total = 0
    completed = 0
    for request in invoice.get("payment_requests") or []:
        total += int((request.get("computed_amount_money") or request.get("fixed_amount_requested_money") or {}).get("amount") or 0)
        completed += int((request.get("total_completed_amount_money") or {}).get("amount") or 0)
    return total, completed, max(0, total - completed)


def _parse_money(value: str) -> int:
    raw = (value or "0").replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value}") from exc
    return int((amount * 100).quantize(Decimal("1")))


def _parse_line_items(value: str) -> tuple[list[dict[str, Any]], int]:
    _sections, items, total = normalize_document_payload({}, title="Scope of Work", legacy_text=value)
    return items, total

def _catalog_match(item: dict[str, Any]) -> dict[str, Any] | None:
    item_id = str(item.get("id") or "")
    external_key = str(item.get("external_key") or "")
    source_id = str(item.get("source_id") or "")
    for existing in store.records("catalog_items"):
        if item_id and str(existing.get("id") or "") == item_id:
            return existing
        if external_key and str(existing.get("external_key") or "") == external_key:
            return existing
        if source_id and str(existing.get("source_id") or "") == source_id and str(existing.get("source_provider") or "") == str(item.get("source_provider") or ""):
            return existing
    return None


def _upsert_catalog_item(payload: dict[str, Any], *, actor_id: str, source: str = "FLOODMAN_CUSTOM") -> tuple[dict[str, Any], bool]:
    normalized = normalize_catalog_item(payload, source=source)
    existing = _catalog_match(normalized)
    if existing:
        return store.update_record("catalog_items", str(existing["id"]), normalized, actor_id=actor_id), False
    return store.create_record("catalog_items", normalized, actor_id=actor_id), True


def _roomflow_catalog_seed_path() -> Path:
    return Path(os.getenv(
        "ROOMFLOW_CATALOG_PATH",
        "/home/container/data/roomflow/current/catalog/floodman-products.json",
    ))


def _import_catalog_rows(
    raw_items: list[Any],
    *,
    actor_id: str,
    source_provider: str,
    maximum: int = 10000,
) -> dict[str, Any]:
    imported = updated = skipped = 0
    errors: list[str] = []
    for index, raw in enumerate(raw_items[:maximum], start=1):
        if not isinstance(raw, dict) or raw.get("active") is False:
            skipped += 1
            continue
        try:
            _item, created = _upsert_catalog_item(
                {**raw, "source_provider": source_provider},
                actor_id=actor_id,
                source=source_provider,
            )
            if created:
                imported += 1
            else:
                updated += 1
        except Exception as exc:
            skipped += 1
            if len(errors) < 10:
                errors.append(f"Item {index}: {exc}")
    return {
        "added": imported,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "total_catalog_items": len(store.records("catalog_items")),
    }


def _import_xactimate_catalog_rows(raw_items: list[Any], *, actor_id: str) -> dict[str, Any]:
    if len(raw_items) > XACTIMATE_MAX_ROWS:
        raise ValueError(f"The validated pricing import exceeds the {XACTIMATE_MAX_ROWS:,}-item limit.")
    normalized: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            errors.append(f"Item {index}: expected a catalog object.")
            continue
        try:
            normalized.append(normalize_catalog_item(raw, source=XACTIMATE_SOURCE_PROVIDER))
        except Exception as exc:
            if len(errors) < 10:
                errors.append(f"Item {index}: {exc}")
    if errors:
        raise ValueError(" ".join(errors))
    result = store.bulk_upsert_records({"catalog_items": normalized}, actor_id=actor_id)["catalog_items"]
    return {
        "added": result["created"],
        "updated": result["updated"],
        "skipped": 0,
        "errors": [],
        "total_catalog_items": len(store.records("catalog_items")),
    }


def _import_bundled_roomflow_catalog(*, actor_id: str, force: bool = False) -> dict[str, Any]:
    seed_path = _roomflow_catalog_seed_path()
    existing_roomflow = [
        item for item in store.records("catalog_items")
        if str(item.get("source_provider") or "").startswith("ROOMFLOW")
    ]
    if existing_roomflow and not force:
        return {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "total_catalog_items": len(store.records("catalog_items")),
            "source_file": str(seed_path),
            "already_loaded": True,
        }
    if not seed_path.is_file():
        return {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [f"RoomFlow catalog file was not found at {seed_path}. Open RoomFlow once, then retry."],
            "total_catalog_items": len(store.records("catalog_items")),
            "source_file": str(seed_path),
            "already_loaded": False,
        }
    try:
        raw = json.loads(seed_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [f"RoomFlow catalog could not be read: {exc}"],
            "total_catalog_items": len(store.records("catalog_items")),
            "source_file": str(seed_path),
            "already_loaded": False,
        }
    if not isinstance(raw, list):
        return {
            "added": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["RoomFlow catalog file must contain a JSON array."],
            "total_catalog_items": len(store.records("catalog_items")),
            "source_file": str(seed_path),
            "already_loaded": False,
        }
    result = _import_catalog_rows(
        raw,
        actor_id=actor_id,
        source_provider="ROOMFLOW_BUNDLED_CATALOG",
    )
    result.update({"source_file": str(seed_path), "already_loaded": False})
    return result


def _save_custom_catalog_lines(lines: list[dict[str, Any]], actor_id: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for line in lines:
        record = dict(line)
        if record.get("catalog_item_id") and store.record("catalog_items", str(record["catalog_item_id"])):
            output.append(record)
            continue
        if record.get("save_to_catalog") or record.get("custom") or not record.get("catalog_item_id"):
            item, _created = _upsert_catalog_item({
                "name": record.get("name"),
                "description": record.get("description"),
                "category": record.get("category") or record.get("section_name"),
                "default_section": record.get("section_name"),
                "pricing_method": record.get("pricing_method") or "fixed",
                "unit": record.get("unit") or "each",
                "unit_price_cents": record.get("unit_price_cents") or 0,
                "taxable": bool(record.get("taxable")),
                "active": True,
            }, actor_id=actor_id, source="FLOODMAN_CUSTOM")
            record["catalog_item_id"] = item["id"]
            record["save_to_catalog"] = False
        output.append(record)
    return output


def _estimate_builder_html(document: dict[str, Any] | None = None, *, default_section: str = "Scope of Work") -> str:
    source = document or {"title": default_section, "sections": [], "line_items": []}
    payload = document_payload(source)
    if not payload.get("sections"):
        payload = default_document(default_section)
    return f"""<div class='fm-estimate-builder' data-fm-estimate-builder data-default-section='{esc(default_section)}'>
      <textarea class='fm-estimate-payload' name='estimate_payload' hidden>{esc(json.dumps(payload, separators=(',', ':'), default=str))}</textarea>
      <div class='fm-estimate-toolbar'><div><b>Grouped scope builder</b><div class='fm-estimate-summary'></div></div><div class='actions'><button type='button' class='secondary' data-add-estimate-section>Add header</button><a class='button secondary' href='/office/catalog' target='_blank'>Line item catalog</a></div></div>
      <div class='fm-estimate-sections'></div>
    </div>"""


def _render_grouped_document_lines(document: dict[str, Any]) -> str:
    groups = group_document_lines(document)
    sections: list[str] = []
    for group in groups:
        rows: list[list[str]] = []
        for item in group.get("lines") or []:
            unit = item.get("unit_price_cents")
            total = item.get("line_total_cents")
            if unit is None:
                unit = int(round(float(item.get("price") or 0) * 100))
            if total is None:
                total = int(round(float(item.get("totalValue") or 0) * 100))
            labels = []
            if item.get("optional"):
                labels.append("Optional")
            if item.get("taxable"):
                labels.append("Taxable")
            description = esc(item.get("description") or "")
            detail = f"<small class='muted'>{description}</small>" if description else ""
            pricing_reference = esc(item.get("pricing_reference") or "")
            pricing_detail = f"<small class='muted'><b>Pricing code:</b> {pricing_reference}</small>" if pricing_reference else ""
            flags = f"<div>{' · '.join(labels)}</div>" if labels else ""
            rows.append([
                f"<b>{esc(item.get('name') or item.get('description'))}</b>{pricing_detail}{detail}{flags}",
                esc(item.get("quantity")),
                esc(item.get("unit") or "each"),
                money_cents(unit),
                money_cents(total),
            ])
        sections.append(
            f"<section class='fm-document-section'><header><div><h3>{esc(group.get('name') or 'Scope')}</h3>"
            f"<small>{esc(group.get('description') or '')}</small></div><b>{money_cents(group.get('subtotal_cents'))}</b></header>"
            f"{table(('Item','Quantity','Unit','Unit price','Line total'), rows, empty='No line items in this header.')}</section>"
        )
    return "".join(sections)


def _provider_items_with_headers(sections: list[dict[str, Any]], lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for group in group_document_lines({"sections": sections, "line_items": lines}):
        output.append({
            "description": f"— {group.get('name') or 'Scope'} —",
            "quantity": 1,
            "price": 0,
            "totalValue": 0,
            "applyTax": False,
            "applyDiscount": False,
        })
        for item in group.get("lines") or []:
            output.append({
                "description": item.get("name") or item.get("description") or "Line item",
                "quantity": item.get("quantity") or 1,
                "price": int(item.get("unit_price_cents") or 0) / 100,
                "totalValue": int(item.get("line_total_cents") or 0) / 100,
                "applyTax": bool(item.get("taxable")),
                "applyDiscount": False,
            })
    return output


def _next_number(prefix: str, kind: str) -> str:
    year = datetime.now(UTC).year
    count = len(store.records(kind)) + 1
    return f"{prefix}-{year}-{count:04d}"


def _duration(value: int | None) -> str:
    seconds = max(0, int(value or 0))
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


async def _sync_contact_to_real_gauzy(record: dict[str, Any], actor_id: str) -> str | None:
    """Create one native Floodman ERP contact and persist the stable mapping."""
    if not settings.gauzy_sync_enabled:
        return None
    record_id = str(record.get("id") or "")
    key = f"contact:{record_id}"
    existing = store.external_mapping("gauzy", key)
    if existing:
        return existing
    context = await providers.gauzy_context()
    created = await providers.full_gauzy_create_contact(record, context)
    external = str(created.get("id") or "")
    if not external:
        raise RuntimeError("Floodman ERP did not return a contact ID")
    store.set_external_mapping("gauzy", key, external)
    if store.record("contacts", record_id):
        store.update_record("contacts", record_id, {"full_gauzy_id": external}, actor_id=actor_id)
    return external


async def _sync_property_to_real_gauzy(record: dict[str, Any], actor_id: str) -> str | None:
    """Represent a Floodman service property/job as a native Floodman project."""
    if not settings.gauzy_sync_enabled:
        return None
    record_id = str(record.get("id") or "")
    key = f"property:{record_id}"
    existing = store.external_mapping("gauzy", key)
    if existing:
        return existing
    contact_id = str(record.get("contact_id") or "")
    external_contact = store.external_mapping("gauzy", f"contact:{contact_id}")
    if not external_contact:
        contact = store.record("contacts", contact_id)
        if not contact:
            raise RuntimeError("The related contact must be synchronized before the property")
        external_contact = await _sync_contact_to_real_gauzy(contact, actor_id)
    if not external_contact:
        raise RuntimeError("Floodman ERP contact mapping is missing")
    context = await providers.gauzy_context()
    created = await providers.full_gauzy_create_project(record, context, contact_id=external_contact)
    external = str(created.get("id") or "")
    if not external:
        raise RuntimeError("Floodman ERP did not return a project ID")
    store.set_external_mapping("gauzy", key, external)
    if store.record("properties", record_id):
        store.update_record("properties", record_id, {"full_gauzy_id": external}, actor_id=actor_id)
    return external


async def _sync_financial_to_real_gauzy(
    kind: str,
    record: dict[str, Any],
    actor_id: str,
    *,
    is_estimate: bool,
) -> str | None:
    if not settings.gauzy_sync_enabled:
        return None
    record_id = str(record.get("id") or "")
    key = f"{kind}:{record_id}"
    existing = store.external_mapping("gauzy", key)
    if existing:
        return existing
    contact_id = str(record.get("contact_id") or "")
    external_contact = store.external_mapping("gauzy", f"contact:{contact_id}")
    if not external_contact:
        contact = store.record("contacts", contact_id)
        if not contact:
            raise RuntimeError("The related contact must be synchronized before the financial record")
        external_contact = await _sync_contact_to_real_gauzy(contact, actor_id)
    project_id = None
    property_id = str(record.get("property_id") or "")
    if property_id:
        project_id = store.external_mapping("gauzy", f"property:{property_id}")
        if not project_id:
            property_record = store.record("properties", property_id)
            if property_record:
                project_id = await _sync_property_to_real_gauzy(property_record, actor_id)
    context = await providers.gauzy_context()
    created = await providers.full_gauzy_create_invoice(
        record,
        context,
        contact_id=str(external_contact),
        is_estimate=is_estimate,
        project_id=project_id,
    )
    external = str(created.get("id") or "")
    if not external:
        raise RuntimeError("Floodman ERP did not return a financial record ID")
    store.set_external_mapping("gauzy", key, external)
    if store.record(kind + "s", record_id):
        store.update_record(
            kind + "s",
            record_id,
            {"full_gauzy_id": external, "full_gauzy_project_id": project_id},
            actor_id=actor_id,
        )
    return external


@app.get("/office/api/search/contacts")
async def contact_search_api(q: str = "", workspace_id: str = "", limit: int = 25) -> dict[str, Any]:
    user = _require("contacts.view")
    state = await _state_page_data()
    query = str(q or "").strip().lower()
    values = _all_contact_rows(state)
    if workspace_id:
        workspaces, _, _ = _browser_roomflow_workspace_context(user)
        if not any(str(record.get("id") or "") == workspace_id for record in workspaces):
            raise HTTPException(status_code=422, detail="Select a valid Floodman RoomFlow company workspace.")
        values = [item for item in values if str(item.get("workspace_id") or "") in {"", workspace_id}]
    if query:
        values = [item for item in values if query in _contact_search_text(item)]
    values.sort(key=lambda item: _contact_label(item).lower())
    items = []
    for item in values[: max(1, min(50, int(limit or 25)))]:
        contact_id = str(item.get("id") or "")
        if not contact_id:
            continue
        meta = " · ".join(value for value in (
            str(item.get("primaryEmail") or item.get("email") or "").strip(),
            str(item.get("primaryPhone") or item.get("phone") or "").strip(),
            _contact_address(item),
        ) if value)
        items.append({"id": contact_id, "label": _contact_label(item), "secondary": meta, "meta": meta, "raw": item})
    return {"items": items}


@app.get("/office/api/search/properties")
async def property_search_api(q: str = "", contact_id: str = "", workspace_id: str = "", limit: int = 25) -> dict[str, Any]:
    user = _require("properties.view")
    state = await _state_page_data()
    query = str(q or "").strip().lower()
    values = _all_property_rows(state)
    if workspace_id:
        workspaces, _, _ = _browser_roomflow_workspace_context(user)
        if not any(str(record.get("id") or "") == workspace_id for record in workspaces):
            raise HTTPException(status_code=422, detail="Select a valid Floodman RoomFlow company workspace.")
        values = [item for item in values if str(item.get("workspace_id") or "") in {"", workspace_id}]
    if contact_id:
        values = [item for item in values if str(item.get("contact_id") or "") == contact_id]
    if query:
        values = [item for item in values if query in " ".join(str(value or "") for value in (
            item.get("property_name"), item.get("name"), item.get("service_street"), item.get("service_city"),
            item.get("service_state"), item.get("service_postal_code"), item.get("property_type"),
        )).lower()]
    values.sort(key=lambda item: _property_label(item).lower())
    items = []
    for item in values[: max(1, min(50, int(limit or 25)))]:
        property_id = str(item.get("id") or "")
        if not property_id:
            continue
        meta = " · ".join(value for value in (
            _contact_name(str(item.get("contact_id") or ""), state),
            str(item.get("property_type") or ""),
            str(item.get("service_postal_code") or ""),
        ) if value)
        items.append({"id": property_id, "label": _property_label(item), "secondary": meta, "meta": meta, "raw": item})
    return {"items": items}


async def _publish_invoice_to_square(
    invoice: dict[str, Any],
    actor_id: str,
    *,
    collection_mode: str | None = None,
    allow_customer_to_save_card: bool | None = None,
) -> tuple[dict[str, Any], str]:
    contact_id = str(invoice.get("contact_id") or "")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    square_customer = await providers.ensure_square_customer(contact)
    square_customer_id = str(square_customer.get("id") or "")
    if square_customer_id and contact.get("square_customer_id") != square_customer_id:
        contact = store.update_record("contacts", contact_id, {"square_customer_id": square_customer_id}, actor_id=actor_id)

    requested = str(collection_mode or invoice.get("collection_mode") or "AUTO_IF_AUTHORIZED").upper()
    allow_save = bool(invoice.get("allow_customer_to_save_card", True) if allow_customer_to_save_card is None else allow_customer_to_save_card)
    cards = await providers.list_square_cards(square_customer_id) if square_customer_id else []
    valid_ids = {str(item.get("id") or "") for item in cards if item.get("id")}
    default_card = str(contact.get("default_square_card_id") or "")
    if default_card not in valid_ids:
        default_card = ""
    authorized = bool(contact.get("auto_charge_enabled") and contact.get("auto_charge_authorized_at") and default_card)
    card_id: str | None = None
    if requested == "AUTO_CHARGE":
        if not authorized:
            raise RuntimeError("Automatic charging is not authorized for this customer or the default saved card is unavailable.")
        card_id = default_card
    elif requested == "AUTO_IF_AUTHORIZED" and authorized:
        card_id = default_card

    result = await providers.create_and_publish_square_invoice(
        invoice,
        contact,
        card_id=card_id,
        allow_customer_to_save_card=allow_save,
    )
    square_invoice = dict(result.get("invoice") or {})
    total, paid, balance = _square_amounts(square_invoice)
    previous_paid = int(invoice.get("paid_cents") or 0)
    status = str(square_invoice.get("status") or "UNPAID").upper()
    local_status = "PAID" if status == "PAID" else "PARTIALLY_PAID" if paid > 0 else "SENT"
    updates = {
        "status": local_status,
        "issued_at": invoice.get("issued_at") or datetime.now(UTC).isoformat(),
        "due_at": invoice.get("due_at") or datetime.now(UTC).isoformat(),
        "send_channel": "SQUARE",
        "collection_mode": "AUTO_CHARGE" if card_id else "PAYMENT_LINK",
        "allow_customer_to_save_card": bool(allow_save and not card_id),
        "square_customer_id": square_customer_id,
        "square_order_id": str((result.get("order") or {}).get("id") or ""),
        "square_invoice_id": str(square_invoice.get("id") or ""),
        "square_invoice_version": int(square_invoice.get("version") or 0),
        "square_public_url": str(square_invoice.get("public_url") or ""),
        "square_automatic_card_id": card_id,
        "paid_cents": paid,
        "balance_cents": balance if total else int(invoice.get("balance_cents") or 0),
    }
    updated = store.update_record("invoices", str(invoice["id"]), updates, actor_id=actor_id)
    if paid > previous_paid:
        payment_key = f"floodman-square-invoice-payment:{updates['square_invoice_id']}:{paid}"
        payment, _ = store.create_record_if_absent("payments", str(uuid.uuid5(uuid.NAMESPACE_URL, payment_key)), {
            "invoice_id": str(invoice["id"]),
            "contact_id": contact_id,
            "amount_cents": paid - previous_paid,
            "currency": str(invoice.get("currency") or "USD"),
            "method": "SQUARE_CARD_ON_FILE" if card_id else "SQUARE",
            "reference": updates["square_invoice_id"],
            "note": "Recorded automatically from the payment processor status.",
            "payment_date": datetime.now(UTC).isoformat(),
            "status": "COMPLETED",
        }, actor_id="square-reconciliation")
        await _notify_payment_admins("invoice", updated, payment)
    message = "Floodman automatically charged the authorized card on file." if card_id else "Floodman published the secure invoice payment page and offered the customer an optional save-payment-method checkbox."
    return updated, message


async def _reconcile_square_invoices_once() -> int:
    changed = 0
    for invoice in store.records("invoices"):
        square_invoice_id = str(invoice.get("square_invoice_id") or "")
        if not square_invoice_id or str(invoice.get("status") or "").upper() in {"PAID", "VOID", "CANCELED"}:
            continue
        try:
            square_invoice = await providers.get_square_invoice(square_invoice_id)
            total, paid, balance = _square_amounts(square_invoice)
            previous_paid = int(invoice.get("paid_cents") or 0)
            square_status = str(square_invoice.get("status") or "").upper()
            local_status = "PAID" if square_status == "PAID" else "PARTIALLY_PAID" if paid else str(invoice.get("status") or "SENT")
            if paid != int(invoice.get("paid_cents") or 0) or balance != int(invoice.get("balance_cents") or 0) or local_status != str(invoice.get("status") or ""):
                store.update_record("invoices", str(invoice["id"]), {
                    "status": local_status,
                    "paid_cents": paid,
                    "balance_cents": balance if total else int(invoice.get("balance_cents") or 0),
                    "square_invoice_version": int(square_invoice.get("version") or 0),
                    "square_public_url": str(square_invoice.get("public_url") or invoice.get("square_public_url") or ""),
                }, actor_id="square-reconciliation")
                changed += 1
                if paid > previous_paid:
                    payment_key = f"floodman-square-invoice-payment:{square_invoice_id}:{paid}"
                    payment, _ = store.create_record_if_absent(
                        "payments",
                        str(uuid.uuid5(uuid.NAMESPACE_URL, payment_key)),
                        {
                            "invoice_id": str(invoice["id"]),
                            "contact_id": invoice.get("contact_id"),
                            "amount_cents": paid - previous_paid,
                            "currency": str(invoice.get("currency") or "USD"),
                            "method": "SQUARE",
                            "reference": square_invoice_id,
                            "note": "Reconciled from the payment processor.",
                            "payment_date": datetime.now(UTC).isoformat(),
                            "status": "COMPLETED",
                        },
                        actor_id="square-reconciliation",
                    )
                    await _notify_payment_admins(
                        "invoice",
                        store.record("invoices", str(invoice["id"])) or invoice,
                        payment,
                    )
                if local_status == "PAID":
                    # If the buyer chose Square's "Save my card on file" option,
                    # discover the new tokenized card and make it the customer's
                    # default only when no default has been chosen yet. Floodman
                    # never receives or stores a full card number or CVV.
                    contact_id = str(invoice.get("contact_id") or "")
                    contact = store.record("contacts", contact_id) if contact_id else None
                    if contact and not contact.get("default_square_card_id"):
                        customer_id = str(contact.get("square_customer_id") or invoice.get("square_customer_id") or "")
                        if customer_id:
                            cards = await providers.list_square_cards(customer_id)
                            card_ids = sorted(str(card.get("id") or "") for card in cards if card.get("id"))
                            if card_ids:
                                selected = next((card for card in cards if str(card.get("id") or "") == card_ids[0]), {})
                                store.update_record("contacts", contact_id, {
                                    "square_customer_id": customer_id,
                                    "default_square_card_id": card_ids[0],
                                    "square_cards_refreshed_at": datetime.now(UTC).isoformat(),
                                }, actor_id="square-reconciliation")
                                store.create_record("notes", {
                                    "entity_type": "CONTACT",
                                    "entity_id": contact_id,
                                    "note_type": "BILLING",
                                    "body": f"Customer saved a Card ending in {selected.get('last_4') or '****'} during invoice payment. It was selected as the default tokenized payment method; automatic charging remains disabled until authorization is recorded.",
                                    "pinned": False,
                                    "created_by_name": "Floodman payment reconciliation",
                                }, actor_id="square-reconciliation")
        except Exception:
            continue
    return changed


async def _square_reconciliation_loop() -> None:
    while True:
        try:
            await _reconcile_square_invoices_once()
        except Exception:
            pass
        await asyncio.sleep(60)


_square_reconciliation_task: asyncio.Task[Any] | None = None


@app.on_event("startup")
async def start_square_reconciliation() -> None:
    global _square_reconciliation_task
    _square_reconciliation_task = asyncio.create_task(_square_reconciliation_loop())


@app.on_event("shutdown")
async def stop_square_reconciliation() -> None:
    global _square_reconciliation_task
    if _square_reconciliation_task:
        _square_reconciliation_task.cancel()
        try:
            await _square_reconciliation_task
        except (asyncio.CancelledError, Exception):
            pass
        _square_reconciliation_task = None


@app.get("/office/contacts")
async def contacts_page(q: str = "", status: str = "", page: int = 1) -> HTMLResponse:
    _require("contacts.view")
    state = await _state_page_data()
    contacts = _all_contact_rows(state)
    query = str(q or "").strip().lower()
    if query:
        contacts = [item for item in contacts if query in _contact_search_text(item)]
    if status:
        contacts = [item for item in contacts if str(item.get("status") or "ACTIVE").upper() == status.upper()]
    contacts.sort(key=lambda item: _contact_label(item).lower())
    page_size = 50
    total = len(contacts)
    pages = max(1, (total + page_size - 1) // page_size)
    current = max(1, min(int(page or 1), pages))
    start = (current - 1) * page_size
    visible = contacts[start:start + page_size]
    property_counts: dict[str, int] = defaultdict(int)
    for item in _all_property_rows(state):
        property_counts[str(item.get("contact_id") or "")] += 1
    rows = []
    for item in visible:
        contact_id = str(item.get("id") or "")
        rows.append([
            f"<div class='customer-name'><a href='/office/contacts/{esc(contact_id)}'><b>{esc(_contact_label(item))}</b></a><small>{esc(item.get('company') or '')}</small></div>",
            f"{esc(item.get('primaryEmail') or item.get('email') or '')}<br><span class='muted'>{esc(item.get('primaryPhone') or item.get('phone') or '')}</span>",
            str(property_counts.get(contact_id, 0)),
            f"<a class='button secondary small' href='/office/contacts/{esc(contact_id)}'>Open</a>",
        ])
    query_value = quote(q)
    status_value = quote(status)
    previous = f"<a class='button secondary small' href='/office/contacts?q={query_value}&status={status_value}&page={current-1}'>Previous</a>" if current > 1 else ""
    following = f"<a class='button secondary small' href='/office/contacts?q={query_value}&status={status_value}&page={current+1}'>Next</a>" if current < pages else ""
    search_form = f"""<div class='card'><form method='get' action='/office/contacts' class='customer-searchbar'><div class='field'><label>Search customers</label><input type='search' name='q' value='{esc(q)}' placeholder='Name, company, email, phone, address, or tag'></div><div class='field'><label>Status</label><select name='status'><option value=''>All statuses</option>{''.join(f"<option value='{value}'{' selected' if status.upper()==value else ''}>{value.title()}</option>" for value in ('ACTIVE','POTENTIAL CUSTOMER','EXISTING CUSTOMER','LAPSED','CLOSED'))}</select></div><button>Search</button></form><p class='muted'>{total:,} matching customer files · page {current} of {pages}</p></div>"""
    create = ""
    if has_permission(_user(), "contacts.manage"):
        create = """<details class='card'><summary>Add customer</summary><form method='post' action='/office/contacts/add' style='margin-top:15px'><div class='form-grid three'>
        <div class='field'><label>First name</label><input name='first_name' required></div><div class='field'><label>Last name</label><input name='last_name' required></div>
        <div class='field'><label>Company</label><input name='company'></div><div class='field'><label>Email</label><input type='email' name='email'></div>
        <div class='field'><label>Phone</label><input name='phone'></div><div class='field'><label>Lead source</label><input name='lead_source' placeholder='Website, referral, repeat customer'></div>
        <div class='field full'><label>Initial note</label><textarea name='notes'></textarea></div></div><button style='margin-top:12px'>Create customer file</button></form></details>"""
    body = f"{search_form}{create}<div class='card'><h2>Customers</h2>{table(('Customer','Contact','Properties','Open'), rows, 'No customers match this search.') }<div class='pagination'>{previous}<span>Page {current} of {pages}</span>{following}</div></div>"
    return _page("Customer Files", body, "contacts")


@app.post("/office/contacts/add")
async def add_contact(
    first_name: str = Form(...),
    last_name: str = Form(...),
    company: str = Form(default=""),
    email: str = Form(default=""),
    phone: str = Form(default=""),
    lead_source: str = Form(default=""),
    notes: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("contacts.manage")
    name = " ".join(filter(None, [first_name.strip(), last_name.strip()]))
    payload = {
        "name": name,
        "primaryEmail": email.strip() or None,
        "primaryPhone": phone.strip() or None,
        "notes": notes.strip(),
        "contactType": "CLIENT",
    }
    provider_id = None
    try:
        created = await providers.create_contact(payload)
        provider_id = created.get("id")
    except Exception as exc:
        store.set_notice(f"Contact saved locally; Floodman ERP bridge warning: {exc}")
    record = store.create_record("contacts", {
        "id": provider_id or str(uuid.uuid4()),
        "first_name": first_name.strip(),
        "last_name": last_name.strip(),
        "name": name,
        "company": company.strip(),
        "email": email.strip(),
        "phone": phone.strip(),
        "lead_source": lead_source.strip(),
        "notes": notes.strip(),
        "provider_id": provider_id,
        "status": "ACTIVE",
    }, actor_id=actor.get("id"))
    notice = f"Contact {record['name']} created."
    try:
        external = await _sync_contact_to_real_gauzy(record, str(actor.get("id")))
        if external:
            notice += " Synced to Floodman ERP."
    except Exception as exc:
        notice += f" Floodman ERP sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/contacts/{record['id']}", status_code=303)


@app.get("/office/contacts/{contact_id}")
async def contact_detail(contact_id: str) -> HTMLResponse:
    _require("contacts.view")
    state = await _state_page_data()
    contact = next((item for item in _all_contact_rows(state) if str(item.get("id") or "") == contact_id), None)
    if not contact:
        raise HTTPException(404, "Customer not found")
    local_contact = store.record("contacts", contact_id)
    properties = [item for item in _all_property_rows(state) if str(item.get("contact_id") or "") == contact_id]
    provider_financials = _rows(state.get("gauzy_invoices"))
    estimates = [item for item in store.records("estimates") + provider_financials if (item.get("isEstimate") is True or item.get("estimate_number")) and str(item.get("contact_id") or item.get("organizationContactId") or "") == contact_id]
    invoices = [item for item in store.records("invoices") + provider_financials if item.get("isEstimate") is not True and str(item.get("contact_id") or item.get("organizationContactId") or "") == contact_id]
    client_files = [item for item in store.records("documents") if str(item.get("contact_id") or "") == contact_id]
    notes = _contact_notes(contact_id)

    def unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set(); result: list[dict[str, Any]] = []
        for item in rows:
            identity = str(item.get("id") or "")
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            result.append(item)
        return result

    properties, estimates, invoices, client_files = map(unique, (properties, estimates, invoices, client_files))
    mailing_address = _contact_address(contact)
    tags = list((local_contact or contact).get("tags") or [])
    manage = f"<a class='button secondary' href='/office/contacts/{esc(contact_id)}/edit'>Edit customer</a>" if local_contact and has_permission(_user(), "contacts.manage") else ""

    square_cards: list[dict[str, Any]] = []
    square_error = ""
    square_customer_id = str((local_contact or contact).get("square_customer_id") or "")
    if square_customer_id:
        try:
            square_cards = await providers.list_square_cards(square_customer_id)
        except Exception as exc:
            square_error = str(exc)
    default_card = str((local_contact or contact).get("default_square_card_id") or "")
    auto_enabled = bool((local_contact or contact).get("auto_charge_enabled"))
    card_rows = []
    for card in square_cards:
        card_id = str(card.get("id") or "")
        expiry = f"{int(card.get('exp_month') or 0):02d}/{int(card.get('exp_year') or 0)}" if card.get("exp_month") else ""
        actions = []
        if has_permission(_user(), "contacts.manage"):
            if card_id != default_card:
                actions.append(f"<form method='post' action='/office/contacts/{esc(contact_id)}/cards/{esc(card_id)}/default'><button class='secondary small'>Make default</button></form>")
            actions.append(f"<form method='post' action='/office/contacts/{esc(contact_id)}/cards/{esc(card_id)}/disable'><button class='danger small'>Remove</button></form>")
        card_rows.append([
            f"<strong>{esc(card.get('card_brand') or 'CARD')} •••• {esc(card.get('last_4') or '')}</strong>",
            esc(expiry),
            badge("Default", "good") if card_id == default_card else badge("Available"),
            "<div class='actions'>" + "".join(actions) + "</div>",
        ])

    tags_html = "".join(f"<span class='tag-chip'>{esc(tag)}</span>" for tag in tags) or "<span class='muted'>No tags</span>"
    tag_editor = ""
    if has_permission(_user(), "contacts.manage"):
        tag_editor = f"""<form method='post' action='/office/contacts/{esc(contact_id)}/tags'><div class='field'><label>Customer tags</label><input name='tags' value='{esc(', '.join(tags))}' placeholder='VIP, insurance, repeat customer, commercial'></div><button class='secondary' style='margin-top:10px'>Save tags</button></form>"""
    tag_controls = f"<details class='plain-details'><summary>Edit customer tags</summary><div style='margin-top:12px'>{tag_editor}</div></details>" if tag_editor else ""

    note_items = ""
    for note in notes:
        note_items += f"""<div class='timeline-item'><div class='timeline-head'><div>{badge(note.get('note_type') or 'NOTE')} {'<span class=\'tag-chip\'>Pinned</span>' if note.get('pinned') else ''}</div><span class='muted'>{esc(note.get('created_at') or '')}</span></div><p>{esc(note.get('body') or note.get('note') or '')}</p>{f"<form method='post' action='/office/contacts/{esc(contact_id)}/notes/{esc(note.get('id'))}/delete'><button class='danger small'>Delete note</button></form>" if has_permission(_user(), 'notes.manage') else ''}</div>"""
    if not note_items:
        note_items = "<p class='muted'>No activity notes have been added yet.</p>"
    note_form = ""
    if has_permission(_user(), "notes.manage"):
        note_form = f"""<form method='post' action='/office/contacts/{esc(contact_id)}/notes'><div class='form-grid'><div class='field'><label>Note type</label><select name='note_type'><option>GENERAL</option><option>CALL</option><option>EMAIL</option><option>SITE_VISIT</option><option>BILLING</option><option>INSURANCE</option><option>FOLLOW_UP</option></select></div><div class='field checks'><label><input type='checkbox' name='pinned' value='yes'> Pin this note</label></div><div class='field full'><label>Customer-file note</label><textarea name='body' required></textarea></div></div><button style='margin-top:10px'>Add note</button></form>"""

    payment_controls = ""
    if has_permission(_user(), "contacts.manage"):
        refresh_text = "Refresh saved payment methods" if square_customer_id else "Create/link payment profile"
        payment_controls += f"<form method='post' action='/office/contacts/{esc(contact_id)}/cards/refresh'><button>{refresh_text}</button></form>"
    payment_authorizations = [
        item for item in client_files
        if str(item.get("document_type") or "").upper() == "PAYMENT_AUTHORIZATION"
        and str(item.get("status") or "").upper() in {"COMPLETED", "SIGNED", "EXECUTED"}
    ]
    payment_authorizations.sort(key=lambda item: str(item.get("completed_at") or item.get("updated_at") or ""), reverse=True)
    latest_authorization = payment_authorizations[0] if payment_authorizations else None
    suggested_authorization_reference = ""
    if latest_authorization:
        suggested_authorization_reference = str(
            latest_authorization.get("envelope_id")
            or latest_authorization.get("id")
            or latest_authorization.get("signed_pdf_sha256")
            or ""
        )

    auto_form = ""
    if has_permission(_user(), "contacts.manage"):
        if auto_enabled:
            auto_form = f"""<div class='callout success'><b>Automatic invoice charging is authorized.</b><br>Authorization: {esc((local_contact or contact).get('auto_charge_authorization_reference') or '')}<form method='post' action='/office/contacts/{esc(contact_id)}/auto-charge' style='margin-top:10px'><input type='hidden' name='enabled' value='no'><button class='danger'>Disable automatic charging</button></form></div>"""
        else:
            authorization_hint = (
                "A completed Payment Authorization is attached to this client file. Confirm it below before enabling automatic charges."
                if latest_authorization
                else "No completed Payment Authorization was found. Send one from Documents & Signing, or enter another written authorization reference."
            )
            auto_form = f"""<div class='callout {'success' if latest_authorization else 'warning'}'>{esc(authorization_hint)}</div><form method='post' action='/office/contacts/{esc(contact_id)}/auto-charge'><input type='hidden' name='enabled' value='yes'><div class='form-grid'><div class='field full'><label>Authorization reference</label><input name='authorization_reference' value='{esc(suggested_authorization_reference)}' placeholder='Signed Payment Authorization envelope ID or written authorization record' required></div><div class='field full checks'><label><input type='checkbox' name='authorization_confirm' value='yes' required> I confirm this customer explicitly authorized Floodman to charge the selected saved card for future invoices when sent.</label></div></div><div class='actions' style='margin-top:10px'><button class='good'>Enable automatic invoice charging</button><a class='button secondary' href='/office/documents?contact_id={quote(contact_id)}'>Send Payment Authorization</a></div></form>"""

    payment_section = f"""<details class='card'><summary>Billing and payment methods</summary><div style='margin-top:15px'><div class='pci-box'><b>Secure payment storage:</b> Floodman never stores a full card number or security code. The certified payment processor stores the credential; Floodman keeps only a token, card brand, last four digits, and expiration for display and authorized charging.</div><div class='actions' style='margin-top:12px'>{payment_controls}</div>{f"<div class='callout warning'>{esc(square_error)}</div>" if square_error else ''}<div style='margin-top:12px'>{table(('Card','Expires','Use','Actions'), card_rows, 'No saved card is on file. Send a Floodman invoice with “Let the customer save the payment method” enabled, or take an authorized card payment by phone.')}</div><hr><h3>Automatic invoice charging</h3>{auto_form}</div></details>"""

    imported_detail = ""
    if str(contact.get("source") or "").upper() == "CUSTOMER_CSV":
        quality = ", ".join(contact.get("quality_flags") or []) or "No review flags"
        imported_detail = f"""<details class='card'><summary>Imported source details</summary><div class='grid'><div><small class='muted'>Assigned staff</small><p>{esc(contact.get('assigned_staff') or '')}</p></div><div><small class='muted'>Source</small><p>{esc(contact.get('lead_source') or '')}</p></div><div><small class='muted'>Review flags</small><p>{esc(quality)}</p></div><div><small class='muted'>Communication suppression</small><p>{badge('Blocked / unsubscribed', 'bad') if contact.get('email_blocked') or contact.get('unsubscribed') else badge('Allowed', 'good')}</p></div></div><details><summary>Original import rows</summary>{json_pre(contact.get('source_records') or [])}</details></details>"""

    body = f"""<div class='actions'><a class='button secondary' href='/office/contacts'>Back to customers</a><a class='button' href='/office/properties?contact_id={quote(contact_id)}'>Properties</a><a class='button' href='/office/estimates/new?contact_id={quote(contact_id)}'>New estimate</a><a class='button' href='/office/invoices?contact_id={quote(contact_id)}'>New invoice</a>{manage}</div>
    <div class='card' style='margin-top:15px'><h2>{esc(_contact_label(contact))}</h2><div class='grid'><div><small class='muted'>Email</small><p>{esc(contact.get('primaryEmail') or contact.get('email') or contact.get('email_raw') or '')}</p></div><div><small class='muted'>Phone</small><p>{esc(contact.get('primaryPhone') or contact.get('phone') or '')}</p></div><div><small class='muted'>Company</small><p>{esc(contact.get('company') or '')}</p></div><div><small class='muted'>Mailing address</small><p>{esc(mailing_address)}</p></div></div><div class='tag-list'>{tags_html}</div>{tag_controls}</div>
    <div class='card'><div class='crm-section-head'><h2>Properties ({len(properties)})</h2><a class='button small' href='/office/properties?contact_id={quote(contact_id)}'>Manage properties</a></div>{table(('Property','Address','Type'), [[f"<a href='/office/properties/{esc(i.get('id'))}'>{esc(i.get('name') or i.get('property_name'))}</a>", esc(i.get('service_street')), esc(i.get('property_type'))] for i in properties], 'No properties are attached to this customer yet.')}</div>
    <details class='card'><summary>Notes and activity ({len(notes)})</summary><div style='margin-top:15px'>{note_form}<div class='timeline' style='margin-top:14px'>{note_items}</div></div></details>
    {payment_section}{imported_detail}
    <details class='card'><summary>Estimates ({len(estimates)})</summary><div style='margin-top:15px'>{table(('Estimate','Status','Total'), [[f"<a href='/office/estimates/{esc(i.get('id'))}'>{esc(i.get('estimate_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('total_cents') if i.get('total_cents') is not None else int(round(float(i.get('totalValue') or 0)*100)))] for i in estimates])}</div></details>
    <details class='card'><summary>Invoices ({len(invoices)})</summary><div style='margin-top:15px'>{table(('Invoice','Status','Balance'), [[f"<a href='/office/invoices/{esc(i.get('id'))}'>{esc(i.get('invoice_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('balance_cents') if i.get('balance_cents') is not None else int(round(float(i.get('amountDue') or 0)*100)))] for i in invoices])}</div></details>
    <details class='card'><summary>Documents ({len(client_files)})</summary><div style='margin-top:15px'>{table(('Document','Status','Completed','Property','File'), [[esc(i.get('title') or i.get('document_type') or i.get('id')), badge(i.get('status') or 'FILED'), esc(i.get('completed_at') or i.get('created_at') or ''), esc(i.get('property_id') or ''), f"<a href='{esc(i.get('signed_download_url') or i.get('download_url') or '#')}' target='_blank'>Open signed PDF</a>" if (i.get('signed_download_url') or i.get('download_url')) else 'File pending'] for i in client_files], 'No signed documents are attached to this customer yet.')}</div></details>
    <details class='card'><summary>RoomFlow jobs</summary><div class='crm-section-head' style='margin-top:15px'><span></span><a class='button small' href='/office/roomflow'>Open RoomFlow</a></div>{table(('Job','Property','Status','Estimate'), [[esc(i.get('job_name') or i.get('roomflow_job_id') or 'RoomFlow job'), esc(i.get('property_id') or ''), badge(i.get('status') or 'SYNCED'), f"<a href='/office/estimates/{esc(i.get('estimate_id'))}'>{esc(i.get('estimate_number') or 'Open')}</a>" if i.get('estimate_id') else 'Not created'] for i in store.records('roomflow_jobs') if str(i.get('contact_id') or '') == contact_id], 'No RoomFlow jobs are attached to this customer yet.')}</details>"""
    return _page(_contact_label(contact), body, "contacts")


@app.post("/office/contacts/{contact_id}/notes")
async def add_contact_note(
    contact_id: str,
    body: str = Form(...),
    note_type: str = Form(default="GENERAL"),
    pinned: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("notes.manage")
    _ensure_local_contact(contact_id, await _state_page_data())
    store.create_record("notes", {
        "entity_type": "CONTACT",
        "entity_id": contact_id,
        "note_type": note_type.strip().upper() or "GENERAL",
        "body": body.strip(),
        "pinned": pinned == "yes",
        "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
    }, actor_id=str(actor.get("id")))
    store.set_notice("Customer-file note added.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/notes/{note_id}/delete")
def delete_contact_note(contact_id: str, note_id: str) -> RedirectResponse:
    _require("notes.manage")
    note = _local_record_or_404("notes", note_id)
    if str(note.get("entity_type") or "").upper() != "CONTACT" or str(note.get("entity_id") or "") != contact_id:
        raise HTTPException(404, "Note not found on this customer")
    store.delete_record("notes", note_id)
    store.set_notice("Customer-file note deleted.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/tags")
async def update_contact_tags(contact_id: str, tags: str = Form(default="")) -> RedirectResponse:
    actor = _require("contacts.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    values: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[,\n;]+", tags):
        value = part.strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key); values.append(value[:60])
    store.update_record("contacts", str(contact["id"]), {"tags": values[:30]}, actor_id=str(actor.get("id")))
    store.set_notice("Customer tags updated.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/cards/refresh")
async def refresh_contact_cards(contact_id: str) -> RedirectResponse:
    actor = _require("contacts.manage")
    try:
        await _reconcile_square_invoices_once()
    except Exception:
        pass
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    try:
        customer = await providers.ensure_square_customer(contact)
        customer_id = str(customer.get("id") or "")
        cards = await providers.list_square_cards(customer_id)
        updates: dict[str, Any] = {"square_customer_id": customer_id, "square_cards_refreshed_at": datetime.now(UTC).isoformat()}
        default_id = str(contact.get("default_square_card_id") or "")
        card_ids = {str(item.get("id") or "") for item in cards}
        selected_default = None
        if default_id not in card_ids:
            updates["default_square_card_id"] = sorted(card_ids)[0] if card_ids else None
            selected_default = next((item for item in cards if str(item.get("id") or "") == str(updates["default_square_card_id"] or "")), None)
            if contact.get("auto_charge_enabled") and not updates["default_square_card_id"]:
                updates["auto_charge_enabled"] = False
        store.update_record("contacts", contact_id, updates, actor_id=str(actor.get("id")))
        if selected_default:
            store.create_record("notes", {
                "entity_type": "CONTACT", "entity_id": contact_id, "note_type": "BILLING",
                "body": f"Card ending in {selected_default.get('last_4') or '****'} was selected as the default tokenized payment method. Automatic charging remains controlled by the customer authorization setting.",
                "pinned": False, "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
            }, actor_id=str(actor.get("id")))
        store.set_notice(f"Payment profile linked. {len(cards)} active card(s) found.")
    except Exception as exc:
        store.set_notice(f"Saved payment method refresh failed: {exc}")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/cards/{card_id}/default")
async def set_default_contact_card(contact_id: str, card_id: str) -> RedirectResponse:
    actor = _require("contacts.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    cards = await providers.list_square_cards(str(contact.get("square_customer_id") or ""))
    if card_id not in {str(item.get("id") or "") for item in cards}:
        raise HTTPException(404, "Saved payment method not found for this customer")
    selected = next((item for item in cards if str(item.get("id") or "") == card_id), {})
    store.update_record("contacts", contact_id, {"default_square_card_id": card_id}, actor_id=str(actor.get("id")))
    store.create_record("notes", {
        "entity_type": "CONTACT", "entity_id": contact_id, "note_type": "BILLING",
        "body": f"Default payment method changed to {selected.get('card_brand') or 'card'} ending in {selected.get('last_4') or '****'}.",
        "pinned": False, "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
    }, actor_id=str(actor.get("id")))
    store.set_notice("Default payment method updated.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/cards/{card_id}/disable")
async def disable_contact_card(contact_id: str, card_id: str) -> RedirectResponse:
    actor = _require("contacts.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    cards = await providers.list_square_cards(str(contact.get("square_customer_id") or ""))
    if card_id not in {str(item.get("id") or "") for item in cards}:
        raise HTTPException(404, "Saved payment method not found for this customer")
    selected = next((item for item in cards if str(item.get("id") or "") == card_id), {})
    await providers.disable_square_card(card_id)
    updates: dict[str, Any] = {}
    if str(contact.get("default_square_card_id") or "") == card_id:
        updates.update({"default_square_card_id": None, "auto_charge_enabled": False})
    if updates:
        store.update_record("contacts", contact_id, updates, actor_id=str(actor.get("id")))
    store.create_record("notes", {
        "entity_type": "CONTACT", "entity_id": contact_id, "note_type": "BILLING",
        "body": f"Payment method ending in {selected.get('last_4') or '****'} was disabled. Automatic charging was also disabled if this was the default card.",
        "pinned": False, "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
    }, actor_id=str(actor.get("id")))
    store.set_notice("Payment method disabled. No card number was stored in Floodman.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/auto-charge")
async def set_contact_auto_charge(
    contact_id: str,
    enabled: str = Form(default="no"),
    authorization_confirm: str = Form(default=""),
    authorization_reference: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("contacts.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    if enabled == "yes":
        if authorization_confirm != "yes" or not authorization_reference.strip():
            store.set_notice("Explicit customer authorization and a reference are required before automatic charging can be enabled.")
            return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)
        customer_id = str(contact.get("square_customer_id") or "")
        card_id = str(contact.get("default_square_card_id") or "")
        cards = await providers.list_square_cards(customer_id) if customer_id else []
        if not card_id or card_id not in {str(item.get("id") or "") for item in cards}:
            store.set_notice("Choose a valid default saved card before enabling automatic charging.")
            return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)
        authorized_at = datetime.now(UTC).isoformat()
        reference = authorization_reference.strip()[:500]
        store.update_record("contacts", contact_id, {
            "auto_charge_enabled": True,
            "auto_charge_authorized_at": authorized_at,
            "auto_charge_authorization_reference": reference,
            "auto_charge_authorized_by": str(actor.get("id") or ""),
        }, actor_id=str(actor.get("id")))
        store.create_record("notes", {
            "entity_type": "CONTACT", "entity_id": contact_id, "note_type": "BILLING",
            "body": f"Automatic invoice charging enabled. Authorization reference: {reference}",
            "pinned": True, "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
        }, actor_id=str(actor.get("id")))
        store.set_notice("Automatic invoice charging enabled under the recorded customer authorization.")
    else:
        store.update_record("contacts", contact_id, {
            "auto_charge_enabled": False,
            "auto_charge_disabled_at": datetime.now(UTC).isoformat(),
            "auto_charge_disabled_by": str(actor.get("id") or ""),
        }, actor_id=str(actor.get("id")))
        store.create_record("notes", {
            "entity_type": "CONTACT", "entity_id": contact_id, "note_type": "BILLING",
            "body": "Automatic invoice charging disabled.", "pinned": True,
            "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
        }, actor_id=str(actor.get("id")))
        store.set_notice("Automatic invoice charging disabled.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.get("/office/properties")
async def properties_page(contact_id: str = "") -> HTMLResponse:
    _require("properties.view")
    state = await _state_page_data()
    contacts = _all_contact_rows(state)
    selected_contact = next(
        (item for item in contacts if str(item.get("id") or "") == contact_id),
        None,
    ) if contact_id else None
    if contact_id and not selected_contact:
        raise HTTPException(404, "Customer not found")
    properties = [
        item for item in _all_property_rows(state)
        if selected_contact and str(item.get("contact_id") or "") == contact_id
    ]
    rows = []
    for item in properties:
        address = item.get("service_address") or {}
        street = address.get("street") or item.get("service_street")
        city = address.get("city") or item.get("service_city")
        state_code = address.get("state") or item.get("service_state")
        postal_code = address.get("postal_code") or address.get("postalCode") or item.get("service_postal_code")
        formatted = ", ".join(value for value in (street, city, " ".join(value for value in (state_code, postal_code) if value)) if value)
        rows.append([
            f"<a href='/office/properties/{esc(item.get('id'))}'>{esc(item.get('property_name') or item.get('name') or item.get('id'))}</a>",
            esc(formatted),
            esc(item.get("property_type") or ""),
        ])

    selected_label = _contact_label(selected_contact) if selected_contact else ""
    selector = f"""<div class='card'><h2>Select a customer</h2><form method='get' action='/office/properties'><div class='form-grid'>
    {_entity_picker(kind='contacts', name='contact_id', label='Customer', selected_id=contact_id, selected_label=selected_label, required=True)}
    <div class='field' style='align-self:end'><button>Show properties</button></div></div></form></div>"""

    customer_summary = ""
    if selected_contact:
        customer_summary = f"""<div class='card'><div class='crm-section-head'><div><small class='muted'>Selected customer</small><h2>{esc(selected_label)}</h2><div class='muted'>{esc(selected_contact.get('primaryEmail') or selected_contact.get('email') or '')} · {esc(selected_contact.get('primaryPhone') or selected_contact.get('phone') or '')}</div></div><a class='button secondary' href='/office/contacts/{esc(contact_id)}'>Open customer</a></div></div>"""

    create = ""
    if selected_contact and has_permission(_user(), "properties.manage"):
        create = f"""<details class='card'><summary>Add a property for {esc(selected_label)}</summary><form method='post' action='/office/properties/add' style='margin-top:15px'><input type='hidden' name='contact_id' value='{esc(contact_id)}'><div class='form-grid three'>
        <div class='field'><label>Property name</label><input name='name' placeholder='Home, rental, business' required></div><div class='field'><label>Property type</label><select name='property_type'><option>Residential</option><option>Commercial</option><option>Rental</option><option>Other</option></select></div><div></div>
        <div class='field full'><label>Service street</label><input name='service_street' required></div><div class='field'><label>City</label><input name='service_city' required></div>
        <div class='field'><label>State</label><input name='service_state' value='MI' required></div><div class='field'><label>Postal code</label><input name='service_postal_code' required></div>
        </div><details class='plain-details'><summary>Insurance, claim, and notes</summary><div class='form-grid' style='margin-top:12px'><div class='field'><label>Insurance company</label><input name='insurance_company'></div><div class='field'><label>Claim number</label><input name='claim_number'></div><div class='field full'><label>Property notes</label><textarea name='notes'></textarea></div></div></details><button style='margin-top:12px'>Create property</button></form></details>"""

    property_list = (
        f"<div class='card'><h2>Properties for {esc(selected_label)}</h2>"
        + table(('Property', 'Service address', 'Type'), rows, 'No properties are attached to this customer yet.')
        + "</div>"
        if selected_contact
        else "<div class='card empty'><h2>Choose a customer to begin</h2><p>Only that customer’s properties will appear here.</p></div>"
    )
    body = f"{selector}{customer_summary}{create}{property_list}"
    return _page("Properties", body, "properties")


@app.post("/office/properties/add")
async def add_property(
    contact_id: str = Form(...),
    name: str = Form(...),
    property_type: str = Form(default="Residential"),
    service_street: str = Form(...),
    service_city: str = Form(...),
    service_state: str = Form(default="MI"),
    service_postal_code: str = Form(...),
    insurance_company: str = Form(default=""),
    claim_number: str = Form(default=""),
    notes: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("properties.manage")
    _ensure_local_contact(contact_id, await _state_page_data())
    record = store.create_record("properties", {
        "contact_id": contact_id,
        "name": name.strip(),
        "property_name": name.strip(),
        "property_type": property_type.strip(),
        "service_street": service_street.strip(),
        "service_city": service_city.strip(),
        "service_state": service_state.strip(),
        "service_postal_code": service_postal_code.strip(),
        "insurance_company": insurance_company.strip(),
        "claim_number": claim_number.strip(),
        "notes": notes.strip(),
        "status": "ACTIVE",
    }, actor_id=actor.get("id"))
    notice = f"Property {record['name']} created."
    try:
        external = await _sync_property_to_real_gauzy(record, str(actor.get("id")))
        if external:
            notice += " Created as a Floodman project."
    except Exception as exc:
        notice += f" Floodman project sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/properties/{record['id']}", status_code=303)


@app.get("/office/properties/{property_id}")
async def property_detail(property_id: str) -> HTMLResponse:
    _require("properties.view")
    state = await _state_page_data()
    property_record = store.record("properties", property_id)
    if not property_record:
        property_record = next((item for item in _rows(state.get("properties")) if str(item.get("id") or "") == property_id), None)
    if not property_record:
        raise HTTPException(404, "Property not found")
    financials = _rows(state.get("gauzy_invoices"))
    estimates = [item for item in store.records("estimates") + financials if item.get("isEstimate") is True and str(item.get("property_id") or "") == property_id]
    estimates += [item for item in store.records("estimates") if str(item.get("property_id") or "") == property_id and item not in estimates]
    invoices = [item for item in store.records("invoices") + financials if item.get("isEstimate") is not True and str(item.get("property_id") or "") == property_id]
    documents = [item for item in store.records("documents") + _rows(state.get("imported_documents")) if str(item.get("property_id") or "") == property_id]
    def unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set(); result: list[dict[str, Any]] = []
        for item in rows:
            identity = str(item.get("id") or item.get("legacy_document_id") or "")
            if identity and identity in seen: continue
            if identity: seen.add(identity)
            result.append(item)
        return result
    estimates, invoices, documents = unique(estimates), unique(invoices), unique(documents)
    address = f"{property_record.get('service_street','')}, {property_record.get('service_city','')}, {property_record.get('service_state','')} {property_record.get('service_postal_code','')}"
    manage = f"<a class='button secondary' href='/office/properties/{esc(property_id)}/edit'>Edit property</a>" if store.record("properties", property_id) and has_permission(_user(), "properties.manage") else ""
    body = f"""<div class='actions'><a class='button secondary' href='/office/properties'>Back</a><a class='button' href='/office/estimates/new?contact_id={quote(str(property_record.get('contact_id') or ''))}&property_id={quote(property_id)}'>Create estimate</a><a class='button' href='/office/documents?property_id={quote(property_id)}'>Send document</a>{manage}</div>
    <div class='grid two' style='margin-top:15px'><div class='card'><h2>{esc(property_record.get('name') or property_record.get('property_name'))}</h2><p><b>Customer:</b> {esc(_contact_name(str(property_record.get('contact_id') or ''), state))}</p><p><b>Address:</b> {esc(address)}</p><p><b>Type:</b> {esc(property_record.get('property_type'))}</p><p><b>Insurance:</b> {esc(property_record.get('insurance_company') or property_record.get('insurer'))}</p><p><b>Claim:</b> {esc(property_record.get('claim_number'))}</p><p><b>Notes:</b> {esc(property_record.get('notes'))}</p></div>
    <div class='card'><h2>Property summary</h2><div class='grid'><div class='metric'><small>Estimates</small><strong>{len(estimates)}</strong></div><div class='metric'><small>Invoices</small><strong>{len(invoices)}</strong></div><div class='metric'><small>Documents</small><strong>{len(documents)}</strong></div></div></div></div>
    <div class='card'><h2>Estimates</h2>{table(('Estimate','Status','Total'), [[f"<a href='/office/estimates/{esc(i.get('id'))}'>{esc(i.get('estimate_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('total_cents') if i.get('total_cents') is not None else int(round(float(i.get('totalValue') or 0)*100)))] for i in estimates])}</div>
    <div class='card'><h2>Invoices</h2>{table(('Invoice','Status','Balance'), [[f"<a href='/office/invoices/{esc(i.get('id'))}'>{esc(i.get('invoice_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('balance_cents') if i.get('balance_cents') is not None else int(round(float(i.get('amountDue') or 0)*100)))] for i in invoices])}</div>"""
    return _page(str(property_record.get("name") or property_record.get("property_name") or "Property"), body, "properties")



@app.get("/office/api/catalog/items")
def catalog_items_api(q: str = "", category: str = "", limit: int = 30) -> dict[str, Any]:
    user = _require("estimates.view")
    if has_permission(user, "estimates.manage"):
        _import_bundled_roomflow_catalog(actor_id=str(user.get("id") or "floodman-office"))
    query = str(q or "").strip().casefold()
    category_key = str(category or "").strip().casefold()
    items = []
    for item in store.records("catalog_items"):
        if item.get("active") is False:
            continue
        pricing = ((item.get("formula") or {}).get("xactimate") or {})
        searchable = " ".join([
            *(str(item.get(key) or "") for key in ("name", "description", "category", "default_section", "unit", "external_key", "source_id")),
            *(str(pricing.get(key) or "") for key in ("code", "price_list", "market", "effective_date")),
        ]).casefold()
        if query and query not in searchable:
            continue
        if category_key and str(item.get("category") or "").casefold() != category_key:
            continue
        items.append(item)
    items.sort(key=lambda item: (str(item.get("category") or "").casefold(), str(item.get("name") or "").casefold()))
    safe_limit = max(1, min(100, int(limit or 30)))
    return {"items": items[:safe_limit], "total": len(items)}


@app.post("/office/api/catalog/items")
async def create_catalog_item_api(request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Catalog item must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Catalog item must be an object.")
    try:
        item, created = _upsert_catalog_item(payload, actor_id=str(actor.get("id")), source=str(payload.get("source_provider") or "FLOODMAN_CUSTOM"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "created": created, "item": item}


@app.post("/office/api/catalog/import/roomflow")
async def import_roomflow_catalog_api(request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="RoomFlow catalog payload must be valid JSON.") from exc
    raw_items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(raw_items, list):
        raise HTTPException(status_code=422, detail="RoomFlow catalog payload must contain an items array.")
    result = _import_catalog_rows(
        raw_items,
        actor_id=str(actor.get("id")),
        source_provider="ROOMFLOW_SUPABASE",
    )
    store.set_notice(
        f"RoomFlow/Supabase catalog synchronized: {result['added']} added, "
        f"{result['updated']} updated, {result['skipped']} skipped."
    )
    return {"ok": True, **result}


@app.post("/office/api/catalog/import/bundled-roomflow")
def import_bundled_roomflow_catalog_api(force: bool = False) -> dict[str, Any]:
    actor = _require("estimates.manage")
    result = _import_bundled_roomflow_catalog(actor_id=str(actor.get("id")), force=bool(force))
    if result.get("errors"):
        raise HTTPException(status_code=422, detail=" ".join(result["errors"]))
    store.set_notice(
        f"Bundled RoomFlow catalog loaded: {result['added']} added, "
        f"{result['updated']} updated, {result['skipped']} skipped."
    )
    return {"ok": True, **result}


@app.post("/office/catalog/import-roomflow")
def import_bundled_roomflow_catalog_page() -> RedirectResponse:
    actor = _require("estimates.manage")
    result = _import_bundled_roomflow_catalog(actor_id=str(actor.get("id")), force=True)
    if result.get("errors"):
        store.set_notice(" ".join(result["errors"]))
    else:
        store.set_notice(
            f"RoomFlow catalog loaded: {result['added']} added, "
            f"{result['updated']} updated, {result['skipped']} skipped."
        )
    return RedirectResponse("/office/catalog", status_code=303)



# ---------------------------------------------------------------------------
# Floodman customer documents and payments
# ---------------------------------------------------------------------------

def _payment_security_headers(*, allow_sdk: bool = False) -> dict[str, str]:
    script_sources = "'self'"
    frame_sources = "'self'"
    connect_sources = "'self'"
    style_sources = "'self' 'unsafe-inline'"
    font_sources = "'self' data:"
    if allow_sdk:
        script_sources += " https://web.squarecdn.com https://sandbox.web.squarecdn.com"
        frame_sources += " https://web.squarecdn.com https://sandbox.web.squarecdn.com"
        connect_sources += " https://web.squarecdn.com https://sandbox.web.squarecdn.com https://pci-connect.squareup.com https://pci-connect.squareupsandbox.com https://o160250.ingest.sentry.io"
        style_sources += " https://web.squarecdn.com https://sandbox.web.squarecdn.com"
        font_sources += " https://square-fonts-production-f.squarecdn.com https://d1g145x70srn7h.cloudfront.net"
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
        "Content-Security-Policy": (
            "default-src 'self'; "
            f"script-src {script_sources}; "
            f"style-src {style_sources}; "
            f"frame-src {frame_sources}; "
            f"connect-src {connect_sources}; "
            f"img-src 'self' data: https:; font-src {font_sources}; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        ),
    }


def _document_contact_property(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    contact = store.record("contacts", str(document.get("contact_id") or "")) or {}
    property_record = store.record("properties", str(document.get("property_id") or "")) or {}
    return contact, property_record


def _contact_display_name(contact: dict[str, Any]) -> str:
    return str(
        contact.get("name")
        or " ".join(part for part in (contact.get("first_name"), contact.get("last_name")) if part)
        or contact.get("email")
        or "Customer"
    ).strip()


def _notification_id(event_kind: str, event_id: str, user_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-notification:{event_kind}:{event_id}:{user_id}"))


async def _notify_staff(
    *,
    permission: str,
    event_kind: str,
    event_id: str,
    reference_id: str,
    title: str,
    body: str,
    action_url: str,
    email_subject: str,
) -> int:
    """Create one durable alert per eligible staff member and email it once.

    The stable event/user identifier makes payment callbacks and browser retries
    safe.  Email failure never rolls back the business event; the in-app/mobile
    notification remains available and records delivery status for staff review.
    """
    recipients = [
        user
        for user in store.list_users()
        if str(user.get("status") or "ACTIVE").upper() == "ACTIVE" and has_permission(user, permission)
    ]
    pending: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for user in recipients:
        user_id = str(user.get("id") or "")
        if not user_id:
            continue
        notification, created = store.create_record_if_absent(
            "notifications",
            _notification_id(event_kind, event_id, user_id),
            {
                "user_id": user_id,
                "title": title,
                "body": body,
                "kind": event_kind,
                "reference_id": reference_id,
                "action_url": action_url if action_url.startswith("/office/") else "/office/alerts",
                "status": "UNREAD",
                "email_status": "PENDING" if user.get("email") else "NO_EMAIL",
                "source": "FLOODMAN_NOTIFICATION",
            },
            actor_id="floodman-system",
        )
        if created and user.get("email"):
            pending.append((user, notification))

    async def deliver(user: dict[str, Any], notification: dict[str, Any]) -> None:
        try:
            office_url = f"{settings.public_url.rstrip('/')}/office/alerts/{quote(str(notification.get('id') or ''))}/open"
            await providers.send_email(
                to=str(user.get("email") or ""),
                subject=email_subject,
                text=f"{body}\n\nOpen Floodman: {office_url}",
            )
            store.update_record(
                "notifications",
                str(notification["id"]),
                {"email_status": "SENT", "email_sent_at": datetime.now(UTC).isoformat()},
                actor_id="floodman-system",
            )
        except Exception:
            store.update_record(
                "notifications",
                str(notification["id"]),
                {"email_status": "FAILED"},
                actor_id="floodman-system",
            )

    if pending:
        await asyncio.gather(*(deliver(user, notification) for user, notification in pending))
    return len(recipients)


async def _notify_payment_admins(kind: str, document: dict[str, Any], payment: dict[str, Any]) -> int:
    contact, _ = _document_contact_property(document)
    number = str(
        document.get("estimate_number")
        if kind == "estimate"
        else document.get("invoice_number") or document.get("id") or ""
    )
    label = "deposit" if kind == "estimate" else "invoice payment"
    amount = money_cents(payment.get("amount_cents"), str(payment.get("currency") or "USD"))
    customer = _contact_display_name(contact)
    action_url = f"/office/{kind}s/{quote(str(document.get('id') or ''))}"
    return await _notify_staff(
        permission="payments.manage",
        event_kind="PAYMENT_RECEIVED",
        event_id=str(payment.get("id") or ""),
        reference_id=str(payment.get("id") or ""),
        title=f"Payment received: {amount}",
        body=f"{customer} paid {amount} toward {label} {number}. Open Floodman to review the balance and receipt.",
        action_url=action_url,
        email_subject=f"Floodman payment received - {number}",
    )


def _customer_thread_id(contact_id: str, property_id: str = "", document_id: str = "") -> str:
    # A document capability may be forwarded to an insurer or other project
    # participant.  Scope conversations to the service property (or, when no
    # property exists, the individual document) so one link cannot expose an
    # unrelated project belonging to the same customer.
    scope = str(property_id or "").strip() or f"document:{str(document_id or '').strip()}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-customer-thread:{contact_id}:{scope}"))


def _customer_thread(document: dict[str, Any], kind: str, *, create: bool = False) -> dict[str, Any] | None:
    contact_id = str(document.get("contact_id") or "")
    if not contact_id:
        return None
    thread_id = _customer_thread_id(contact_id, str(document.get("property_id") or ""), str(document.get("id") or ""))
    thread = store.record("customer_threads", thread_id)
    if thread or not create:
        return thread
    thread, _ = store.create_record_if_absent(
        "customer_threads",
        thread_id,
        {
            "contact_id": contact_id,
            "property_id": document.get("property_id"),
            "last_document_kind": kind,
            "last_document_id": document.get("id"),
            "status": "OPEN",
            "source": "FLOODMAN_CUSTOMER_PORTAL",
        },
        actor_id="customer-portal",
    )
    return thread


def _customer_thread_messages(thread_id: str) -> list[dict[str, Any]]:
    return sorted(
        [item for item in store.records("customer_messages") if str(item.get("thread_id") or "") == thread_id],
        key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")),
    )


def _clean_portal_message(value: str) -> str:
    message = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not message:
        raise ValueError("Write a message before sending.")
    if len(message) > 3000:
        raise ValueError("Messages can contain up to 3,000 characters.")
    return message


async def _notify_customer_message_staff(document: dict[str, Any], message: dict[str, Any], thread_id: str) -> int:
    contact, _ = _document_contact_property(document)
    customer = _contact_display_name(contact)
    return await _notify_staff(
        permission="messages.manage",
        event_kind="CUSTOMER_MESSAGE",
        event_id=str(message.get("id") or ""),
        reference_id=thread_id,
        title="New customer portal message",
        body=f"{customer} sent a secure portal message. Open Floodman Messages to read and respond.",
        action_url=f"/office/messages?thread={quote(thread_id)}",
        email_subject=f"Floodman customer message - {customer}",
    )


def _customer_conversation_body(kind: str, document: dict[str, Any]) -> str:
    thread_id = _customer_thread_id(
        str(document.get("contact_id") or ""),
        str(document.get("property_id") or ""),
        str(document.get("id") or ""),
    )
    messages = _customer_thread_messages(thread_id)
    unread = sum(1 for item in messages if str(item.get("sender_kind") or "").upper() == "STAFF" and not item.get("customer_read_at"))
    rendered = "".join(
        f"<article class='portal-message {'staff' if str(item.get('sender_kind') or '').upper() == 'STAFF' else 'customer'}'><div class='portal-message-head'><b>{esc('Floodman team' if str(item.get('sender_kind') or '').upper() == 'STAFF' else 'You')}</b><span>{esc(str(item.get('created_at') or '')[:16].replace('T', ' '))} UTC</span></div><p>{esc(item.get('body') or '').replace(chr(10), '<br>')}</p></article>"
        for item in messages
    ) or "<div class='notice'>No messages yet. Send a question below and the Floodman team will be notified.</div>"
    request_id = secrets.token_urlsafe(24)
    read_form = (
        f"<form method='post' action='/customer/{esc(kind)}/{esc(document.get('public_token') or '')}/messages/read'><button class='secondary'>Mark replies read</button></form>"
        if unread
        else ""
    )
    return f"""
<section class='card portal-conversation' id='messages'><div class='portal-message-title'><div><span class='eyebrow'>SECURE CUSTOMER MESSAGES</span><h2>Message the Floodman team</h2><p>Ask a project, scheduling, estimate, or billing question here. Staff replies stay with your customer file.</p></div>{f"<span class='status'>{unread} new repl{'y' if unread == 1 else 'ies'}</span>" if unread else ""}</div>
<div class='portal-message-list' aria-live='polite'>{rendered}</div>
{read_form}
<form method='post' action='/customer/{esc(kind)}/{esc(document.get('public_token') or '')}/messages' class='portal-message-form'><input type='hidden' name='request_id' value='{esc(request_id)}'><div class='portal-honeypot' aria-hidden='true'><label>Website<input name='website' tabindex='-1' autocomplete='off'></label></div><div class='field'><label for='portal-message-body'>Your message</label><textarea id='portal-message-body' name='body' maxlength='3000' rows='5' required placeholder='How can we help?'></textarea><small>Do not send card numbers, security codes, passwords, or other sensitive account information.</small></div><button>Send message</button></form></section>
"""


def _ensure_public_document(kind: str, document: dict[str, Any], *, actor_id: str = "floodman-system") -> dict[str, Any]:
    record_id = str(document.get("id") or "")
    if kind not in {"estimate", "invoice"} or not record_id:
        raise ValueError("A local estimate or invoice is required.")
    plural = kind + "s"
    token = str(document.get("public_token") or "").strip()
    if not token:
        token = secrets.token_urlsafe(32)
    public_url = f"{settings.customer_public_url}/{kind}/{token}"
    pay_url = f"{settings.customer_public_url}/pay/{token}"
    pdf_url = f"{settings.customer_public_url}/{kind}/{token}/pdf"
    values = {
        "public_token": token,
        "public_url": public_url,
        "public_pay_url": pay_url,
        "public_pdf_url": pdf_url,
        "public_enabled": True,
        "public_created_at": document.get("public_created_at") or datetime.now(UTC).isoformat(),
    }
    updated = store.update_record(plural, record_id, values, actor_id=actor_id)
    return updated


def _public_document(token: str) -> tuple[str, dict[str, Any]]:
    candidate = str(token or "").strip()
    if len(candidate) < 20:
        raise HTTPException(404, "Document link not found")
    for kind in ("estimate", "invoice"):
        for record in store.records(kind + "s"):
            if secrets.compare_digest(str(record.get("public_token") or ""), candidate):
                if record.get("public_enabled") is False:
                    break
                return kind, record
    raise HTTPException(404, "Document link not found")


def _estimate_payment_values(estimate: dict[str, Any]) -> dict[str, int | str | bool]:
    deposit_cents, deposit_label = calculate_deposit(estimate)
    paid_cents = int(estimate.get("deposit_paid_cents") or 0)
    due_cents = max(0, deposit_cents - paid_cents)
    stage = str(estimate.get("deposit_due_stage") or "AFTER_AUTHORIZATION").upper()
    payable = bool(estimate.get("deposit_payable")) or stage == "IMMEDIATELY" or str(estimate.get("status") or "").upper() in {"ACCEPTED", "APPROVED", "DEPOSIT_DUE", "DEPOSIT_PAID"}
    if deposit_cents == 0:
        payable = False
    return {
        "deposit_cents": deposit_cents,
        "deposit_label": deposit_label,
        "paid_cents": paid_cents,
        "due_cents": due_cents,
        "payable": payable,
        "stage": stage,
    }


def _document_pdf(kind: str, document: dict[str, Any]) -> bytes:
    contact, property_record = _document_contact_property(document)
    if kind == "estimate":
        public_url = str(document.get("public_url") or "")
        payments = [item for item in store.records("payments") if str(item.get("estimate_id") or "") == str(document.get("id") or "")]
        document = merge_project_plan(enrich_estimate_with_roomflow(store, document))
        return build_estimate_pdf(document, contact, property_record, store.profile(), public_url=public_url, payments=payments)
    payments = [item for item in store.records("payments") if str(item.get("invoice_id") or "") == str(document.get("id") or "")]
    documents = [item for item in store.records("documents") if str(item.get("invoice_id") or item.get("floodman_invoice_id") or "") == str(document.get("id") or "")]
    return build_invoice_pdf(document, contact, property_record, store.profile(), payments=payments, documents=documents, public_url=str(document.get("public_url") or ""))


def _payment_card_summary(payment: dict[str, Any]) -> dict[str, Any]:
    details = payment.get("card_details") if isinstance(payment.get("card_details"), dict) else {}
    card = details.get("card") if isinstance(details.get("card"), dict) else {}
    return {
        "processor_payment_id": str(payment.get("id") or ""),
        "processor_status": str(payment.get("status") or ""),
        "receipt_url": str(payment.get("receipt_url") or ""),
        "card_brand": str(card.get("card_brand") or "CARD"),
        "last_4": str(card.get("last_4") or ""),
        "exp_month": card.get("exp_month"),
        "exp_year": card.get("exp_year"),
        "entry_method": str(details.get("entry_method") or ""),
    }


async def _record_document_payment(
    *,
    kind: str,
    document: dict[str, Any],
    amount_cents: int,
    method: str,
    reference: str,
    note: str,
    actor_id: str,
    processor_payment: dict[str, Any] | None = None,
    payment_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record_id = str(document.get("id") or "")
    if kind == "invoice":
        maximum = int(document.get("balance_cents") or 0)
    else:
        maximum = int(_estimate_payment_values(document)["due_cents"])
    if amount_cents <= 0 or amount_cents > maximum:
        raise HTTPException(422, f"Payment must be between $0.01 and {money_cents(maximum)}.")
    processor_id = str((processor_payment or {}).get("id") or "")
    if processor_id:
        existing = next((p for p in store.records("payments") if str(p.get("processor_payment_id") or "") == processor_id), None)
        if existing:
            current_document = store.record(kind + "s", record_id) or document
            await _notify_payment_admins(kind, current_document, existing)
            return existing
    values: dict[str, Any] = {
        "invoice_id": record_id if kind == "invoice" else None,
        "estimate_id": record_id if kind == "estimate" else None,
        "contact_id": document.get("contact_id"),
        "property_id": document.get("property_id"),
        "amount_cents": amount_cents,
        "currency": document.get("currency") or "USD",
        "method": method.upper(),
        "reference": reference.strip(),
        "note": note.strip(),
        "payment_date": datetime.now(UTC).isoformat(),
        "status": "COMPLETED",
        "source": "FLOODMAN_PAYMENTS",
    }
    values.update(_payment_card_summary(processor_payment or {}))
    values.update(payment_metadata or {})
    if processor_id:
        stable_payment_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-processor-payment:{processor_id}"))
        payment, payment_created = store.create_record_if_absent(
            "payments", stable_payment_id, values, actor_id=actor_id
        )
        if not payment_created:
            current_document = store.record(kind + "s", record_id) or document
            await _notify_payment_admins(kind, current_document, payment)
            return payment
    else:
        payment = store.create_record("payments", values, actor_id=actor_id)
    if kind == "invoice":
        new_paid = int(document.get("paid_cents") or 0) + amount_cents
        total = int(document.get("total_cents") or 0)
        new_balance = max(0, total - new_paid)
        store.update_record("invoices", record_id, {
            "paid_cents": new_paid,
            "balance_cents": new_balance,
            "status": "PAID" if new_balance == 0 else "PARTIALLY_PAID",
            "last_payment_at": payment["payment_date"],
        }, actor_id=actor_id)
    else:
        values = _estimate_payment_values(document)
        new_paid = int(values["paid_cents"]) + amount_cents
        deposit_total = int(values["deposit_cents"])
        store.update_record("estimates", record_id, {
            "deposit_paid_cents": new_paid,
            "deposit_balance_cents": max(0, deposit_total - new_paid),
            "deposit_status": "PAID" if new_paid >= deposit_total else "PARTIALLY_PAID",
            "last_payment_at": payment["payment_date"],
        }, actor_id=actor_id)
    try:
        await providers.record_payment({
            "invoiceId": document.get("provider_id") or record_id,
            "amount": amount_cents / 100,
            "currency": document.get("currency") or "USD",
            "paymentDate": payment["payment_date"],
            "paymentMethod": method.upper(),
            "note": note.strip(),
        })
    except Exception:
        pass
    current_document = store.record(kind + "s", record_id) or document
    await _notify_payment_admins(kind, current_document, payment)
    return payment


def _payment_email_html(title: str, summary: str, public_url: str, button_label: str) -> str:
    return f"""<!doctype html><html><body style='font-family:Arial,sans-serif;background:#eef4f7;padding:24px;color:#153247'><div style='max-width:640px;margin:auto;background:#fff;border-radius:14px;padding:28px'><h1 style='letter-spacing:.08em;color:#12344b'>FLOODMAN</h1><h2>{esc(title)}</h2><p>{esc(summary)}</p><p><a href='{esc(public_url)}' style='display:inline-block;background:#129dcc;color:#fff;text-decoration:none;padding:13px 18px;border-radius:8px;font-weight:bold'>{esc(button_label)}</a></p><p style='color:#6c7b88'>Floodman, LLC - Northern Michigan - (231) 935-4921 - office@floodman.com</p></div></body></html>"""


async def _send_customer_document(kind: str, document: dict[str, Any], *, actor_id: str) -> tuple[dict[str, Any], str]:
    updated = _ensure_public_document(kind, document, actor_id=actor_id)
    contact, _ = _document_contact_property(updated)
    email = str(contact.get("email") or contact.get("primaryEmail") or "").strip()
    if not email:
        raise RuntimeError("The customer file needs an email address before this document can be sent.")
    pdf = _document_pdf(kind, updated)
    number = str(updated.get("estimate_number") if kind == "estimate" else updated.get("invoice_number") or updated.get("id"))
    title = "Your Floodman project estimate" if kind == "estimate" else "Your Floodman invoice"
    summary = (
        f"Estimate {number} is ready for review."
        if kind == "estimate"
        else f"Invoice {number} is due upon receipt."
    )
    button = "Review estimate" if kind == "estimate" else "View invoice and pay"
    await providers.send_email(
        to=email,
        subject=f"Floodman {number}",
        text=f"{summary}\n\nOpen securely: {updated['public_url']}\n\nFloodman, LLC | (231) 935-4921",
        html=_payment_email_html(title, summary, str(updated["public_url"]), button),
        attachments=[(f"{number}.pdf", pdf, "application/pdf")],
    )
    plural = kind + "s"
    sent_at = datetime.now(UTC).isoformat()
    send_updates = {
        "status": "SENT",
        "sent_at": sent_at,
        "last_sent_to": email,
        "delivery_mode": "FLOODMAN_EMAIL",
    }
    if kind == "invoice":
        send_updates.update({"issued_at": sent_at, "due_at": sent_at})
    else:
        send_updates.update({"issued_at": updated.get("issued_at") or sent_at})
    updated = store.update_record(plural, str(updated["id"]), send_updates, actor_id=actor_id)
    return updated, email



def _customer_document_body(kind: str, document: dict[str, Any]) -> str:
    contact, property_record = _document_contact_property(document)
    groups = group_document_lines(document)
    public_pdf = str(document.get("public_pdf_url") or "")
    title = str(document.get("title") or ("Floodman project estimate" if kind == "estimate" else "Floodman invoice"))
    number = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "")
    customer = str(contact.get("name") or " ".join(part for part in (contact.get("first_name"), contact.get("last_name")) if part) or "Customer")
    property_lines = [
        property_record.get("service_street") or property_record.get("street"),
        ", ".join(part for part in (
            str(property_record.get("service_city") or property_record.get("city") or "").strip(),
            " ".join(part for part in (
                str(property_record.get("service_state") or property_record.get("state") or "").strip(),
                str(property_record.get("service_postal_code") or property_record.get("postal_code") or "").strip(),
            ) if part),
        ) if part),
    ]
    property_text = "<br>".join(esc(item) for item in property_lines if item) or "Service property"
    scope = customer_grouped_lines(groups)
    download = f"<a class='button secondary' href='{esc(public_pdf)}' target='_blank'>Download Floodman PDF</a>" if public_pdf else ""
    if kind == "estimate":
        values = _estimate_payment_values(document)
        status = str(document.get("status") or "READY FOR REVIEW").replace("_", " ")
        payment = ""
        if int(values["due_cents"]) > 0 and values["payable"]:
            payment = f"<a class='button good' href='{esc(document.get('public_pay_url') or '')}'>Pay {esc(values['deposit_label'])}</a>"
        elif int(values["deposit_cents"]) > 0 and int(values["due_cents"]) > 0:
            payment = "<div class='notice'><b>Deposit timing:</b> The secure payment button becomes available after project authorization.</div>"
        elif int(values["deposit_cents"]) > 0:
            payment = "<div class='notice good'><b>Deposit received.</b> Thank you. The payment is attached to this project.</div>"
        return f"""
<div class='card hero'><span class='eyebrow' style='color:#bfe3f0'>PROJECT ESTIMATE</span><h2>{esc(title)}</h2><p>{esc(number)} &nbsp; {esc(status)}</p></div>
<div class='grid'><div class='metric'><small>Total project</small><strong>{money_cents(document.get('total_cents'))}</strong></div><div class='metric'><small>{esc(values['deposit_label'])}</small><strong>{money_cents(values['deposit_cents'])}</strong></div><div class='metric'><small>Deposit remaining</small><strong>{money_cents(values['due_cents'])}</strong></div></div>
<div class='grid'><div class='card'><span class='eyebrow'>PREPARED FOR</span><h3>{esc(customer)}</h3><p>{esc(contact.get('email') or '')}<br>{esc(contact.get('phone') or '')}</p></div><div class='card'><span class='eyebrow'>SERVICE PROPERTY</span><h3>{property_text}</h3></div></div>
<div class='card'><h2>Detailed scope of work</h2>{scope}</div>
<div class='card'><h2>Approval and payment</h2><p>{esc(document.get('terms') or 'Review the scope, sign the Floodman Work Authorization, and pay the requested deposit to reserve scheduling.')}</p><div class='actions'>{payment}{download}</div></div>
"""
    total = int(document.get("total_cents") or 0)
    paid = int(document.get("paid_cents") or 0)
    balance = int(document.get("balance_cents") or max(0, total - paid))
    payments = [item for item in store.records("payments") if str(item.get("invoice_id") or "") == str(document.get("id") or "")]
    rows = "".join(
        f"<div class='line'><div><strong>{esc(str(item.get('method') or 'Payment').replace('_',' ').title())}</strong><small>{esc(item.get('payment_date') or '')}</small></div><div>{esc(item.get('reference') or item.get('last_4') or '')}</div><div style='text-align:right'>-{money_cents(item.get('amount_cents'))}</div></div>"
        for item in payments
    ) or "<div class='notice'>No payments have been recorded yet.</div>"
    payment_action = f"<a class='button good' href='{esc(document.get('public_pay_url') or '')}'>Pay {money_cents(balance)} securely</a>" if balance > 0 else "<div class='notice good'><b>Paid in full.</b> This invoice is now your Floodman receipt.</div>"
    return f"""
<div class='card hero'><span class='eyebrow' style='color:#bfe3f0'>INVOICE</span><h2>{esc(number)}</h2><p>{esc(title)}</p></div>
<div class='grid'><div class='metric'><small>Amount due now</small><strong>{money_cents(balance)}</strong></div><div class='metric'><small>Payments received</small><strong>{money_cents(paid)}</strong></div><div class='metric'><small>Contract total</small><strong>{money_cents(total)}</strong></div></div>
<div class='grid'><div class='card'><span class='eyebrow'>BILL TO</span><h3>{esc(customer)}</h3><p>{esc(contact.get('email') or '')}<br>{esc(contact.get('phone') or '')}</p></div><div class='card'><span class='eyebrow'>SERVICE PROPERTY</span><h3>{property_text}</h3></div></div>
<div class='card'><h2>Invoice details</h2>{scope}</div>
<div class='card'><h2>Payment and balance history</h2>{rows}<div class='subtotal'><span>Balance due</span><span>{money_cents(balance)}</span></div></div>
<div class='card'><h2>Secure Floodman payment</h2><p>Pay online using the secure card field. Floodman never stores the full card number or card security code.</p><div class='actions'>{payment_action}{download}</div></div>
"""


async def _send_payment_receipt(kind: str, document: dict[str, Any], payment: dict[str, Any]) -> None:
    contact, _ = _document_contact_property(document)
    email = str(contact.get("email") or contact.get("primaryEmail") or "").strip()
    if not email:
        return
    number = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "")
    payment_id = str(payment.get("id") or "")
    receipt_url = f"{settings.customer_public_url}/receipt/{document.get('public_token')}?payment={quote(payment_id)}"
    amount = money_cents(payment.get("amount_cents"))
    pdf = _document_pdf(kind, store.record(kind + "s", str(document.get("id"))) or document)
    await providers.send_email(
        to=email,
        subject=f"Floodman payment receipt - {number}",
        text=f"Floodman received {amount} for {number}.\n\nReceipt: {receipt_url}\n\nThank you.",
        html=_payment_email_html("Payment received", f"Floodman received {amount} for {number}.", receipt_url, "Open receipt"),
        attachments=[(f"{number}-receipt.pdf", pdf, "application/pdf")],
    )


def _payment_request_values(kind: str, document: dict[str, Any]) -> tuple[int, int, bool]:
    if kind == "estimate":
        values = _estimate_payment_values(document)
        return int(values["due_cents"]), int(values["due_cents"]), bool(values["payable"])
    balance = int(document.get("balance_cents") or 0)
    online_enabled = str(document.get("collection_mode") or "PAYMENT_PAGE").upper() != "OFFLINE_ONLY"
    return balance, balance, balance > 0 and online_enabled


async def _process_card_payment(kind: str, document: dict[str, Any], payload: dict[str, Any], *, staff_keyed: bool, actor_id: str) -> dict[str, Any]:
    config = providers.square_payment_configuration()
    if not settings.payments_enabled:
        raise HTTPException(503, "Floodman online payments are disabled.")
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id:
        raise HTTPException(422, "The secure payment token is missing. Please refresh and try again.")
    requested, maximum, payable = _payment_request_values(kind, document)
    if not payable or maximum <= 0:
        raise HTTPException(409, "No payment is currently due for this document.")
    try:
        amount_cents = int(payload.get("amount_cents") or requested)
    except (TypeError, ValueError):
        raise HTTPException(422, "Enter a valid payment amount.")
    if amount_cents <= 0 or amount_cents > maximum:
        raise HTTPException(422, f"Payment must be between $0.01 and {money_cents(maximum)}.")
    save_requested = bool(payload.get("save_card"))
    authorization_reference = str(payload.get("authorization_reference") or "").strip()
    if staff_keyed and save_requested and not authorization_reference:
        raise HTTPException(422, "Record the customer authorization reference before saving a phone-entered card.")
    contact, _ = _document_contact_property(document)
    customer = await providers.ensure_square_customer(contact)
    customer_id = str(customer.get("id") or "")
    fingerprint = f"{kind}:{document.get('id')}:{source_id}:{amount_cents}:{staff_keyed}"
    idempotency = str(uuid.uuid5(uuid.NAMESPACE_URL, fingerprint))
    reference = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "")
    processor_payment = await providers.create_square_payment(
        source_id=source_id,
        amount_cents=amount_cents,
        currency=str(document.get("currency") or "USD"),
        reference_id=reference,
        note=f"Floodman {'deposit' if kind == 'estimate' else 'invoice'} payment for {reference}",
        customer_id=customer_id or None,
        customer_initiated=not staff_keyed,
        seller_keyed_in=staff_keyed,
        idempotency_key=idempotency,
    )
    saved_card: dict[str, Any] | None = None
    save_warning = ""
    if save_requested:
        try:
            saved_card = await providers.create_square_card_from_payment(
                payment_id=str(processor_payment.get("id") or ""),
                customer_id=customer_id,
            )
            local_contact = store.record("contacts", str(document.get("contact_id") or ""))
            if local_contact:
                store.update_record("contacts", str(local_contact["id"]), {
                    "square_customer_id": customer_id,
                    "default_square_card_id": saved_card.get("id"),
                    "payment_method_saved_at": datetime.now(UTC).isoformat(),
                    "payment_method_authorization_reference": authorization_reference or "Customer selected save payment method during online payment",
                    "payment_method_card_brand": saved_card.get("card_brand"),
                    "payment_method_last_4": saved_card.get("last_4"),
                    "payment_method_exp_month": saved_card.get("exp_month"),
                    "payment_method_exp_year": saved_card.get("exp_year"),
                }, actor_id=actor_id)
        except Exception as exc:
            # The card charge has already succeeded. Never turn a completed payment into a
            # customer-facing failure because the optional save-card step was declined.
            save_warning = f"Payment completed, but the payment method was not saved: {exc}"
    payment = await _record_document_payment(
        kind=kind,
        document=document,
        amount_cents=amount_cents,
        method="CARD_BY_PHONE" if staff_keyed else "ONLINE_CARD",
        reference=str(processor_payment.get("id") or ""),
        note="Card payment taken by Floodman staff." if staff_keyed else "Customer paid through the secure Floodman payment page.",
        actor_id=actor_id,
        processor_payment=processor_payment,
        payment_metadata={
            "staff_keyed": staff_keyed,
            "customer_initiated": not staff_keyed,
            "saved_payment_method_id": (saved_card or {}).get("id"),
            "authorization_reference": str(payload.get("authorization_reference") or "").strip() or None,
        },
    )
    updated = store.record(kind + "s", str(document.get("id"))) or document
    try:
        await _send_payment_receipt(kind, updated, payment)
    except Exception:
        pass
    return {
        "ok": True,
        "payment_id": payment.get("id"),
        "processor_status": processor_payment.get("status"),
        "receipt_url": f"{settings.customer_public_url}/receipt/{document.get('public_token')}?payment={quote(str(payment.get('id') or ''))}",
        "saved_payment_method": bool(saved_card),
        "warning": save_warning or None,
        "mode": "test" if config.get("local_mock") else "live",
    }


@app.get("/office/payment-settings")
def payment_settings_page() -> HTMLResponse:
    _require("connections.manage")
    config = providers.square_payment_configuration()
    status = "TEST MODE" if config.get("local_mock") else "READY" if config.get("live") else "SETUP REQUIRED"
    status_message = (
        "Safe test payments are available. No real card will be charged."
        if config.get("local_mock")
        else "The production processor identifiers are present. Complete a small approved test before go-live."
        if config.get("live")
        else "Ask the server owner to connect the Square Sandbox before accepting card payments."
    )
    body = f"""
<div class='callout {'success' if config.get('local_mock') or config.get('live') else 'warning'}'><b>{esc(status)}:</b> {esc(status_message)}</div>
<div class='grid two'><div class='card'><div class='settings-eyebrow'>CURRENT READINESS</div><h2>Card payment connection</h2><p><b>Mode:</b> {badge(status)}</p><p><b>Environment:</b> {esc(str(config.get('environment') or 'Not configured').replace('_', ' ').title())}</p><p><b>Application:</b> {esc('Connected' if config.get('application_id') else 'Not connected')}</p><p><b>Business location:</b> {esc('Connected' if config.get('location_id') else 'Not connected')}</p><p><b>Customer payment page:</b><br><span class='mono'>{esc(settings.customer_public_url)}</span></p></div><div class='card'><div class='settings-eyebrow'>WHAT STAFF NEED TO KNOW</div><h2>Card information stays with Square</h2><p>Customers or authorized staff type card details only into Square's secure card field. Floodman keeps the payment result, amount, receipt, processor ID, card brand, and last four digits.</p><div class='callout success'><b>Never paste a card number, expiration date, or security code into notes, messages, or this settings area.</b></div></div></div>
<div class='card'><h2>Simple setup path</h2><div class='role-guide'><div><b>1. Start in test mode</b><small>Use local test mode or Square Sandbox before any production payment.</small></div><div><b>2. Server owner connects Square</b><small>The owner installs the application ID, access token, location ID, and webhook secret outside the browser.</small></div><div><b>3. Run one approved test</b><small>Verify the receipt, invoice balance, and payment record agree.</small></div><div><b>4. Approve production</b><small>Switch only after the business owner reviews the payment and refund process.</small></div></div><div class='actions'><a class='button' href='/office/payments'>Open payment records</a><a class='button secondary' href='/office/settings'>Back to settings</a></div></div>
<details class='card plain-details'><summary>Server owner instructions</summary><p>Copy <code>/home/container/config/floodman-payments.env.example</code> to <code>/home/container/config/floodman-payments.env</code>, insert reviewed Square Sandbox values, restart Floodman, and return here. Never place credentials in browser JavaScript, GitHub, chat, or screenshots.</p><p class='muted'>Required server values: application ID, server access token, location ID, and webhook signature key. This page intentionally shows only whether identifiers are present.</p></details>
"""
    return _page("Card Payment Setup", body, "payment-settings")


@app.get("/office/estimates/{estimate_id}/pdf")
def estimate_pdf(estimate_id: str) -> Response:
    _require("estimates.view")
    document = _local_record_or_404("estimates", estimate_id)
    document = _ensure_public_document("estimate", document, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    number = str(document.get("estimate_number") or estimate_id)
    return Response(_document_pdf("estimate", document), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{number}.pdf"', "Cache-Control": "no-store"})


@app.get("/office/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: str) -> Response:
    _require("invoices.view")
    document = _local_record_or_404("invoices", invoice_id)
    document = _ensure_public_document("invoice", document, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    number = str(document.get("invoice_number") or invoice_id)
    return Response(_document_pdf("invoice", document), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{number}.pdf"', "Cache-Control": "no-store"})


@app.post("/office/estimates/{estimate_id}/activate-deposit")
def activate_estimate_deposit(estimate_id: str) -> RedirectResponse:
    actor = _require("payments.manage")
    document = _local_record_or_404("estimates", estimate_id)
    values = _estimate_payment_values(document)
    if not int(values["deposit_cents"]):
        store.set_notice("This estimate does not require a deposit.")
    else:
        store.update_record("estimates", estimate_id, {"deposit_payable": True, "deposit_status": "DUE" if int(values["due_cents"]) else "PAID"}, actor_id=str(actor.get("id")))
        store.set_notice("The Floodman deposit payment page is now active.")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/payment")
async def estimate_manual_payment(estimate_id: str, amount: str = Form(...), method: str = Form(default="CASH"), reference: str = Form(default=""), note: str = Form(default=""), check_date: str = Form(default=""), bank_name: str = Form(default=""), check_status: str = Form(default="RECEIVED"), email_receipt: str = Form(default="")) -> RedirectResponse:
    actor = _require("payments.manage")
    document = _local_record_or_404("estimates", estimate_id)
    try:
        amount_cents = _parse_money(amount)
        payment = await _record_document_payment(kind="estimate", document=document, amount_cents=amount_cents, method=method, reference=reference, note=note, actor_id=str(actor.get("id")), payment_metadata={"check_date": check_date or None, "bank_name": bank_name.strip() or None, "check_status": check_status.upper() if method.upper() == "CHECK" else None})
        if email_receipt == "yes":
            await _send_payment_receipt("estimate", store.record("estimates", estimate_id) or document, payment)
        store.set_notice(f"Deposit payment of {money_cents(amount_cents)} recorded.")
    except Exception as exc:
        store.set_notice(str(exc))
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.get("/office/estimates/{estimate_id}/take-payment")
def estimate_phone_payment(estimate_id: str) -> HTMLResponse:
    _require("payments.manage")
    document = _local_record_or_404("estimates", estimate_id)
    document = _ensure_public_document("estimate", document, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    amount, maximum, payable = _payment_request_values("estimate", document)
    if not payable or maximum <= 0:
        raise HTTPException(409, "No deposit is currently due.")
    contact, _ = _document_contact_property(document)
    html_page = customer_payment_page(title="Floodman deposit by phone", reference=str(document.get("estimate_number") or estimate_id), amount_cents=amount, max_amount_cents=maximum, currency=str(document.get("currency") or "USD"), customer=contact, process_url=f"/office/estimates/{estimate_id}/card-payment", return_url=f"/office/estimates/{estimate_id}", config=providers.square_payment_configuration(), staff_keyed=True, allow_save=True, allow_partial=True)
    return HTMLResponse(html_page, headers=_payment_security_headers(allow_sdk=True))


@app.post("/office/estimates/{estimate_id}/card-payment")
async def estimate_phone_payment_process(estimate_id: str, request: Request) -> JSONResponse:
    actor = _require("payments.manage")
    document = _local_record_or_404("estimates", estimate_id)
    try:
        result = await _process_card_payment("estimate", document, await request.json(), staff_keyed=True, actor_id=str(actor.get("id")))
        return JSONResponse(result, headers=_payment_security_headers())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Payment was not completed: {exc}") from exc


@app.get("/office/invoices/{invoice_id}/take-payment")
def invoice_phone_payment(invoice_id: str) -> HTMLResponse:
    _require("payments.manage")
    document = _local_record_or_404("invoices", invoice_id)
    document = _ensure_public_document("invoice", document, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    amount, maximum, payable = _payment_request_values("invoice", document)
    if not payable or maximum <= 0:
        raise HTTPException(409, "This invoice has no balance due.")
    contact, _ = _document_contact_property(document)
    html_page = customer_payment_page(title="Floodman card payment by phone", reference=str(document.get("invoice_number") or invoice_id), amount_cents=amount, max_amount_cents=maximum, currency=str(document.get("currency") or "USD"), customer=contact, process_url=f"/office/invoices/{invoice_id}/card-payment", return_url=f"/office/invoices/{invoice_id}", config=providers.square_payment_configuration(), staff_keyed=True, allow_save=True, allow_partial=True)
    return HTMLResponse(html_page, headers=_payment_security_headers(allow_sdk=True))


@app.post("/office/invoices/{invoice_id}/card-payment")
async def invoice_phone_payment_process(invoice_id: str, request: Request) -> JSONResponse:
    actor = _require("payments.manage")
    document = _local_record_or_404("invoices", invoice_id)
    try:
        result = await _process_card_payment("invoice", document, await request.json(), staff_keyed=True, actor_id=str(actor.get("id")))
        return JSONResponse(result, headers=_payment_security_headers())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Payment was not completed: {exc}") from exc


def _customer_document_response(expected_kind: str, token: str) -> HTMLResponse:
    kind, document = _public_document(token)
    if kind != expected_kind:
        raise HTTPException(404, "Document link not found")
    body = _customer_document_body(kind, document) + _customer_conversation_body(kind, document)
    return HTMLResponse(customer_page(str(document.get("title") or "Floodman document"), body), headers=_payment_security_headers())


def _customer_document_pdf_response(expected_kind: str, token: str) -> Response:
    kind, document = _public_document(token)
    if kind != expected_kind:
        raise HTTPException(404, "Document link not found")
    number = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "Floodman")
    return Response(_document_pdf(kind, document), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{number}.pdf"', **_payment_security_headers()})


@app.get("/customer/estimate/{token}")
def customer_estimate(token: str) -> HTMLResponse:
    return _customer_document_response("estimate", token)


@app.get("/customer/invoice/{token}")
def customer_invoice(token: str) -> HTMLResponse:
    return _customer_document_response("invoice", token)


@app.post("/customer/{kind}/{token}/messages")
async def customer_message(
    kind: str,
    token: str,
    body: str = Form(...),
    request_id: str = Form(...),
    website: str = Form(default=""),
) -> Response:
    actual_kind, document = _public_document(token)
    if actual_kind != kind or kind not in {"estimate", "invoice"}:
        raise HTTPException(404, "Document link not found")
    return_url = str(document.get("public_url") or f"{settings.customer_public_url}/{kind}/{token}") + "#messages"
    if website.strip():
        return RedirectResponse(return_url, status_code=303)
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(request_id or "")):
        raise HTTPException(422, "Refresh the page and send your message again.")
    try:
        message_body = _clean_portal_message(body)
    except ValueError as exc:
        page_body = f"<div class='notice error'>{esc(exc)}</div>" + _customer_document_body(kind, document) + _customer_conversation_body(kind, document)
        return HTMLResponse(customer_page("Message not sent", page_body), status_code=422, headers=_payment_security_headers())

    thread = _customer_thread(document, kind, create=True)
    if not thread:
        raise HTTPException(409, "This customer file is not available for messaging.")
    thread_id = str(thread["id"])
    message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-customer-message:{thread_id}:{request_id}"))
    existing_message = store.record("customer_messages", message_id)
    if existing_message:
        await _notify_customer_message_staff(document, existing_message, thread_id)
        return RedirectResponse(return_url, status_code=303)

    now = datetime.now(UTC)
    recent_customer_messages = 0
    for item in _customer_thread_messages(thread_id):
        if str(item.get("sender_kind") or "").upper() != "CUSTOMER":
            continue
        try:
            created = datetime.fromisoformat(str(item.get("created_at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - created).total_seconds() <= 60:
            recent_customer_messages += 1
    if recent_customer_messages >= 5:
        raise HTTPException(429, "Please wait a moment before sending another message.")

    contact, _ = _document_contact_property(document)
    message, created = store.create_record_if_absent(
        "customer_messages",
        message_id,
        {
            "thread_id": thread_id,
            "contact_id": document.get("contact_id"),
            "property_id": document.get("property_id"),
            "document_kind": kind,
            "document_id": document.get("id"),
            "sender_kind": "CUSTOMER",
            "sender_name": _contact_display_name(contact),
            "body": message_body,
            "customer_read_at": now.isoformat(),
            "staff_read_at": None,
            "source": "FLOODMAN_CUSTOMER_PORTAL",
        },
        actor_id="customer-portal",
    )
    if created:
        store.update_record(
            "customer_threads",
            thread_id,
            {
                "status": "OPEN",
                "property_id": document.get("property_id") or thread.get("property_id"),
                "last_document_kind": kind,
                "last_document_id": document.get("id"),
                "last_message_at": message.get("created_at"),
                "last_sender_kind": "CUSTOMER",
            },
            actor_id="customer-portal",
        )
    await _notify_customer_message_staff(document, message, thread_id)
    return RedirectResponse(return_url, status_code=303)


@app.post("/customer/{kind}/{token}/messages/read")
def customer_messages_read(kind: str, token: str) -> RedirectResponse:
    actual_kind, document = _public_document(token)
    if actual_kind != kind or kind not in {"estimate", "invoice"}:
        raise HTTPException(404, "Document link not found")
    thread_id = _customer_thread_id(
        str(document.get("contact_id") or ""),
        str(document.get("property_id") or ""),
        str(document.get("id") or ""),
    )
    now = datetime.now(UTC).isoformat()
    for item in _customer_thread_messages(thread_id):
        if str(item.get("sender_kind") or "").upper() == "STAFF" and not item.get("customer_read_at"):
            store.update_record("customer_messages", str(item["id"]), {"customer_read_at": now}, actor_id="customer-portal")
    return RedirectResponse(str(document.get("public_url") or f"{settings.customer_public_url}/{kind}/{token}") + "#messages", status_code=303)


@app.get("/customer/estimate/{token}/pdf")
def customer_estimate_pdf(token: str) -> Response:
    return _customer_document_pdf_response("estimate", token)


@app.get("/customer/invoice/{token}/pdf")
def customer_invoice_pdf(token: str) -> Response:
    return _customer_document_pdf_response("invoice", token)


@app.get("/customer/pay/{token}")
def customer_pay(token: str) -> HTMLResponse:
    kind, document = _public_document(token)
    amount, maximum, payable = _payment_request_values(kind, document)
    if not payable or maximum <= 0:
        return RedirectResponse(str(document.get("public_url") or f"{settings.customer_public_url}/{kind}/{token}"), status_code=303)
    contact, _ = _document_contact_property(document)
    reference = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "")
    title = "Floodman project deposit" if kind == "estimate" else "Floodman invoice payment"
    html_page = customer_payment_page(title=title, reference=reference, amount_cents=amount, max_amount_cents=maximum, currency=str(document.get("currency") or "USD"), customer=contact, process_url=f"{settings.customer_public_url}/pay/{token}/process", return_url=str(document.get("public_url") or ""), config=providers.square_payment_configuration(), staff_keyed=False, allow_save=bool(document.get("allow_customer_to_save_card", True)), allow_partial=kind == "invoice" and str(document.get("collection_mode") or "PAYMENT_PAGE").upper() == "PAYMENT_PAGE")
    return HTMLResponse(html_page, headers=_payment_security_headers(allow_sdk=True))


@app.post("/customer/pay/{token}/process")
async def customer_pay_process(token: str, request: Request) -> JSONResponse:
    kind, document = _public_document(token)
    try:
        result = await _process_card_payment(kind, document, await request.json(), staff_keyed=False, actor_id="customer-online-payment")
        return JSONResponse(result, headers=_payment_security_headers())
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, f"Payment was not completed: {exc}") from exc


@app.get("/customer/receipt/{token}")
def customer_receipt(token: str, payment: str = "") -> HTMLResponse:
    kind, document = _public_document(token)
    record = next((item for item in store.records("payments") if str(item.get("id") or "") == str(payment or "") and (str(item.get("invoice_id") or "") == str(document.get("id") or "") or str(item.get("estimate_id") or "") == str(document.get("id") or ""))), None)
    if not record:
        raise HTTPException(404, "Receipt not found")
    contact, _ = _document_contact_property(document)
    reference = str(document.get("estimate_number") if kind == "estimate" else document.get("invoice_number") or document.get("id") or "")
    card = ""
    if record.get("last_4"):
        card = f"{esc(record.get('card_brand') or 'Card')} ending in {esc(record.get('last_4'))}"
    body = f"""<div class='card receipt hero'><span class='eyebrow' style='color:#bfe3f0'>PAYMENT RECEIPT</span><h2>{money_cents(record.get('amount_cents'))} received</h2><p>Thank you, {esc(contact.get('name') or contact.get('first_name') or 'customer')}.</p></div><div class='grid'><div class='metric'><small>Reference</small><strong>{esc(reference)}</strong></div><div class='metric'><small>Method</small><strong>{esc(str(record.get('method') or '').replace('_',' ').title())}</strong></div><div class='metric'><small>Date</small><strong>{esc(record.get('payment_date') or '')}</strong></div></div><div class='card'><h2>Payment details</h2><p><b>Amount:</b> {money_cents(record.get('amount_cents'))}</p><p><b>Confirmation:</b> {esc(record.get('processor_payment_id') or record.get('reference') or record.get('id'))}</p>{f'<p><b>Card:</b> {card}</p>' if card else ''}<div class='actions'><a class='button secondary' href='{esc(document.get('public_url') or '')}'>Return to document</a><a class='button secondary' href='{esc(document.get('public_pdf_url') or '')}' target='_blank'>Open updated PDF</a></div></div>"""
    return HTMLResponse(customer_page("Floodman payment receipt", body), headers=_payment_security_headers())


@app.get("/office/catalog")
def catalog_page(q: str = "", category: str = "") -> HTMLResponse:
    _require("estimates.view")
    query = str(q or "").strip().casefold()
    category_key = str(category or "").strip().casefold()
    all_items = store.records("catalog_items")
    if has_permission(_user(), "estimates.manage"):
        _import_bundled_roomflow_catalog(actor_id=str((_user() or {}).get("id") or "floodman-office"))
        all_items = store.records("catalog_items")
    categories = sorted({str(item.get("category") or "General Services") for item in all_items}, key=str.casefold)
    items = []
    for item in all_items:
        pricing = ((item.get("formula") or {}).get("xactimate") or {})
        searchable = " ".join([
            *(str(item.get(key) or "") for key in ("name", "description", "category", "unit", "source_provider", "source_id", "external_key")),
            *(str(pricing.get(key) or "") for key in ("code", "price_list", "market", "effective_date")),
        ]).casefold()
        if query and query not in searchable:
            continue
        if category_key and str(item.get("category") or "").casefold() != category_key:
            continue
        items.append(item)
    items.sort(key=lambda item: (item.get("active") is False, str(item.get("category") or "").casefold(), str(item.get("name") or "").casefold()))
    category_options = "".join(f"<option value='{esc(value)}' {'selected' if value.casefold() == category_key else ''}>{esc(value)}</option>" for value in categories)
    create = ""
    xactimate_import = ""
    if has_permission(_user(), "estimates.manage"):
        create = """<details class='card plain-details'><summary>Add a new service or price</summary><p class='muted'>Add something your team sells often. It will appear in office estimates and the RoomFlow scope builder.</p><form method='post' action='/office/catalog/add'><div class='form-grid three'><div class='field'><label>Service name <span class='required-mark'>Required</span></label><input name='name' maxlength='200' placeholder='Interior perimeter drainage' required><small class='field-help'>Use the name a customer will understand.</small></div><div class='field'><label>Estimate section</label><input name='category' value='General Services' maxlength='120' required><small class='field-help'>Services with the same section stay grouped together.</small></div><div class='field'><label>How it is measured</label><select name='unit'><option value='each'>Each</option><option value='LF'>Linear foot</option><option value='SF'>Square foot</option><option value='hour'>Hour</option><option value='day'>Day</option><option value='allowance'>Allowance</option></select></div><div class='field'><label>Standard unit price</label><input name='unit_price' type='number' min='0' max='9999999.99' step='0.01' value='0.00' inputmode='decimal'><small class='field-help'>Enter dollars, not cents. It can still be changed on an estimate.</small></div><div class='field checks'><label><input type='checkbox' name='taxable' value='yes'> Apply sales tax when the estimate uses tax</label></div><div class='field full'><label>Customer-facing description <span class='muted'>Optional</span></label><textarea name='description' maxlength='2000' placeholder='What is included in this service?'></textarea></div></div><button class='good' style='margin-top:12px'>Save service</button></form></details>"""
        xactimate_import = """<details class='card plain-details'><summary>Bring in licensed Xactimate pricing</summary><div class='callout'><b>Preview first, import second.</b> Floodman never changes the original file. A direct PLX upload is inspected locally, but protected XACTDOC.ZIPXML data requires a supported Xactimate conversion. A completed Floodman pricing CSV can be fully previewed and confirmed here.</div><form method='post' action='/office/catalog/import-xactimate' enctype='multipart/form-data' class='import-upload-form'><label class='file-drop-field'><span class='file-drop-icon'>⇩</span><b>Select a PLX or pricing CSV</b><small>Accepted: .plx and .csv · Maximum 25 MB · Files stay in private server storage only when a CSV preview succeeds</small><input type='file' name='pricing_file' accept='.plx,.csv,text/csv' required></label><button class='good'>Inspect and preview</button></form><div class='role-guide'><div><b>1. Try the PLX</b><small>Floodman identifies the transfer container and tells you if Xactimate conversion is required.</small></div><div><b>2. Fill the template</b><small>Use only pricing data your Xactimate license allows you to use.</small></div><div><b>3. Confirm the preview</b><small>Stable market/category/selector/activity codes update existing items without duplicates.</small></div></div><div class='actions'><a class='button secondary' href='/office/catalog/import-xactimate/template.csv'>Download pricing CSV template</a></div></details>"""
    source_labels = {
        "FLOODMAN_CUSTOM": "Added by your team",
        "ROOMFLOW_SUPABASE": "Current RoomFlow/Supabase",
        "ROOMFLOW_BUNDLED_CATALOG": "Floodman starter list",
        XACTIMATE_SOURCE_PROVIDER: "Licensed Xactimate import",
    }

    def catalog_card(item: dict[str, Any]) -> str:
        xactimate = ((item.get("formula") or {}).get("xactimate") or {})
        code = xactimate.get("code")
        effective = xactimate.get("effective_date")
        pricing_details = ""
        if code:
            pricing_details = f"<small><b>Insurance code:</b> {esc(code)}</small><small><b>Price list:</b> {esc(xactimate.get('price_list') or 'Not recorded')} · <b>Effective:</b> {esc(effective or 'Review required')}</small>"
        return f"<article class='catalog-card'><div class='catalog-source'>{esc(source_labels.get(str(item.get('source_provider') or ''), 'Floodman service'))}</div><h3>{esc(item.get('name'))}</h3><div class='catalog-price'>{money_cents(item.get('unit_price_cents'))} / {esc(item.get('unit') or 'each')}</div>{pricing_details}<small>Estimate section: {esc(item.get('default_section') or item.get('category') or 'General Services')}</small><small>{esc(item.get('description') or 'No customer description yet.')}</small><div style='margin-top:9px'>{badge('REVIEW PRICE' if item.get('review_required') else ('AVAILABLE' if item.get('active') is not False else 'HIDDEN'), 'warn' if item.get('review_required') else ('good' if item.get('active') is not False else 'neutral'))}</div></article>"

    display_limit = 200
    cards = "".join(catalog_card(item) for item in items[:display_limit]) or "<div class='callout'>No services match this search. Clear the filters, refresh the starter list, or add a service.</div>"
    result_note = f"<p class='muted'>Showing the first {display_limit} of {len(items)} matches. Search by description or insurance code to narrow the list.</p>" if len(items) > display_limit else ""
    body = f"""<div class='callout success'><b>One price list for office and field staff.</b> Choose these services while building an estimate in Floodman Office or RoomFlow. A price is a reusable starting point and can be adjusted on an individual estimate.</div>{xactimate_import}<div class='card'><div class='actions spread'><div><h2>Services &amp; Prices</h2><p class='muted'>{len(all_items)} reusable services are available. RoomFlow/Supabase and licensed pricing imports use stable source IDs, so refreshing does not create duplicates.</p></div><div class='actions'><form method='post' action='/office/catalog/import-roomflow'><button type='submit'>Refresh starter services</button></form><a class='button secondary' href='/office/roomflow?catalog_sync=1'>Pull current RoomFlow prices</a></div></div><form method='get' class='customer-searchbar'><div class='field'><label>Find a service or insurance code</label><input type='search' name='q' value='{esc(q)}' placeholder='Try WTR, drywall, waterproofing, or demolition' autocomplete='off'></div><div class='field'><label>Show section</label><select name='category'><option value=''>All sections</option>{category_options}</select></div><button>Apply filters</button></form>{result_note}<div class='catalog-grid'>{cards}</div></div>{create} """
    return _page("Services & Prices", body, "catalog")


@app.get("/office/catalog/import-xactimate/template.csv")
def download_xactimate_catalog_template() -> Response:
    _require("estimates.manage")
    return Response(
        xactimate_catalog_template(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="floodman-xactimate-pricing-template.csv"'},
    )


@app.post("/office/catalog/import-xactimate")
async def upload_xactimate_catalog(pricing_file: UploadFile = File(...)) -> RedirectResponse:
    _require("estimates.manage")
    filename = Path((pricing_file.filename or "pricing-import").replace("\\", "/")).name
    data = await pricing_file.read(XACTIMATE_MAX_UPLOAD_BYTES + 1)
    try:
        result = parse_xactimate_catalog_upload(data, filename)
    except ProtectedXactimatePlxError as exc:
        inspection = exc.inspection
        store.set_notice(
            f"PLX recognized ({inspection.member_name}, {inspection.member_size:,} bytes; file SHA-256 starts {inspection.sha256[:12]}). "
            f"{exc} The PLX was not stored or imported."
        )
        return RedirectResponse("/office/catalog", status_code=303)
    except (XactimateCatalogError, zipfile.BadZipFile) as exc:
        store.set_notice(f"Pricing file was not imported: {exc}")
        return RedirectResponse("/office/catalog", status_code=303)
    safe_filename = str(result.summary.get("source_filename") or "xactimate-pricing.csv")
    run_id = store.create_import(result.summary, result.normalized, {safe_filename: data})
    store.set_notice("Pricing worksheet validated. Review the detected line items before importing them.")
    return RedirectResponse(f"/office/imports/{run_id}", status_code=303)


@app.post("/office/catalog/add")
def add_catalog_item(name: str = Form(...), category: str = Form(default="General Services"), unit: str = Form(default="each"), unit_price: str = Form(default="0"), taxable: str = Form(default=""), description: str = Form(default="")) -> RedirectResponse:
    actor = _require("estimates.manage")
    try:
        item, created = _upsert_catalog_item({"name": name, "category": category, "default_section": category, "unit": unit, "unit_price": unit_price, "taxable": taxable == "yes", "description": description}, actor_id=str(actor.get("id")), source="FLOODMAN_CUSTOM")
        store.set_notice(f"Catalog item {'created' if created else 'updated'}: {item['name']}.")
    except ValueError as exc:
        store.set_notice(str(exc))
    return RedirectResponse("/office/catalog", status_code=303)


@app.get("/office/estimates")
async def estimates_page(q: str = "", status: str = "") -> HTMLResponse:
    _require("estimates.view")
    state = await _state_page_data()
    provider_estimates = [item for item in _rows(state.get("gauzy_invoices")) if item.get("isEstimate") is True]
    local_estimates = store.records("estimates")
    query = str(q or "").strip().casefold()
    status_key = str(status or "").strip().upper()
    rows: list[list[str]] = []
    seen: set[str] = set()
    totals = {"all": 0, "draft": 0, "sent": 0, "accepted": 0}

    for item in local_estimates + provider_estimates:
        identity = str(item.get("id") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        item_status = str(item.get("status") or "DRAFT").upper()
        contact_id = str(item.get("contact_id") or item.get("organizationContactId") or "")
        property_id = str(item.get("property_id") or "")
        customer = _contact_name(contact_id, state) or str(item.get("organizationContactName") or "")
        property_row = next((row for row in _all_property_rows(state) if str(row.get("id") or "") == property_id), None)
        property_label = _property_label(property_row or {}) if property_id else ""
        searchable = " ".join(
            str(value or "")
            for value in (
                item.get("estimate_number"), _invoice_number(item), item.get("title"), item_status,
                customer, property_label, item.get("source"), item.get("legacyEstimateId"),
            )
        ).casefold()
        if query and query not in searchable:
            continue
        if status_key and item_status != status_key:
            continue
        total = item.get("total_cents")
        if total is None:
            total = int(round(float(item.get("totalValue") or 0) * 100))
        totals["all"] += 1
        if item_status in {"DRAFT", "SENT", "VIEWED"}:
            totals["draft" if item_status == "DRAFT" else "sent"] += 1
        if item_status in {"ACCEPTED", "CONVERTED"}:
            totals["accepted"] += 1
        action = f"<a class='button small' href='/office/estimates/{esc(identity)}'>Open estimate</a>"
        if store.record("estimates", identity) and item_status in {"DRAFT", "SENT", "VIEWED"} and has_permission(_user(), "estimates.manage"):
            action += f" <a class='button secondary small' href='/office/estimates/{esc(identity)}/edit'>Continue editing</a>"
        rows.append([
            f"<b>{esc(item.get('estimate_number') or _invoice_number(item))}</b><br><small class='muted'>{esc(item.get('title') or '')}</small>",
            esc(customer), esc(property_label), badge(item_status), money_cents(total, item.get("currency") or "USD"),
            action,
        ])

    status_options = "".join(
        f"<option value='{value}' {'selected' if status_key == value else ''}>{label}</option>"
        for value, label in (("", "All statuses"), ("DRAFT", "Draft"), ("SENT", "Sent"), ("VIEWED", "Viewed"), ("ACCEPTED", "Accepted"), ("CONVERTED", "Converted"), ("VOID", "Void"))
    )
    create_action = ""
    if has_permission(_user(), "estimates.manage"):
        create_action = "<a class='button good' href='/office/estimates/new'>Create new estimate</a>"
    body = f"""
    <div class='card'><div class='actions'>{create_action}<a class='button secondary' href='/office/roomflow'>RoomFlow</a><a class='button secondary' href='/office/catalog'>Services and prices</a></div></div>
    <div class='card'><form method='get' action='/office/estimates' class='customer-searchbar estimate-index-search' data-estimate-index-search><div class='field'><label>Find an estimate</label><input type='search' name='q' value='{esc(q)}' placeholder='Number, customer, property, or title' autocomplete='off'></div><div class='field'><label>Status</label><select name='status'>{status_options}</select></div><button type='submit'>Search</button></form><p class='muted'>{totals['all']} matching estimates</p>{table(('Estimate','Customer','Property','Status','Total','Open'), rows, empty='No estimates match this search.')}</div>
    """
    return _page("Estimates", body, "estimates")


def _estimate_new_contact_fields() -> str:
    return """<div class='form-grid three'>
      <div class='field'><label>First name</label><input name='new_contact_first_name' data-new-customer-field></div>
      <div class='field'><label>Last name</label><input name='new_contact_last_name' data-new-customer-field></div>
      <div class='field'><label>Company</label><input name='new_contact_company' data-new-customer-field></div>
      <div class='field'><label>Email</label><input name='new_contact_email' type='email' data-new-customer-field></div>
      <div class='field'><label>Phone</label><input name='new_contact_phone' data-new-customer-field></div>
      <div class='field'><label>Lead source</label><input name='new_contact_lead_source' value='Floodman estimate' data-new-customer-field></div>
      <div class='field full'><label>Mailing street</label><input name='new_contact_mailing_street' data-new-customer-field></div>
      <div class='field'><label>Mailing city</label><input name='new_contact_mailing_city' data-new-customer-field></div>
      <div class='field'><label>Mailing state</label><input name='new_contact_mailing_state' value='MI' data-new-customer-field></div>
      <div class='field'><label>Mailing ZIP</label><input name='new_contact_mailing_postal_code' data-new-customer-field></div>
      <div class='field full'><label>Customer note</label><textarea name='new_contact_notes' data-new-customer-field placeholder='Initial request, referral, access details, or other customer-file note'></textarea></div>
    </div>"""


def _estimate_new_property_fields() -> str:
    return """<div class='form-grid three'>
      <div class='field'><label>Property name</label><input name='new_property_name' value='Service Property' data-new-property-field></div>
      <div class='field'><label>Property type</label><input name='new_property_type' value='Residential' data-new-property-field></div>
      <div class='field'><label>Insurance company</label><input name='new_property_insurance_company' data-new-property-field></div>
      <div class='field full'><label>Service street address</label><input name='new_property_service_street' data-new-property-field></div>
      <div class='field'><label>City</label><input name='new_property_service_city' data-new-property-field></div>
      <div class='field'><label>State</label><input name='new_property_service_state' value='MI' data-new-property-field></div>
      <div class='field'><label>ZIP</label><input name='new_property_service_postal_code' data-new-property-field></div>
      <div class='field'><label>Claim number</label><input name='new_property_claim_number' data-new-property-field></div>
      <div class='field full'><label>Property / job notes</label><textarea name='new_property_notes' data-new-property-field placeholder='Access, occupancy, insurance, inspection, or job-site notes'></textarea></div>
    </div>"""


@app.get("/office/estimates/new")
async def new_estimate_page(contact_id: str = "", property_id: str = "") -> HTMLResponse:
    actor = _require("estimates.manage")
    state = await _state_page_data()
    contact_label = _contact_name(contact_id, state) if contact_id else ""
    property_row = next((item for item in _all_property_rows(state) if str(item.get("id") or "") == property_id), None)
    property_label = _property_label(property_row or {}) if property_id else ""
    can_create_customer = has_permission(actor, "contacts.manage")
    can_create_property = has_permission(actor, "properties.manage")
    customer_create_button = "<button type='button' class='secondary' data-customer-mode-button='new'>Create new customer</button>" if can_create_customer else ""
    property_create_button = "<button type='button' class='secondary' data-property-mode-button='new'>Create new property</button>" if can_create_property else ""
    customer_new_panel = f"<div class='estimate-mode-panel' data-customer-mode-panel='new' hidden>{_estimate_new_contact_fields()}</div>" if can_create_customer else ""
    property_new_panel = f"<div class='estimate-mode-panel' data-property-mode-panel='new' hidden>{_estimate_new_property_fields()}</div>" if can_create_property else ""
    customer_mode = "existing"
    property_mode = "existing"
    body = f"""
    <div class='actions'><a class='button secondary' href='/office/estimates'>Back to estimates</a><a class='button secondary' href='/office/roomflow'>Build in RoomFlow</a></div>
    <form method='post' action='/office/estimates/add' data-estimate-workflow novalidate>
      <input type='hidden' name='customer_mode' value='{customer_mode}' data-customer-mode-value>
      <input type='hidden' name='property_mode' value='{property_mode}' data-property-mode-value>
      <section class='card estimate-workflow-step' data-workflow-step='1'><div class='estimate-step-heading'><span>1</span><div><h2>Customer</h2><p>Select an existing customer or create a new customer file without leaving the estimate.</p></div></div><div class='estimate-mode-buttons'><button type='button' class='secondary active' data-customer-mode-button='existing'>Use existing customer</button>{customer_create_button}</div><div class='estimate-mode-panel' data-customer-mode-panel='existing'>{_entity_picker(kind='contacts', name='contact_id', label='Customer', selected_id=contact_id, selected_label=contact_label, required=False)}</div>{customer_new_panel}</section>
      <section class='card estimate-workflow-step' data-workflow-step='2'><div class='estimate-step-heading'><span>2</span><div><h2>Service property</h2><p>Choose one of the customer's properties or create the job address now.</p></div></div><div class='estimate-mode-buttons'><button type='button' class='secondary active' data-property-mode-button='existing'>Use existing property</button>{property_create_button}</div><div class='estimate-mode-panel' data-property-mode-panel='existing'>{_entity_picker(kind='properties', name='property_id', label='Property / job', selected_id=property_id, selected_label=property_label, required=False, contact_source='contact_id')}</div>{property_new_panel}</section>
      <section class='card estimate-workflow-step' data-workflow-step='3'><div class='estimate-step-heading'><span>3</span><div><h2>Estimate details</h2><p>These details feed the customer view, Floodman PDF, payment plan, and project file.</p></div></div><div class='form-grid three'>
        <div class='field'><label>Estimate number</label><input name='estimate_number' value='{esc(_next_number('EST','estimates'))}' required></div>
        <div class='field two-wide'><label>Estimate title</label><input name='title' placeholder='Basement waterproofing and mold remediation' required></div>
        <div class='field full'><label>Project summary</label><textarea name='project_summary' placeholder='Plain-language explanation of the problem, recommended work, and intended result.'></textarea></div>
        <div class='field'><label>Estimated duration</label><input name='estimated_duration' placeholder='4–6 days'></div>
        <div class='field'><label>Estimate valid for</label><input type='number' name='expiration_days' min='1' max='365' value='30'></div>
        <div class='field'><label>Deposit requirement</label><select name='deposit_type'><option value='PERCENT' selected>Percentage</option><option value='FIXED'>Fixed amount</option><option value='NONE'>No deposit</option></select></div>
        <div class='field'><label>Deposit percent</label><input type='number' name='deposit_percent' min='0' max='100' step='0.01' value='50'></div>
        <div class='field'><label>Fixed deposit amount</label><input type='number' name='deposit_fixed_amount' min='0' step='0.01' value='0.00'></div>
        <div class='field'><label>Deposit becomes payable</label><select name='deposit_due_stage'><option value='AFTER_AUTHORIZATION' selected>After authorization</option><option value='IMMEDIATELY'>When estimate is sent</option></select></div>
        <div class='field full'><label>Project assumptions</label><textarea name='assumptions' placeholder='One assumption per line'></textarea></div>
        <div class='field full'><label>Not included unless listed</label><textarea name='exclusions' placeholder='One exclusion per line'></textarea></div>
        <div class='field full'><label>Customer-facing notes</label><textarea name='customer_notes' placeholder='Scheduling, access, warranty, or other notes shown with the estimate'></textarea></div>
        <div class='field full'><label>Terms and notes</label><textarea name='terms'>Payment is due upon receipt of each issued invoice. Additional work requires a signed Change Order.</textarea></div>
      </div></section>
      <section class='card estimate-workflow-step' data-workflow-step='4'><div class='estimate-step-heading'><span>4</span><div><h2>Scope and pricing</h2><p>Add headers, catalog items, custom items, quantities, descriptions, and prices.</p></div></div>{_estimate_builder_html(default_section='Waterproofing')}</section>
      <section class='card estimate-workflow-submit'><div><h2>Save the draft</h2><p class='muted'>Nothing is sent to the customer until you open the saved estimate and press Send Floodman estimate.</p></div><div class='actions'><button type='submit' class='good' data-estimate-submit>Save draft estimate</button><a class='button secondary' href='/office/estimates'>Cancel</a></div></section>
    </form>
    """
    return _page("Create Estimate", body, "estimates")


async def _create_estimate_customer(
    *, actor_id: str, first_name: str, last_name: str, company: str, email: str, phone: str,
    lead_source: str, mailing_street: str, mailing_city: str, mailing_state: str,
    mailing_postal_code: str, notes: str,
) -> tuple[dict[str, Any], list[str]]:
    _require("contacts.manage")
    first_name = first_name.strip(); last_name = last_name.strip(); company = company.strip()
    email = email.strip(); phone = phone.strip()
    name = " ".join(value for value in (first_name, last_name) if value).strip() or company
    if not name:
        raise ValueError("Enter a customer name or company.")
    if not email and not phone:
        raise ValueError("Enter at least an email address or phone number for the new customer.")
    warnings: list[str] = []
    provider_id = None
    try:
        created = await providers.create_contact({"name": name, "primaryEmail": email or None, "primaryPhone": phone or None, "notes": notes.strip(), "contactType": "CLIENT"})
        provider_id = created.get("id")
    except Exception as exc:
        warnings.append(f"ERP customer bridge: {exc}")
    record = store.create_record("contacts", {
        "id": provider_id or str(uuid.uuid4()), "first_name": first_name, "last_name": last_name,
        "name": name, "company": company, "email": email, "phone": phone,
        "lead_source": lead_source.strip() or "Floodman estimate", "notes": notes.strip(),
        "mailing_street": mailing_street.strip(), "mailing_city": mailing_city.strip(),
        "mailing_state": mailing_state.strip() or "MI", "mailing_postal_code": mailing_postal_code.strip(),
        "provider_id": provider_id, "status": "ACTIVE", "source": "ESTIMATE_WORKFLOW",
    }, actor_id=actor_id)
    try:
        await _sync_contact_to_real_gauzy(record, actor_id)
    except Exception as exc:
        warnings.append(f"Floodman ERP customer sync: {exc}")
    return record, warnings


async def _create_estimate_property(
    *, actor_id: str, contact_id: str, name: str, property_type: str, service_street: str,
    service_city: str, service_state: str, service_postal_code: str,
    insurance_company: str, claim_number: str, notes: str,
) -> tuple[dict[str, Any], list[str]]:
    _require("properties.manage")
    if not service_street.strip() or not service_city.strip() or not service_postal_code.strip():
        raise ValueError("Enter the service street, city, state, and ZIP for the new property.")
    record = store.create_record("properties", {
        "contact_id": contact_id, "name": name.strip() or "Service Property",
        "property_name": name.strip() or "Service Property", "property_type": property_type.strip() or "Residential",
        "service_street": service_street.strip(), "service_city": service_city.strip(),
        "service_state": service_state.strip() or "MI", "service_postal_code": service_postal_code.strip(),
        "insurance_company": insurance_company.strip(), "claim_number": claim_number.strip(),
        "notes": notes.strip(), "status": "ACTIVE", "source": "ESTIMATE_WORKFLOW",
    }, actor_id=actor_id)
    warnings: list[str] = []
    try:
        await _sync_property_to_real_gauzy(record, actor_id)
    except Exception as exc:
        warnings.append(f"Floodman ERP property sync: {exc}")
    return record, warnings


@app.post("/office/estimates/add")
async def add_estimate(
    contact_id: str = Form(default=""), property_id: str = Form(default=""),
    customer_mode: str = Form(default="existing"), property_mode: str = Form(default="existing"),
    new_contact_first_name: str = Form(default=""), new_contact_last_name: str = Form(default=""),
    new_contact_company: str = Form(default=""), new_contact_email: str = Form(default=""),
    new_contact_phone: str = Form(default=""), new_contact_lead_source: str = Form(default=""),
    new_contact_mailing_street: str = Form(default=""), new_contact_mailing_city: str = Form(default=""),
    new_contact_mailing_state: str = Form(default="MI"), new_contact_mailing_postal_code: str = Form(default=""),
    new_contact_notes: str = Form(default=""),
    new_property_name: str = Form(default="Service Property"), new_property_type: str = Form(default="Residential"),
    new_property_service_street: str = Form(default=""), new_property_service_city: str = Form(default=""),
    new_property_service_state: str = Form(default="MI"), new_property_service_postal_code: str = Form(default=""),
    new_property_insurance_company: str = Form(default=""), new_property_claim_number: str = Form(default=""),
    new_property_notes: str = Form(default=""),
    estimate_number: str = Form(...), title: str = Form(...), estimate_payload: str = Form(...),
    project_summary: str = Form(default=""), estimated_duration: str = Form(default=""),
    assumptions: str = Form(default=""), exclusions: str = Form(default=""), customer_notes: str = Form(default=""),
    deposit_type: str = Form(default="PERCENT"), deposit_percent: float = Form(default=50.0),
    deposit_fixed_amount: str = Form(default="0"), deposit_due_stage: str = Form(default="AFTER_AUTHORIZATION"),
    expiration_days: int = Form(default=30), terms: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("estimates.manage")
    actor_id = str(actor.get("id") or "floodman-office")
    state = await _state_page_data()
    notices: list[str] = []
    customer_mode = str(customer_mode or "existing").lower()
    property_mode = str(property_mode or "existing").lower()
    try:
        if customer_mode == "new":
            contact, warnings = await _create_estimate_customer(
                actor_id=actor_id, first_name=new_contact_first_name, last_name=new_contact_last_name,
                company=new_contact_company, email=new_contact_email, phone=new_contact_phone,
                lead_source=new_contact_lead_source, mailing_street=new_contact_mailing_street,
                mailing_city=new_contact_mailing_city, mailing_state=new_contact_mailing_state,
                mailing_postal_code=new_contact_mailing_postal_code, notes=new_contact_notes,
            )
            contact_id = str(contact["id"]); notices.append(f"Customer {contact['name']} created."); notices.extend(warnings)
            property_mode = "new"
        else:
            if not contact_id:
                raise ValueError("Choose an existing customer or create a new one.")
            _ensure_local_contact(contact_id, state)

        if property_mode == "new":
            property_record, warnings = await _create_estimate_property(
                actor_id=actor_id, contact_id=contact_id, name=new_property_name,
                property_type=new_property_type, service_street=new_property_service_street,
                service_city=new_property_service_city, service_state=new_property_service_state,
                service_postal_code=new_property_service_postal_code,
                insurance_company=new_property_insurance_company, claim_number=new_property_claim_number,
                notes=new_property_notes,
            )
            property_id = str(property_record["id"]); notices.append(f"Property {_property_label(property_record)} created."); notices.extend(warnings)
        else:
            if not property_id:
                raise ValueError("Choose an existing property or create a new one.")
            selected_property = next((item for item in _all_property_rows(state) if str(item.get("id") or "") == property_id), None)
            if not selected_property or str(selected_property.get("contact_id") or "") != contact_id:
                raise ValueError("Choose a property that belongs to the selected customer.")

        sections, items, total_cents = normalize_document_payload(estimate_payload, title=title)
        items = _save_custom_catalog_lines(items, actor_id)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/estimates/new", status_code=303)

    contact_name = _contact_name(contact_id)
    provider_id = None
    provider_items = _provider_items_with_headers(sections, items)
    try:
        created = await providers.create_invoice({
            "invoiceNumber": len(store.records("estimates")) + 1001,
            "invoiceDate": datetime.now(UTC).isoformat(), "dueDate": datetime.now(UTC).isoformat(),
            "status": "DRAFT", "totalValue": total_cents / 100, "currency": "USD", "paid": False,
            "terms": terms.strip(), "organizationContactId": contact_id, "organizationContactName": contact_name,
            "toContactId": contact_id, "isEstimate": True, "isAccepted": False, "invoiceType": "DETAILED_ITEMS",
        }, provider_items)
        provider_id = created.get("id")
    except Exception as exc:
        notices.append(f"Floodman ERP bridge: {exc}")

    record = store.create_record("estimates", {
        "id": provider_id or str(uuid.uuid4()), "estimate_number": estimate_number.strip(),
        "contact_id": contact_id, "property_id": property_id, "title": title.strip(), "status": "DRAFT",
        "currency": "USD", "sections": sections, "line_items": items, "total_cents": total_cents,
        "summary": project_summary.strip(), "project_summary": project_summary.strip(),
        "estimated_duration": estimated_duration.strip(), "assumptions": assumptions.strip(),
        "exclusions": exclusions.strip(), "customer_notes": customer_notes.strip(),
        "deposit_type": deposit_type.upper() if deposit_type.upper() in {"PERCENT", "FIXED", "NONE"} else "PERCENT",
        "deposit_percent": max(0, min(100, float(deposit_percent))),
        "deposit_fixed_cents": _parse_money(deposit_fixed_amount) if str(deposit_fixed_amount).strip() else 0,
        "deposit_due_stage": deposit_due_stage.upper() if deposit_due_stage.upper() in {"AFTER_AUTHORIZATION", "IMMEDIATELY"} else "AFTER_AUTHORIZATION",
        "deposit_payable": deposit_due_stage.upper() == "IMMEDIATELY", "deposit_paid_cents": 0,
        "deposit_balance_cents": 0, "expiration_days": max(1, int(expiration_days)),
        "terms": terms.strip(), "provider_id": provider_id, "source": "FLOODMAN_ESTIMATE_WORKSPACE",
    }, actor_id=actor_id)
    deposit_values = _estimate_payment_values(record)
    record = store.update_record("estimates", str(record["id"]), {"deposit_balance_cents": int(deposit_values["deposit_cents"])}, actor_id=actor_id)
    record = _ensure_public_document("estimate", record, actor_id=actor_id)
    notice = f"Estimate {record['estimate_number']} created as a draft for {contact_name} at {_property_label(store.record('properties', property_id) or {})}."
    if notices:
        notice += " " + " ".join(notices)
    try:
        external = await _sync_financial_to_real_gauzy("estimate", record, actor_id, is_estimate=True)
        if external:
            notice += " Synced to Floodman ERP under the property project."
    except Exception as exc:
        notice += f" Floodman ERP sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/estimates/{record['id']}", status_code=303)


@app.get("/office/estimates/{estimate_id}")
async def estimate_detail(estimate_id: str) -> HTMLResponse:
    _require("estimates.view")
    estimate = store.record("estimates", estimate_id)
    if not estimate:
        state = await _state_page_data()
        estimate = next((item for item in _rows(state.get("gauzy_invoices")) if str(item.get("id")) == estimate_id and item.get("isEstimate") is True), None)
    if not estimate:
        raise HTTPException(404, "Estimate not found")
    total_cents = estimate.get("total_cents")
    if total_cents is None:
        total_cents = int(round(float(estimate.get("totalValue") or 0) * 100))
    if store.record("estimates", estimate_id):
        estimate = _ensure_public_document("estimate", estimate, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    deposit_values = _estimate_payment_values(estimate)
    actions = "<a class='button secondary' href='/office/estimates'>Back</a>"
    actions += f"<a class='button secondary' href='/office/estimates/{esc(estimate_id)}/pdf' target='_blank'>Open Floodman PDF</a>"
    if estimate.get("public_url"):
        actions += f"<a class='button secondary' href='{esc(estimate.get('public_url'))}' target='_blank'>Open customer view</a>"
    if store.record("estimates", estimate_id) and has_permission(_user(), "estimates.manage"):
        actions += f"<a class='button secondary' href='/office/estimates/{esc(estimate_id)}/edit'>Manage estimate</a><form method='post' action='/office/estimates/{esc(estimate_id)}/send'><button>Send Floodman estimate</button></form>"
        if not deposit_values["payable"] and int(deposit_values["deposit_cents"]):
            actions += f"<form method='post' action='/office/estimates/{esc(estimate_id)}/activate-deposit'><button class='secondary'>Make deposit payable</button></form>"
    if has_permission(_user(), "invoices.manage") and not estimate.get("converted_invoice_id"):
        actions += f"<form method='post' action='/office/estimates/{esc(estimate_id)}/convert'><button class='good'>Convert to due-now invoice</button></form>"
    contact_id = str(estimate.get('contact_id') or estimate.get('organizationContactId') or '')
    property_id = str(estimate.get('property_id') or '')
    customer_name = _contact_name(contact_id) or str(estimate.get('organizationContactName') or '')
    property_record = store.record('properties', property_id) if property_id else None
    customer_link = f"<a href='/office/contacts/{esc(contact_id)}'>{esc(customer_name)}</a>" if contact_id else esc(customer_name)
    property_link = f"<a href='/office/properties/{esc(property_id)}'>{esc(_property_label(property_record or {}))}</a>" if property_id else 'Not linked'
    body = f"""<div class='actions'>{actions}</div><div class='grid two' style='margin-top:15px'><div class='card'><h2>{esc(estimate.get('estimate_number') or _invoice_number(estimate))}</h2><p><b>Customer:</b> {customer_link}</p><p><b>Service property:</b> {property_link}</p><p><b>Title:</b> {esc(estimate.get('title') or '')}</p><p><b>Status:</b> {badge(estimate.get('status'))}</p><p><b>Total:</b> {money_cents(total_cents)}</p><p><b>Estimated duration:</b> {esc(estimate.get('estimated_duration') or 'Not entered')}</p><p><b>Terms:</b> {esc(estimate.get('terms') or '')}</p></div>
    <div class='card'><h2>Payment plan</h2><p><b>Deposit requested:</b> {money_cents(deposit_values['deposit_cents'])}</p><p><b>Deposit paid:</b> {money_cents(deposit_values['paid_cents'])}</p><p><b>Deposit due:</b> {money_cents(deposit_values['due_cents'])}</p><p><b>Payable:</b> {badge('READY' if deposit_values['payable'] else 'AFTER AUTHORIZATION')}</p><p><b>Expiration:</b> {esc(estimate.get('expiration_days') or '')} days</p><p><b>Converted invoice:</b> {esc(estimate.get('converted_invoice_id') or 'Not yet')}</p><p><b>Scope headers:</b> {len(group_document_lines(estimate))}</p></div></div>
    <div class='card'><h2>Project details</h2><p><b>Summary:</b> {esc(estimate.get('project_summary') or estimate.get('summary') or 'Not entered')}</p><div class='grid two'><div><h3>Assumptions</h3><p class='preline'>{esc(estimate.get('assumptions') or 'Not entered')}</p></div><div><h3>Not included unless listed</h3><p class='preline'>{esc(estimate.get('exclusions') or 'Not entered')}</p></div></div><p><b>Customer-facing notes:</b> {esc(estimate.get('customer_notes') or 'Not entered')}</p></div><div class='card'><h2>Grouped scope</h2>{_render_grouped_document_lines(estimate)}</div>{f"<div class='card'><h2>Take or record deposit</h2><div class='actions'><a class='button good' href='/office/estimates/{esc(estimate_id)}/take-payment'>Card by phone</a><a class='button secondary' href='{esc(estimate.get('public_pay_url') or '')}' target='_blank'>Open customer payment page</a></div><hr><form method='post' action='/office/estimates/{esc(estimate_id)}/payment'><div class='form-grid three'><div class='field'><label>Amount</label><input name='amount' value='{int(deposit_values['due_cents'])/100:.2f}' required></div><div class='field'><label>Method</label><select name='method'><option value='CASH'>Cash</option><option value='CHECK'>Check</option><option value='ACH'>Bank transfer / ACH</option><option value='EXTERNAL_CARD'>Card processed elsewhere</option><option value='OTHER'>Other</option></select></div><div class='field'><label>Reference / check number</label><input name='reference'></div><div class='field'><label>Check date</label><input type='date' name='check_date'></div><div class='field'><label>Bank name</label><input name='bank_name'></div><div class='field'><label>Check status</label><select name='check_status'><option>RECEIVED</option><option>DEPOSITED</option><option>CLEARED</option><option>RETURNED</option></select></div><div class='field full'><label>Note</label><input name='note'></div><div class='field full checks'><label><input type='checkbox' name='email_receipt' value='yes' checked> Email a Floodman receipt</label></div></div><button style='margin-top:12px'>Record deposit</button></form></div>" if has_permission(_user(), 'payments.manage') and int(deposit_values['due_cents']) > 0 and deposit_values['payable'] else ''}"""
    return _page(str(estimate.get("estimate_number") or "Estimate"), body, "estimates")


@app.post("/office/estimates/{estimate_id}/convert")
async def convert_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("invoices.manage")
    estimate = store.record("estimates", estimate_id)
    if not estimate:
        raise HTTPException(404, "Estimate not found")
    if (
        str(estimate.get("publication_status") or "").upper() == "UNPUBLISHED"
        or str(estimate.get("pricing_status") or "PRICED").upper() != "PRICED"
        or int(estimate.get("total_cents") or 0) <= 0
    ):
        store.set_notice("This call-intake draft needs verified measurements, line items, and pricing before conversion.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    existing = estimate.get("converted_invoice_id")
    if existing:
        return RedirectResponse(f"/office/invoices/{existing}", status_code=303)
    now = datetime.now(UTC).isoformat()
    invoice = store.create_record("invoices", {
        "invoice_number": _next_number("INV", "invoices"),
        "contact_id": estimate.get("contact_id"),
        "property_id": estimate.get("property_id"),
        "estimate_id": estimate_id,
        "title": estimate.get("title"),
        "status": "SENT",
        "currency": "USD",
        "sections": estimate.get("sections") or document_payload(estimate).get("sections") or [],
        "line_items": estimate.get("line_items") or [],
        "total_cents": int(estimate.get("total_cents") or 0),
        "paid_cents": int(estimate.get("deposit_paid_cents") or 0),
        "balance_cents": max(0, int(estimate.get("total_cents") or 0) - int(estimate.get("deposit_paid_cents") or 0)),
        "issued_at": now,
        "due_at": now,
        "terms": estimate.get("terms") or "Payment due upon receipt.",
    }, actor_id=actor.get("id"))
    invoice = _ensure_public_document("invoice", invoice, actor_id=str(actor.get("id")))
    for deposit_payment in [p for p in store.records("payments") if str(p.get("estimate_id") or "") == estimate_id and not p.get("invoice_id")]:
        store.update_record("payments", str(deposit_payment["id"]), {"invoice_id": invoice["id"], "note": (str(deposit_payment.get("note") or "") + " Deposit applied to invoice.").strip()}, actor_id=str(actor.get("id")))
    store.update_record("estimates", estimate_id, {"status": "ACCEPTED", "converted_invoice_id": invoice["id"]}, actor_id=actor.get("id"))
    notice = f"Invoice {invoice['invoice_number']} issued and due immediately."
    try:
        external = await _sync_financial_to_real_gauzy(
            "invoice", invoice, str(actor.get("id")), is_estimate=False
        )
        if external:
            notice += " Synced to Floodman ERP under the property project."
    except Exception as exc:
        notice += f" Floodman ERP sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/invoices/{invoice['id']}", status_code=303)


@app.get("/office/invoices")
async def invoices_page(contact_id: str = "", property_id: str = "") -> HTMLResponse:
    _require("invoices.view")
    state = await _state_page_data()
    local_invoices = store.records("invoices")
    provider_invoices = [item for item in _rows(state.get("gauzy_invoices")) if item.get("isEstimate") is not True]
    rows = []
    seen = set()
    for item in local_invoices + provider_invoices:
        identity = str(item.get("id") or "")
        if identity in seen:
            continue
        seen.add(identity)
        total_cents = item.get("total_cents")
        paid_cents = item.get("paid_cents")
        balance_cents = item.get("balance_cents")
        if total_cents is None:
            total_cents = int(round(float(item.get("totalValue") or 0) * 100))
        if paid_cents is None:
            paid_cents = int(round(float(item.get("alreadyPaid") or 0) * 100))
        if balance_cents is None:
            balance_cents = int(round(float(item.get("amountDue") or max(0, total_cents - paid_cents)) * 100)) if item.get("amountDue") is not None else max(0, total_cents - paid_cents)
        rows.append([
            f"<a href='/office/invoices/{esc(identity)}'>{esc(item.get('invoice_number') or _invoice_number(item))}</a>",
            esc(_contact_name(str(item.get("contact_id") or item.get("organizationContactId") or ""), state) or item.get("organizationContactName") or ""),
            badge(item.get("status")), money_cents(balance_cents, item.get("currency") or "USD"), esc(item.get("due_at") or item.get("dueDate") or ""),
        ])
    create = ""
    if has_permission(_user(), "invoices.manage"):
        create = f"""<details class='card'><summary>Create invoice</summary><form method='post' action='/office/invoices/add' style='margin-top:15px'><div class='form-grid three'>
        {_entity_picker(kind='contacts', name='contact_id', label='Customer', selected_id=contact_id, selected_label=_contact_name(contact_id, state) if contact_id else '', required=True)}{_entity_picker(kind='properties', name='property_id', label='Property / job', selected_id=property_id, selected_label=_property_label(next((i for i in _all_property_rows(state) if str(i.get('id')) == property_id), {})) if property_id else '', contact_source='contact_id')}
        <div class='field'><label>Invoice number</label><input name='invoice_number' value='{esc(_next_number('INV','invoices'))}' required></div>
        <div class='field full'><label>Invoice title</label><input name='title' placeholder='Final service invoice' required></div>
        <div class='field full'>{_estimate_builder_html(default_section='Completed Scope')}</div>
        <div class='field'><label>Status</label><select name='status'><option>SENT</option><option>DRAFT</option></select></div>
        <div class='field'><label>Delivery</label><select name='send_channel'><option value='FLOODMAN_EMAIL'>Floodman email with PDF and online payment</option><option value='CREATE_ONLY'>Create only</option></select></div>
        <div class='field'><label>Online payment</label><select name='collection_mode'><option value='PAYMENT_PAGE' selected>Allow full or partial online payment</option><option value='FULL_BALANCE'>Require full balance online</option><option value='OFFLINE_ONLY'>Cash, check, or staff-entered payment only</option></select></div>
        <div class='field full checks'><label><input type='checkbox' name='allow_customer_to_save_card' value='yes'> Let the customer choose to save the payment method for future separately authorized charges.</label></div>
        <div class='field full'><label>Terms</label><textarea name='terms'>Payment is due upon receipt.</textarea></div></div><button style='margin-top:12px'>Create invoice</button></form></details>"""
    reconcile_button = ""
    if has_permission(_user(), "payments.manage"):
        reconcile_button = "<form method='post' action='/office/square/reconcile'><input type='hidden' name='next_path' value='/office/invoices'><button class='secondary'>Refresh payment status</button></form>"
    body = f"{create}<div class='card'><div class='actions spread'><h2>Invoices</h2>{reconcile_button}</div>{table(('Invoice','Customer','Status','Balance','Due'), rows)}</div>"
    return _page("Invoices", body, "invoices")


@app.post("/office/invoices/add")
async def add_invoice(
    contact_id: str = Form(...), property_id: str = Form(default=""), invoice_number: str = Form(...), title: str = Form(...), estimate_payload: str = Form(...), status: str = Form(default="SENT"), send_channel: str = Form(default="FLOODMAN_EMAIL"), collection_mode: str = Form(default="PAYMENT_PAGE"), allow_customer_to_save_card: str = Form(default=""), terms: str = Form(default="Payment is due upon receipt."),
) -> RedirectResponse:
    actor = _require("invoices.manage")
    state = await _state_page_data()
    _ensure_local_contact(contact_id, state)
    if property_id:
        selected_property = next((item for item in _all_property_rows(state) if str(item.get("id") or "") == property_id), None)
        if not selected_property or str(selected_property.get("contact_id") or "") != contact_id:
            store.set_notice("Choose a property that belongs to the selected customer.")
            return RedirectResponse("/office/invoices", status_code=303)
    try:
        sections, items, total_cents = normalize_document_payload(estimate_payload, title=title)
        items = _save_custom_catalog_lines(items, str(actor.get("id")))
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/invoices", status_code=303)
    now = datetime.now(UTC).isoformat()
    desired_status = status.upper()
    record = store.create_record("invoices", {
        "invoice_number": invoice_number.strip(), "contact_id": contact_id, "property_id": property_id or None, "title": title.strip(), "status": "DRAFT", "currency": "USD", "sections": sections, "line_items": items, "total_cents": total_cents, "paid_cents": 0, "balance_cents": total_cents, "issued_at": None, "due_at": None, "terms": terms.strip(), "send_channel": send_channel.upper(), "collection_mode": collection_mode.upper(), "allow_customer_to_save_card": allow_customer_to_save_card == "yes",
    }, actor_id=actor.get("id"))
    record = _ensure_public_document("invoice", record, actor_id=str(actor.get("id")))
    notice = f"Invoice {record['invoice_number']} created as a draft."
    if desired_status == "SENT" and send_channel.upper() == "FLOODMAN_EMAIL":
        try:
            record, recipient = await _send_customer_document("invoice", record, actor_id=str(actor.get("id")))
            notice = f"Invoice {record['invoice_number']} sent to {recipient}. It is due immediately and includes the secure Floodman payment page."
        except Exception as exc:
            notice = f"Invoice remains a draft because delivery failed: {exc}"
    try:
        external = await _sync_financial_to_real_gauzy("invoice", store.record("invoices", str(record["id"])) or record, str(actor.get("id")), is_estimate=False)
        if external:
            notice += " Synced to Floodman ERP under the property project."
    except Exception as exc:
        notice += f" Floodman ERP sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/invoices/{record['id']}", status_code=303)


@app.get("/office/invoices/{invoice_id}")
async def invoice_detail(invoice_id: str) -> HTMLResponse:
    _require("invoices.view")
    invoice = store.record("invoices", invoice_id)
    if not invoice:
        state = await _state_page_data()
        invoice = next((item for item in _rows(state.get("gauzy_invoices")) if str(item.get("id")) == invoice_id and item.get("isEstimate") is not True), None)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    total_cents = invoice.get("total_cents")
    if total_cents is None:
        total_cents = int(round(float(invoice.get("totalValue") or 0) * 100))
    paid_cents = invoice.get("paid_cents")
    if paid_cents is None:
        paid_cents = int(round(float(invoice.get("alreadyPaid") or 0) * 100))
    balance_cents = invoice.get("balance_cents")
    if balance_cents is None:
        balance_cents = max(0, total_cents - paid_cents)
    payments = [item for item in store.records("payments") if str(item.get("invoice_id")) == invoice_id]
    if store.record("invoices", invoice_id):
        invoice = _ensure_public_document("invoice", invoice, actor_id=str((_user() or {}).get("id") or "floodman-system"))
    payment_form = ""
    if has_permission(_user(), "payments.manage") and balance_cents > 0:
        payment_form = f"""<div class='card'><h2>Take or record a payment</h2><div class='actions'><a class='button good' href='/office/invoices/{esc(invoice_id)}/take-payment'>Card by phone</a><a class='button secondary' href='{esc(invoice.get('public_pay_url') or '')}' target='_blank'>Open customer payment page</a></div><hr><form method='post' action='/office/invoices/{esc(invoice_id)}/payment'><div class='form-grid three'><div class='field'><label>Amount</label><input name='amount' value='{balance_cents/100:.2f}' required></div><div class='field'><label>Method</label><select name='method'><option value='CASH'>Cash</option><option value='CHECK'>Check</option><option value='ACH'>Bank transfer / ACH</option><option value='EXTERNAL_CARD'>Card processed elsewhere</option><option value='OTHER'>Other</option></select></div><div class='field'><label>Reference / check number</label><input name='reference'></div><div class='field'><label>Check date</label><input type='date' name='check_date'></div><div class='field'><label>Bank name</label><input name='bank_name'></div><div class='field'><label>Check status</label><select name='check_status'><option>RECEIVED</option><option>DEPOSITED</option><option>CLEARED</option><option>RETURNED</option></select></div><div class='field full'><label>Note</label><input name='note'></div><div class='field full checks'><label><input type='checkbox' name='email_receipt' value='yes' checked> Email a Floodman receipt to the customer</label></div></div><button style='margin-top:12px'>Record payment</button></form></div>"""
    manage = f"<a class='button secondary' href='/office/invoices/{esc(invoice_id)}/edit'>Manage invoice</a>" if store.record("invoices", invoice_id) and has_permission(_user(), "invoices.manage") else ""
    public_actions = f"<a class='button secondary' href='/office/invoices/{esc(invoice_id)}/pdf' target='_blank'>Open Floodman PDF</a>" + (f"<a class='button secondary' href='{esc(invoice.get('public_url'))}' target='_blank'>Open customer view</a>" if invoice.get('public_url') else "")
    body = f"""<div class='actions'><a class='button secondary' href='/office/invoices'>Back</a><a class='button' href='/office/documents?invoice_id={quote(invoice_id)}'>Send related document</a>{public_actions}{manage}</div>
    <div class='grid' style='margin-top:15px'><div class='card metric'><small>Total</small><strong>{money_cents(total_cents)}</strong></div><div class='card metric'><small>Paid</small><strong>{money_cents(paid_cents)}</strong></div><div class='card metric'><small>Balance</small><strong>{money_cents(balance_cents)}</strong></div><div class='card metric'><small>Status</small><strong>{badge(invoice.get('status'))}</strong></div></div>
    <div class='card'><h2>{esc(invoice.get('invoice_number') or _invoice_number(invoice))}</h2><p><b>Customer:</b> {esc(_contact_name(str(invoice.get('contact_id') or invoice.get('organizationContactId') or '')) or invoice.get('organizationContactName'))}</p><p><b>Issued:</b> {esc(invoice.get('issued_at') or invoice.get('invoiceDate') or '')}</p><p><b>Due:</b> {esc(invoice.get('due_at') or invoice.get('dueDate') or '')}</p><p><b>Online payment:</b> {f"<a href='{esc(invoice.get('public_pay_url'))}' target='_blank'>Open secure Floodman payment</a>" if invoice.get('public_pay_url') and balance_cents else 'Paid or not enabled'}</p><p><b>Terms:</b> {esc(invoice.get('terms') or '')}</p></div>
    <div class='card'><h2>Grouped charges</h2>{_render_grouped_document_lines(invoice)}</div>{payment_form}
    <div class='card'><h2>Payments</h2>{table(('Date','Amount','Method','Reference'), [[esc(i.get('payment_date')), money_cents(i.get('amount_cents')), badge(str(i.get('method') or '').replace('_',' ')), esc(i.get('reference') or i.get('processor_payment_id'))] for i in payments])}</div>"""
    return _page(str(invoice.get("invoice_number") or "Invoice"), body, "invoices")


@app.post("/office/invoices/{invoice_id}/payment")
async def invoice_payment(
    invoice_id: str,
    amount: str = Form(...),
    method: str = Form(default="OTHER"),
    reference: str = Form(default=""),
    note: str = Form(default=""),
    check_date: str = Form(default=""),
    bank_name: str = Form(default=""),
    check_status: str = Form(default="RECEIVED"),
    email_receipt: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("payments.manage")
    invoice = store.record("invoices", invoice_id)
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    try:
        amount_cents = _parse_money(amount)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)
    balance = int(invoice.get("balance_cents") or 0)
    if amount_cents <= 0 or amount_cents > balance:
        store.set_notice(f"Payment must be between $0.01 and {money_cents(balance)}.")
        return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)
    payment = await _record_document_payment(
        kind="invoice",
        document=invoice,
        amount_cents=amount_cents,
        method=method,
        reference=reference,
        note=note,
        actor_id=str(actor.get("id")),
        payment_metadata={
            "check_date": check_date or None,
            "bank_name": bank_name.strip() or None,
            "check_status": check_status.upper() if method.upper() == "CHECK" else None,
            "email_receipt": email_receipt == "yes",
        },
    )
    if email_receipt == "yes":
        try:
            await _send_payment_receipt("invoice", store.record("invoices", invoice_id) or invoice, payment)
        except Exception:
            pass
    notice = f"Payment of {money_cents(amount_cents)} recorded."
    try:
        external_invoice = store.external_mapping("gauzy", f"invoice:{invoice_id}")
        if not external_invoice:
            external_invoice = await _sync_financial_to_real_gauzy(
                "invoice", invoice, str(actor.get("id")), is_estimate=False
            )
        context = await providers.gauzy_context()
        external_contact = store.external_mapping("gauzy", f"contact:{invoice.get('contact_id')}")
        project_id = store.external_mapping("gauzy", f"property:{invoice.get('property_id')}") if invoice.get("property_id") else None
        created = await providers.full_gauzy_create_payment(
            payment,
            context,
            invoice_id=str(external_invoice),
            contact_id=external_contact,
            project_id=project_id,
        )
        external_payment = str(created.get("id") or "")
        if external_payment:
            store.set_external_mapping("gauzy", f"payment:{payment['id']}", external_payment)
            store.update_record("payments", str(payment["id"]), {"full_gauzy_id": external_payment}, actor_id=str(actor.get("id")))
            notice += " Synced to Floodman ERP."
    except Exception as exc:
        notice += f" Floodman ERP payment sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)


@app.get("/office/payments")
async def payments_page() -> HTMLResponse:
    _require("payments.view")
    state = await _state_page_data()
    payments = store.records("payments") + _rows(state.get("gauzy_payments"))
    seen: set[str] = set()
    rows = []
    for item in payments:
        identity = str(item.get("id") or item.get("providerReference") or item.get("reference") or "")
        if identity in seen:
            continue
        seen.add(identity)
        amount_cents = item.get("amount_cents")
        if amount_cents is None:
            amount_cents = int(round(float(item.get("amount") or 0) * 100))
        rows.append([
            esc(item.get("payment_date") or item.get("paymentDate") or item.get("paid_at") or ""),
            money_cents(amount_cents, item.get("currency") or "USD"),
            badge(item.get("status") or item.get("providerStatus") or "RECORDED"),
            esc(item.get("method") or item.get("paymentMethod") or item.get("payment_method") or ""),
            esc(item.get("reference") or item.get("providerReference") or item.get("provider_reference") or item.get("legacyPaymentId") or item.get("legacy_payment_id") or identity),
            esc(item.get("note") or ""),
        ])
    body = f"<div class='card'><h2>Payment ledger</h2>{table(('Date','Amount','Status','Method','Reference','Note'), rows)}</div>"
    return _page("Payments", body, "payments")



# ---------------------------------------------------------------------------
# Integrated RoomFlow workspace
# ---------------------------------------------------------------------------

def _roomflow_clean(value: Any, limit: int = 5000) -> str:
    return str(value or "").strip()[:limit]


def _roomflow_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _roomflow_decimal(value: Any, default: Decimal = Decimal("1")) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
    return result


def _roomflow_contact_name(customer: dict[str, Any]) -> tuple[str, str, str]:
    first = _roomflow_clean(customer.get("first_name") or customer.get("firstName"), 100)
    last = _roomflow_clean(customer.get("last_name") or customer.get("lastName"), 100)
    name = _roomflow_clean(customer.get("name") or " ".join(part for part in (first, last) if part), 220)
    if not first and name:
        pieces = name.split(None, 1)
        first = pieces[0]
        last = pieces[1] if len(pieces) > 1 else "Customer"
    if not first:
        first = "Floodman"
    if not last:
        last = "Customer"
    return first, last, name or f"{first} {last}"


def _roomflow_address(property_data: dict[str, Any]) -> dict[str, str]:
    nested = property_data.get("service_address") if isinstance(property_data.get("service_address"), dict) else {}
    return {
        "street": _roomflow_clean(nested.get("street") or property_data.get("street") or property_data.get("service_street"), 200),
        "street2": _roomflow_clean(nested.get("street2") or property_data.get("street2") or property_data.get("service_street2"), 200),
        "city": _roomflow_clean(nested.get("city") or property_data.get("city") or property_data.get("service_city"), 100),
        "state": _roomflow_clean(nested.get("state") or property_data.get("state") or property_data.get("service_state") or "MI", 50),
        "postal_code": _roomflow_clean(nested.get("postal_code") or nested.get("postalCode") or property_data.get("postal_code") or property_data.get("service_postal_code"), 20),
        "country": _roomflow_clean(nested.get("country") or property_data.get("country") or "US", 2).upper() or "US",
    }


def _roomflow_property_label(record: dict[str, Any]) -> str:
    address = _roomflow_address(record)
    location = ", ".join(part for part in (address["street"], address["city"], " ".join(part for part in (address["state"], address["postal_code"]) if part)) if part)
    return _roomflow_clean(record.get("name") or record.get("property_name") or location or "Service property", 220)


def _roomflow_find_property(contact_id: str, property_data: dict[str, Any], workspace_id: str = "") -> dict[str, Any] | None:
    requested = _roomflow_clean(property_data.get("property_id") or property_data.get("id"), 100)
    if requested:
        item = store.record("properties", requested)
        if (
            item
            and str(item.get("contact_id") or "") == contact_id
            and str(item.get("workspace_id") or "") in {"", workspace_id}
        ):
            return item
    address = _roomflow_address(property_data)
    key = "|".join((address["street"], address["city"], address["state"], address["postal_code"])).lower()
    if not key.replace("|", ""):
        return None
    for item in store.records("properties"):
        if str(item.get("contact_id") or "") != contact_id:
            continue
        if str(item.get("workspace_id") or "") not in {"", workspace_id}:
            continue
        current = _roomflow_address(item)
        current_key = "|".join((current["street"], current["city"], current["state"], current["postal_code"])).lower()
        if current_key == key:
            return item
    return None


@app.get("/office/roomflow")
def roomflow_workspace(job_id: str = "") -> HTMLResponse:
    user = _require("estimates.view")
    _, selected_workspace_id, active_workspace = _browser_roomflow_workspace_context(user)
    jobs = [
        item
        for item in store.records("roomflow_jobs")
        if str(item.get("workspace_id") or "") == selected_workspace_id
    ]
    selected_job_id = str(job_id or "").strip()
    if not any(str(item.get("id") or "") == selected_job_id for item in jobs):
        selected_job_id = ""
    roomflow_job_query = f"&amp;job_id={quote(selected_job_id, safe='')}" if selected_job_id else ""
    roomflow_fullscreen_query = f"?job_id={quote(selected_job_id, safe='')}" if selected_job_id else ""
    cards = []
    for item in jobs[:12]:
        customer_id = str(item.get("contact_id") or "")
        property_id = str(item.get("property_id") or "")
        estimate_id = str(item.get("estimate_id") or "")
        customer = store.record("contacts", customer_id) or {}
        property_record = store.record("properties", property_id) or {}
        links = []
        if customer_id:
            links.append(f"<a href='/office/contacts/{esc(customer_id)}'>Customer file</a>")
        if property_id:
            links.append(f"<a href='/office/properties/{esc(property_id)}'>Property</a>")
        if estimate_id:
            links.append(f"<a href='/office/estimates/{esc(estimate_id)}'>Estimate</a>")
        cards.append(
            "<article class='roomflow-history-card'>"
            f"<b>{esc(item.get('job_name') or item.get('roomflow_job_id') or 'RoomFlow job')}</b>"
            f"<small>{esc(_contact_label(customer) if customer else 'Customer not linked')} · {esc(_roomflow_property_label(property_record) if property_record else 'Property not linked')}</small>"
            f"<small>{esc(item.get('estimate_number') or '')} · {badge(item.get('status') or 'SYNCED')}</small>"
            f"<div class='actions' style='margin-top:9px'><a href='/office/roomflow?job_id={quote(str(item.get('id') or ''), safe='')}'>Open in RoomFlow</a> · {' · '.join(links)}</div>"
            "</article>"
        )
    history = "".join(cards) or "<p class='muted'>No RoomFlow estimates have been saved into Floodman yet.</p>"
    import_action = ""
    if has_permission(user, "imports.manage"):
        import_action = "<a class='button secondary' href='/office/roomflow/import'>Bring in old RoomFlow data</a>"
    body = f"""
<div class='callout success'><b>No separate RoomFlow account is needed.</b> Your ERP sign-in already opens the <b>{esc(active_workspace.get('name') or 'Floodman')}</b> company workspace. RoomFlow saves to the same customer, property, and estimate files used by the office.</div>
<div class='role-guide'><div><b>1. Choose customer</b><small>Open Customer &amp; job file, then search by name, phone, email, or address.</small></div><div><b>2. Choose property</b><small>Select that customer's service address so the job stays on the right file.</small></div><div><b>3. Sketch and price</b><small>Draw the layout, then add services from the shared Services &amp; Prices list.</small></div><div><b>4. Save to Floodman</b><small>Save the draft. Re-saving updates the same estimate instead of making a duplicate.</small></div></div>
<div class='card roomflow-workspace-card'>
  <div class='roomflow-toolbar'><div class='roomflow-toolbar-copy'><b>Floodman RoomFlow Estimator</b><small>Same customer files, properties, estimates, and staff permissions.</small></div><div class='actions'>{import_action}<a class='button secondary' href='/office/catalog'>Services &amp; prices</a><a class='button secondary' href='/roomflow/{roomflow_fullscreen_query}' target='_blank'>Open full screen</a><a class='button' href='/office/estimates'>View estimates</a></div></div>
  <iframe class='roomflow-frame' src='/roomflow/?embedded=1{roomflow_job_query}' title='Floodman RoomFlow Estimator' allow='camera; fullscreen; clipboard-write'></iframe>
</div>
<div class='card'><h2>Recent RoomFlow saves</h2><div class='roomflow-history-grid'>{history}</div></div>
"""
    return _page("RoomFlow Estimator", body, "roomflow")


@app.get("/office/roomflow/import")
def roomflow_supabase_import_page() -> HTMLResponse:
    _require("imports.manage")
    history_rows = []
    for item in store.records("roomflow_imports")[:25]:
        counts = item.get("counts") or {}
        record_total = sum(int(value or 0) for value in counts.values() if isinstance(value, (int, float)))
        history_rows.append([
            esc(str(item.get("started_at") or item.get("created_at") or "")[:19].replace("T", " ")),
            badge(item.get("status") or "UNKNOWN"),
            esc(item.get("email_hint") or "Hidden"),
            esc(record_total),
            esc(item.get("error") or ""),
        ])
    body = f"""
<div class='callout success'><b>This is a one-time bridge for an older RoomFlow cloud account.</b> Current staff use their normal Floodman ERP sign-in. Use this only when you need companies, jobs, customers, properties, layouts, or catalog items that still exist in the original RoomFlow Supabase project.</div>
<div class='role-guide'><div><b>1. Enter the old sign-in</b><small>Use the email and password that worked in the original RoomFlow account.</small></div><div><b>2. Floodman reads approved records</b><small>The password is used for this request only and is never written to the Office store.</small></div><div><b>3. Matching records update</b><small>Stable Supabase source IDs update earlier imports instead of intentionally duplicating them.</small></div></div>
<div class='card'><h2>Bring in old RoomFlow data</h2><form method='post' action='/office/roomflow/import' autocomplete='off'><div class='form-grid'><div class='field'><label>Original RoomFlow email</label><input type='email' name='email' autocomplete='username' required></div><div class='field'><label>Original RoomFlow password</label><input type='password' name='password' autocomplete='current-password' required><small class='field-help'>Floodman clears this form value and does not save the password.</small></div></div><div class='actions' style='margin-top:14px'><button class='good'>Start secure import</button><a class='button secondary' href='/office/roomflow'>Cancel</a></div></form></div>
<details class='card plain-details'><summary>Previous RoomFlow import attempts</summary>{table(('Started','Result','Account','Records processed','Message'), history_rows, 'No old RoomFlow imports have been run.')}</details>
<div class='callout warning'><b>Measured-layout rule:</b> Floodman keeps genuine captured layouts when the source provides them. A missing layout stays marked for field capture; the import never invents a diagram.</div>
"""
    return _page("Bring In Old RoomFlow Data", body, "roomflow")


@app.post("/office/roomflow/import")
def run_roomflow_supabase_import(email: str = Form(...), password: str = Form(...)) -> RedirectResponse:
    actor = _require("imports.manage")
    try:
        result = import_roomflow_supabase(
            store,
            email=email,
            password=password,
            actor_id=str(actor.get("id") or ""),
            supabase_url=DEFAULT_ROOMFLOW_SUPABASE_URL,
            supabase_anon_key=DEFAULT_ROOMFLOW_SUPABASE_ANON_KEY,
        )
        counts = result.get("counts") or {}
        store.set_notice(
            "Old RoomFlow import completed. "
            f"{len(result.get('workspaces') or [])} company workspaces are available; "
            f"{int(counts.get('jobs') or counts.get('roomflow_jobs') or 0)} jobs were processed."
        )
    except RoomFlowSupabaseError as exc:
        store.set_notice(str(exc))
    finally:
        password = ""
    return RedirectResponse("/office/roomflow/import", status_code=303)


@app.get("/office/api/roomflow/jobs")
def roomflow_jobs_api(limit: int = 50) -> dict[str, Any]:
    user = _require("estimates.view")
    _, selected_workspace_id, active_workspace = _browser_roomflow_workspace_context(user)
    safe_limit = max(1, min(int(limit or 50), 200))
    all_jobs = [
        item
        for item in store.records("roomflow_jobs")
        if str(item.get("workspace_id") or "") == selected_workspace_id
    ]
    items = []
    for job in all_jobs[:safe_limit]:
        row = dict(job)
        row.pop("snapshot", None)
        items.append(row)
    return {
        "items": items,
        "count": len(all_jobs),
        "selected_workspace_id": selected_workspace_id,
        "active_workspace": workspace_public(active_workspace),
    }


@app.get("/office/api/roomflow/auth-check", response_class=Response)
def roomflow_auth_check() -> Response:
    user = _user()
    if not user:
        return Response(status_code=401, headers={"Cache-Control": "no-store"})
    if not has_permission(user, "estimates.view"):
        return Response(status_code=403, headers={"Cache-Control": "no-store"})
    return Response(status_code=204)


@app.get("/office/api/roomflow/context")
def roomflow_context_api() -> dict[str, Any]:
    user = _require("estimates.view")
    workspaces, selected_workspace_id, active_workspace = _browser_roomflow_workspace_context(user)
    return {
        "release": "4.7.3",
        "timezone": store.profile().get("timezone") or "America/Detroit",
        "user": {"id": user.get("id"), "name": user.get("name"), "email": user.get("email")},
        "workspaces": [workspace_public(record) for record in workspaces],
        "selected_workspace_id": selected_workspace_id,
        "active_workspace": workspace_public(active_workspace),
        "counts": {
            "contacts": len(store.records("contacts")),
            "properties": len(store.records("properties")),
            "estimates": len(store.records("estimates")),
            "roomflow_jobs": len(store.records("roomflow_jobs")),
        },
    }


def _browser_roomflow_workspace_context(
    user: dict[str, Any],
    preferred_workspace_id: str = "",
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    actor_id = str(user.get("id") or "")
    workspaces = ensure_roomflow_workspaces(store, actor_id=actor_id)
    selected_id = selected_roomflow_workspace_id(
        store,
        actor_id,
        preferred_workspace_id=preferred_workspace_id,
        actor_id=actor_id,
    )
    active = next(
        (record for record in workspaces if str(record.get("id") or "") == selected_id),
        workspaces[0],
    )
    return workspaces, selected_id, active


def _call_intake_public(record: dict[str, Any]) -> dict[str, Any]:
    """Return the authenticated staff card without provider payloads or secrets."""

    intake_id = str(record.get("id") or record.get("intake_id") or "")
    customer_id = str(record.get("customer_id") or "")
    property_id = str(record.get("property_id") or "")
    estimate_id = str(record.get("estimate_id") or "")
    task = store.record("tasks", str(record.get("task_id") or "")) or {}
    return {
        "id": intake_id,
        "workspace_id": record.get("workspace_id"),
        "status": record.get("status") or "ACTIVE",
        "review_status": record.get("review_status") or "PROJECTED",
        "review_reasons": list(record.get("review_reasons") or []),
        "event_type": record.get("event_type"),
        "provider_call_id": record.get("provider_call_id"),
        "event_sequence": int(record.get("event_sequence") or 0),
        "occurred_at": record.get("occurred_at"),
        "started_at": record.get("started_at"),
        "ended_at": record.get("ended_at"),
        "caller": dict(record.get("caller") or {}),
        "property": dict(record.get("property") or {}),
        "service_reason": record.get("service_reason") or "",
        "summary": record.get("summary") or "",
        "requested_services": list(record.get("requested_services") or []),
        "urgency": record.get("urgency") or "NORMAL",
        "appointment": dict(record.get("appointment") or {}),
        "consent": dict(record.get("consent") or {}),
        "transcript_available": bool(record.get("transcript_available")),
        "failure_reason": record.get("failure_reason") or "",
        "assigned_employee": {
            "id": task.get("assigned_user_id") or task.get("assigned_to"),
            "name": task.get("assigned_to_name") or "Unassigned",
        },
        "gauzy_contact_id": record.get("gauzy_contact_id"),
        "gauzy_project_id": record.get("gauzy_project_id"),
        "links": {
            "customer": f"/office/contacts/{customer_id}" if customer_id else "",
            "property": f"/office/properties/{property_id}" if property_id else "",
            "roomflow": f"/office/roomflow?job_id={quote(str(record.get('roomflow_job_id') or ''), safe='')}" if record.get("roomflow_job_id") else "",
            "job": f"/office/roomflow?job_id={quote(str(record.get('roomflow_job_id') or ''), safe='')}" if record.get("job_id") and record.get("roomflow_job_id") else "",
            "estimate": f"/office/estimates/{estimate_id}" if estimate_id else "",
            "task": "/office/tasks" if record.get("task_id") else "",
            "appointment": f"/office/calls/{intake_id}#appointment" if record.get("appointment_id") else "",
            "gauzy": settings.gauzy_hub_url if record.get("gauzy_contact_id") or record.get("gauzy_project_id") else "",
        },
        "updated_at": record.get("updated_at"),
    }


def _call_intakes_for_user(user: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    user_id = str(user.get("id") or "")
    workspaces = ensure_roomflow_workspaces(store, actor_id=user_id)
    valid_ids = {str(value.get("id") or "") for value in workspaces}
    selection = next(
        (value for value in store.records("roomflow_workspace_selections") if str(value.get("user_id") or "") == user_id),
        None,
    )
    workspace_id = str((selection or {}).get("workspace_id") or "")
    if workspace_id not in valid_ids:
        workspace_id = str(workspaces[0]["id"])
    values = [
        record for record in store.records("call_intakes")
        if str(record.get("workspace_id") or "") == workspace_id
    ]
    return values, workspace_id


def _detroit_time(value: Any) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        local = parsed.astimezone(ZoneInfo("America/Detroit"))
        return f"{local.strftime('%b')} {local.day}, {local.year} {local.strftime('%I:%M %p').lstrip('0')} ET"
    except (ValueError, TypeError):
        return ""


@app.get("/office/calls")
def call_intake_queue() -> HTMLResponse:
    user = _require("call_intakes.view")
    values, _ = _call_intakes_for_user(user)
    rows = []
    for record in values:
        caller = dict(record.get("caller") or {})
        name = str(caller.get("name") or "").strip() or "Incoming caller"
        rows.append([
            esc(_detroit_time(record.get("occurred_at") or record.get("updated_at"))),
            f"<a href='/office/calls/{esc(record.get('id'))}'><b>{esc(name)}</b></a><br><span class='muted'>{esc(caller.get('phone_e164') or caller.get('phone') or '')}</span>",
            badge(record.get("status") or "ACTIVE"),
            badge(record.get("review_status") or "PROJECTED"),
            esc(record.get("service_reason") or "Details still being collected"),
            f"<a class='button small secondary' href='/office/calls/{esc(record.get('id'))}'>Open</a>",
        ])
    body = (
        "<div class='callout success'><b>Live call intake is connected.</b> Signed provider events update this durable queue and the on-screen call card. Dismissing a card never removes the intake.</div>"
        + "<div class='actions' style='margin-bottom:14px'><button type='button' class='secondary' data-enable-call-notifications>Enable browser notifications</button></div>"
        + f"<div class='card'><h2>Incoming and recent calls</h2>{table(('Time','Caller','Call','Review','Reason','Action'), rows, 'No calls are in this workspace yet.')}</div>"
    )
    return _page("AI Call Intake", body, "calls")


@app.get("/office/calls/{intake_id}")
def call_intake_detail(intake_id: str) -> HTMLResponse:
    user = _require("call_intakes.view")
    values, _ = _call_intakes_for_user(user)
    record = next((value for value in values if str(value.get("id") or "") == intake_id), None)
    if not record:
        raise HTTPException(404, "Call intake not found")
    item = _call_intake_public(record)
    caller = item["caller"]
    prop = item["property"]
    link_buttons = "".join(
        f"<a class='button secondary' href='{esc(url)}'>{esc(label)}</a>"
        for label, url in (("Customer", item["links"]["customer"]), ("Property", item["links"]["property"]),
                           ("RoomFlow job", item["links"]["roomflow"]), ("Estimate draft", item["links"]["estimate"]),
                           ("Follow-up task", item["links"]["task"]), ("Appointment", item["links"]["appointment"]),
                           ("Floodman ERP", item["links"]["gauzy"]))
        if url
    )
    address = ", ".join(value for value in (
        str(prop.get("street") or ""), str(prop.get("city") or ""),
        str(prop.get("state") or ""), str(prop.get("postal_code") or ""),
    ) if value)
    reviews = "".join(f"<li>{esc(str(reason).replace('_', ' ').title())}</li>" for reason in item["review_reasons"])
    body = f"""
<div class='actions'><a class='button secondary' href='/office/calls'>Back to call queue</a>{link_buttons}</div>
<div class='grid two' style='margin-top:16px'>
  <section class='card'><h2>Caller</h2><p><b>{esc(caller.get('name') or 'Incoming caller')}</b><br>{esc(caller.get('phone_e164') or caller.get('phone') or 'Phone unavailable')}<br>{esc(caller.get('email') or 'Email unavailable')}</p><p>{badge(item['status'])} {badge(item['review_status'])}</p><small>{esc(_detroit_time(item.get('occurred_at')))}</small></section>
  <section class='card'><h2>Service property</h2><p>{esc(address or 'Address still being collected')}</p><p>{esc(prop.get('property_type') or 'Property type not confirmed')}</p></section>
</div>
<section class='card'><h2>Call summary</h2><p>{esc(item['summary'] or item['service_reason'] or 'The assistant is still collecting details.')}</p><div class='pill-list'>{''.join(badge(value) for value in item['requested_services'])}</div><p><b>Urgency:</b> {esc(item['urgency'])} · <b>Transcript:</b> {'Available from the approved provider reference' if item['transcript_available'] else 'Not available'}</p></section>
<section id='appointment' class='card'><h2>Follow-up and appointment</h2><p><b>Assigned employee:</b> {esc(item['assigned_employee']['name'])}</p><p><b>Preferred time:</b> {esc(item['appointment'].get('requested_window') or 'Not provided')} · <b>Confirmed:</b> {'Yes' if item['appointment'].get('confirmed') else 'No — staff confirmation required'}</p><p><b>Provider call reference:</b> <span class='mono'>{esc(item.get('provider_call_id') or '')}</span></p><p><b>Consent:</b> SMS {esc(item['consent'].get('sms_status') or 'UNKNOWN')} · Email {esc(item['consent'].get('email_status') or 'UNKNOWN')}</p></section>
{f"<section class='card warning'><h2>Human review needed</h2><ul>{reviews}</ul></section>" if reviews else ''}
<section class='card'><h2>Financial safety</h2><p>This intake can prepare an unpublished estimate draft, but it cannot invent measurements or prices, send an estimate, accept it, or charge a customer.</p></section>
"""
    return _page("Call Intake", body, "calls")


@app.get("/office/api/call-intakes/latest")
def latest_call_intake() -> dict[str, Any]:
    user = _require("call_intakes.view")
    values, workspace_id = _call_intakes_for_user(user)
    return {"item": _call_intake_public(values[0]) if values else None, "workspace_id": workspace_id}


@app.get("/office/api/call-intakes/item/{intake_id}")
def call_intake_api(intake_id: str) -> dict[str, Any]:
    user = _require("call_intakes.view")
    values, _ = _call_intakes_for_user(user)
    record = next((value for value in values if str(value.get("id") or "") == intake_id), None)
    if not record:
        raise HTTPException(404, "Call intake not found")
    return _call_intake_public(record)


@app.get("/office/api/call-intakes/events")
async def call_intake_events(request: Request) -> StreamingResponse:
    user = _require("call_intakes.view")
    user_id = str(user.get("id") or "")
    last_event_id = str(request.headers.get("last-event-id") or "")

    async def stream():
        nonlocal last_event_id
        while True:
            if await request.is_disconnected():
                return
            current_user = store.get_user(user_id)
            if not current_user or not has_permission(current_user, "call_intakes.view"):
                return
            values, _ = _call_intakes_for_user(current_user)
            if values:
                item = _call_intake_public(values[0])
                event_id = f"{item['id']}:{item['event_sequence']}"
                if event_id != last_event_id:
                    last_event_id = event_id
                    yield f"id: {event_id}\nevent: call-intake\ndata: {json.dumps(item, separators=(',', ':'), default=str)}\n\n"
            else:
                yield ": waiting for a call intake\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.get("/office/api/roomflow/workspaces")
def browser_roomflow_workspaces_api() -> dict[str, Any]:
    user = _require("estimates.view")
    workspaces, selected_id, active = _browser_roomflow_workspace_context(user)
    return {
        "items": [workspace_public(record) for record in workspaces],
        "selected_workspace_id": selected_id,
        "active_workspace": workspace_public(active),
    }


@app.post("/office/api/roomflow/workspaces")
async def browser_create_roomflow_workspace_api(request: Request) -> dict[str, Any]:
    user = _require("estimates.manage")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="RoomFlow sent invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="RoomFlow workspace payload must be an object.")
    actor_id = str(user.get("id") or "")
    try:
        workspace = create_roomflow_workspace(
            store,
            name=str(payload.get("name") or ""),
            timezone=str(payload.get("timezone") or store.profile().get("timezone") or "America/Detroit"),
            user_id=actor_id,
            actor_id=actor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    workspaces, selected_id, active = _browser_roomflow_workspace_context(user, str(workspace["id"]))
    return {
        "workspace": workspace_public(workspace),
        "workspaces": [workspace_public(record) for record in workspaces],
        "selected_workspace_id": selected_id,
        "active_workspace": workspace_public(active),
    }


@app.post("/office/api/roomflow/workspaces/{workspace_id}/select")
def browser_select_roomflow_workspace_api(workspace_id: str) -> dict[str, Any]:
    user = _require("estimates.view")
    actor_id = str(user.get("id") or "")
    try:
        workspace = select_roomflow_workspace(store, actor_id, workspace_id, actor_id=actor_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RoomFlow workspace not found") from exc
    workspaces, selected_id, active = _browser_roomflow_workspace_context(user, workspace_id)
    return {
        "workspace": workspace_public(workspace),
        "workspaces": [workspace_public(record) for record in workspaces],
        "selected_workspace_id": selected_id,
        "active_workspace": workspace_public(active),
    }


def _roomflow_formatted_address(address: dict[str, Any]) -> str:
    street = _roomflow_clean(address.get("street"), 200)
    street2 = _roomflow_clean(address.get("street2"), 200)
    city = _roomflow_clean(address.get("city"), 100)
    state_value = _roomflow_clean(address.get("state"), 50)
    postal = _roomflow_clean(address.get("postal_code") or address.get("postalCode"), 20)
    locality = ", ".join(value for value in (city, " ".join(value for value in (state_value, postal) if value)) if value)
    return ", ".join(value for value in (street, street2, locality) if value)


def _roomflow_property_payload(record: dict[str, Any]) -> dict[str, Any]:
    address = _roomflow_address(record)
    address["formatted"] = _roomflow_formatted_address(address)
    property_id = str(record.get("id") or "")
    return {
        "id": property_id,
        "contact_id": str(record.get("contact_id") or ""),
        "name": _roomflow_property_label(record),
        "property_type": str(record.get("property_type") or ""),
        "claim_number": str(record.get("claim_number") or ""),
        "insurer": str(record.get("insurance_company") or record.get("insurer") or ""),
        "address": address,
        "url": f"/office/properties/{property_id}" if property_id else "/office/properties",
    }


def _roomflow_note_payload(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(note.get("id") or ""),
        "body": str(note.get("body") or note.get("note") or ""),
        "category": str(note.get("note_type") or note.get("category") or "GENERAL").upper(),
        "pinned": bool(note.get("pinned")),
        "author_name": str(note.get("created_by_name") or note.get("author_name") or "Floodman staff"),
        "created_at": str(note.get("created_at") or ""),
    }


def _roomflow_open_balance(contact_id: str, state: dict[str, Any]) -> int:
    merged: dict[str, dict[str, Any]] = {}
    for item in _rows(state.get("gauzy_invoices")) + store.records("invoices"):
        item_contact = str(item.get("contact_id") or item.get("organizationContactId") or "")
        if item_contact != contact_id or item.get("isEstimate") is True:
            continue
        identity = str(item.get("id") or item.get("invoice_number") or item.get("invoiceNumber") or uuid.uuid4())
        merged[identity] = dict(item)
    total = 0
    for item in merged.values():
        status = str(item.get("status") or "").upper()
        if status in {"PAID", "VOID", "CANCELED", "CANCELLED", "REFUNDED"}:
            continue
        if item.get("balance_cents") is not None:
            total += max(0, _roomflow_int(item.get("balance_cents"), 0))
        else:
            try:
                total += max(0, int(round(float(item.get("amountDue") or item.get("amount_due") or 0) * 100)))
            except (TypeError, ValueError):
                pass
    return total


@app.get("/office/api/roomflow/customers/{contact_id}")
async def roomflow_customer_api(contact_id: str) -> dict[str, Any]:
    user = _require("contacts.view")
    state = await _state_page_data()
    contact = next((item for item in _all_contact_rows(state) if str(item.get("id") or "") == contact_id), None)
    if not contact:
        raise HTTPException(status_code=404, detail="Customer not found")
    local = store.record("contacts", contact_id) or contact
    _, workspace_id, _ = _browser_roomflow_workspace_context(user)
    if str(local.get("workspace_id") or "") not in {"", workspace_id}:
        raise HTTPException(status_code=404, detail="Customer not found")
    mailing = {
        "street": str(local.get("mailing_street") or local.get("street") or ""),
        "street2": str(local.get("mailing_street2") or local.get("street2") or ""),
        "city": str(local.get("mailing_city") or local.get("city") or ""),
        "state": str(local.get("mailing_state") or local.get("state") or ""),
        "postal_code": str(local.get("mailing_postal_code") or local.get("postal_code") or ""),
        "formatted": _contact_address(local),
    }
    properties = [
        _roomflow_property_payload(item)
        for item in _all_property_rows(state)
        if str(item.get("contact_id") or "") == contact_id
        and str(item.get("workspace_id") or "") in {"", workspace_id}
    ]
    notes = sorted(_contact_notes(contact_id), key=lambda item: str(item.get("created_at") or ""), reverse=True)
    customer = {
        "id": contact_id,
        "name": _contact_label(contact),
        "company": str(local.get("company") or ""),
        "email": str(local.get("primaryEmail") or local.get("email") or contact.get("primaryEmail") or contact.get("email") or ""),
        "phone": str(local.get("primaryPhone") or local.get("phone") or contact.get("primaryPhone") or contact.get("phone") or ""),
        "status": str(local.get("status") or contact.get("status") or "ACTIVE"),
        "tags": list(local.get("tags") or []),
        "mailing_address": mailing,
        "open_balance_cents": _roomflow_open_balance(contact_id, state),
        "url": f"/office/contacts/{contact_id}",
    }
    return {"customer": customer, "properties": properties, "notes": [_roomflow_note_payload(item) for item in notes]}


@app.get("/office/api/roomflow/properties/{property_id}")
async def roomflow_property_api(property_id: str) -> dict[str, Any]:
    user = _require("properties.view")
    state = await _state_page_data()
    record = next((item for item in _all_property_rows(state) if str(item.get("id") or "") == property_id), None)
    _, workspace_id, _ = _browser_roomflow_workspace_context(user)
    if not record or str(record.get("workspace_id") or "") not in {"", workspace_id}:
        raise HTTPException(status_code=404, detail="Property not found")
    return {"property": _roomflow_property_payload(record)}


@app.post("/office/api/roomflow/customers/{contact_id}/notes")
async def roomflow_customer_note_api(contact_id: str, request: Request) -> dict[str, Any]:
    actor = _require("notes.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    if str(contact.get("workspace_id") or "") not in {"", workspace_id}:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Note payload must be valid JSON") from exc
    body = _roomflow_clean((payload or {}).get("body"), 10000)
    if not body:
        raise HTTPException(status_code=422, detail="Enter a note before saving")
    category = _roomflow_clean((payload or {}).get("category") or "JOB", 40).upper()
    store.create_record("notes", {
        "entity_type": "CONTACT",
        "entity_id": contact_id,
        "note_type": category,
        "body": body,
        "pinned": bool((payload or {}).get("pinned")),
        "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
        "source": "ROOMFLOW",
    }, actor_id=str(actor.get("id")))
    notes = sorted(_contact_notes(contact_id), key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"notes": [_roomflow_note_payload(item) for item in notes]}


@app.post("/office/api/roomflow/customers/{contact_id}/tags")
async def roomflow_customer_tags_api(contact_id: str, request: Request) -> dict[str, Any]:
    actor = _require("contacts.manage")
    contact = _ensure_local_contact(contact_id, await _state_page_data())
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    if str(contact.get("workspace_id") or "") not in {"", workspace_id}:
        raise HTTPException(status_code=404, detail="Customer not found")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Tag payload must be valid JSON") from exc
    raw_tags = (payload or {}).get("tags") or []
    if isinstance(raw_tags, str):
        raw_tags = re.split(r"[,\n;]+", raw_tags)
    if not isinstance(raw_tags, list):
        raise HTTPException(status_code=422, detail="Tags must be a list or comma-separated text")
    tags: list[str] = []
    seen: set[str] = set()
    for raw in raw_tags:
        value = _roomflow_clean(raw, 60)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            tags.append(value)
        if len(tags) >= 30:
            break
    updated = store.update_record("contacts", str(contact["id"]), {"tags": tags}, actor_id=str(actor.get("id")))
    return {"tags": list(updated.get("tags") or [])}




ROOMFLOW_SNAPSHOT_KEYS = {
    "schemaVersion", "currentStep", "guidedStep3Mode", "currentLevelId", "levels",
    "rooms", "walls", "roomConnections", "doors", "windows", "openings", "stairs",
    "floorHatches", "utilities", "sumpPumps", "dehumidifiers", "dischargeLines",
    "interiorPipes", "stanchions", "mainBeams", "capturedMeasurements", "costing",
    "createdTimestamp", "updatedTimestamp", "revisionNumber", "leadIntake",
    "currentJobName", "jobId", "syncState", "floodmanContactId", "floodmanPropertyId",
    "floodmanEstimateId", "floodmanEstimateUrl", "floodmanLink", "floodmanRoomFlowJobId", "captureSchemaVersion", "captureRevision",
}


def _roomflow_snapshot(value: Any) -> tuple[dict[str, Any], str, int]:
    if not isinstance(value, dict):
        return {}, "", 0
    clean = {key: value[key] for key in ROOMFLOW_SNAPSHOT_KEYS if key in value}
    try:
        encoded = json.dumps(clean, separators=(",", ":"), sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=422, detail="RoomFlow job snapshot could not be serialized") from exc
    if len(encoded) > 8 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="RoomFlow job snapshot exceeds the 8 MB limit")
    return json.loads(encoded.decode("utf-8")), hashlib.sha256(encoded).hexdigest(), len(encoded)


@app.get("/office/api/roomflow/jobs/{job_id}")
def roomflow_job_detail_api(job_id: str) -> dict[str, Any]:
    user = _require("estimates.view")
    _, selected_workspace_id, _ = _browser_roomflow_workspace_context(user)
    job = store.record("roomflow_jobs", job_id)
    if not job or str(job.get("workspace_id") or "") != selected_workspace_id:
        raise HTTPException(status_code=404, detail="RoomFlow job not found")
    return {"job": job}


def _capture_error(exc: Exception) -> None:
    if isinstance(exc, CaptureOperationNotFound):
        raise HTTPException(status_code=404, detail=str(exc).strip("'")) from exc
    if isinstance(exc, CaptureOperationConflict):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _capture_json(request: Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Capture payload must be valid JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Capture payload must be an object")
    return value


@app.get("/office/api/roomflow/jobs/{job_id}/capture/rooms")
def roomflow_capture_rooms_api(job_id: str) -> dict[str, Any]:
    actor = _require("estimates.view")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    try:
        return {"schemaVersion": 2, "items": roomflow_capture_service.list_rooms(workspace_id=workspace_id, job_id=job_id)}
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.get("/office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
def roomflow_capture_room_api(job_id: str, room_id: str) -> dict[str, Any]:
    actor = _require("estimates.view")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    try:
        return roomflow_capture_service.get_room(workspace_id=workspace_id, job_id=job_id, room_id=room_id)
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.post("/office/api/roomflow/jobs/{job_id}/capture/rooms")
async def create_roomflow_capture_room_api(job_id: str, request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    payload = await _capture_json(request)
    room = payload.get("room") if isinstance(payload.get("room"), dict) else payload
    try:
        return roomflow_capture_service.apply(
            action="CREATE",
            operation_id=str(payload.get("operationId") or ""),
            workspace_id=workspace_id,
            job_id=job_id,
            actor_id=str(actor.get("id") or ""),
            room_id=str(payload.get("roomId") or room.get("roomId") or room.get("id") or ""),
            expected_revision=int(payload.get("expectedRevision") or 0),
            room=room,
        )
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.put("/office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
async def update_roomflow_capture_room_api(job_id: str, room_id: str, request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    payload = await _capture_json(request)
    room = payload.get("room") if isinstance(payload.get("room"), dict) else payload
    try:
        return roomflow_capture_service.apply(
            action="UPDATE",
            operation_id=str(payload.get("operationId") or ""),
            workspace_id=workspace_id,
            job_id=job_id,
            actor_id=str(actor.get("id") or ""),
            room_id=room_id,
            expected_revision=int(payload.get("expectedRevision") or 0),
            room=room,
        )
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.delete("/office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}")
def delete_roomflow_capture_room_api(job_id: str, room_id: str, operation_id: str, expected_revision: int) -> dict[str, Any]:
    actor = _require("estimates.manage")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    try:
        return roomflow_capture_service.apply(
            action="DELETE",
            operation_id=operation_id,
            workspace_id=workspace_id,
            job_id=job_id,
            actor_id=str(actor.get("id") or ""),
            room_id=room_id,
            expected_revision=expected_revision,
        )
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.post("/office/api/roomflow/jobs/{job_id}/capture/operations")
async def replay_roomflow_capture_operations_api(job_id: str, request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    _, workspace_id, _ = _browser_roomflow_workspace_context(actor)
    payload = await _capture_json(request)
    try:
        return roomflow_capture_service.apply_batch(
            workspace_id=workspace_id,
            job_id=job_id,
            actor_id=str(actor.get("id") or ""),
            operations=payload.get("operations") if isinstance(payload.get("operations"), list) else [],
        )
    except (CaptureValidationError, CaptureOperationConflict, CaptureOperationNotFound, ValueError, TypeError) as exc:
        _capture_error(exc)


@app.post("/office/api/roomflow/estimates/sync")
@app.post("/office/api/roomflow/sync")
async def roomflow_sync_api(request: Request) -> dict[str, Any]:
    actor = _require("estimates.manage")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="RoomFlow sent invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="RoomFlow payload must be an object.")

    preferred_workspace_id = _roomflow_clean(payload.get("workspace_id"), 160)
    workspaces, workspace_id, active_workspace = _browser_roomflow_workspace_context(actor, preferred_workspace_id)
    if preferred_workspace_id and not any(str(record.get("id") or "") == preferred_workspace_id for record in workspaces):
        raise HTTPException(status_code=422, detail="Select a valid Floodman RoomFlow company workspace before saving.")

    customer = payload.get("customer") if isinstance(payload.get("customer"), dict) else {}
    property_data = payload.get("property") if isinstance(payload.get("property"), dict) else {}
    estimate_data = payload.get("estimate") if isinstance(payload.get("estimate"), dict) else {}
    first, last, customer_name = _roomflow_contact_name(customer)
    email = _roomflow_clean(customer.get("email"), 254).lower()
    phone = _roomflow_clean(customer.get("phone"), 40)
    contact_id = _roomflow_clean(customer.get("contact_id") or payload.get("contact_id"), 100)
    contact = store.find_contact(contact_id=contact_id or None, email=email or None, phone=phone or None)
    if contact and str(contact.get("workspace_id") or "") not in {"", workspace_id}:
        contact = None
    contact_values = {
        "first_name": first,
        "last_name": last,
        "name": customer_name,
        "company": _roomflow_clean(customer.get("company"), 200),
        "email": email,
        "phone": phone,
        "lead_source": _roomflow_clean(customer.get("lead_source") or "ROOMFLOW", 160),
        "notes": _roomflow_clean(customer.get("notes"), 5000),
        "status": _roomflow_clean(customer.get("status") or "ACTIVE", 80).upper(),
        "workspace_id": workspace_id,
    }
    if contact:
        if contact.get("workspace_id"):
            contact_values.pop("workspace_id", None)
        contact = store.update_record("contacts", str(contact["id"]), {key: value for key, value in contact_values.items() if value}, actor_id=str(actor.get("id")))
    else:
        identity = email or "".join(character for character in phone if character.isdigit()) or f"{customer_name}:{uuid.uuid4()}"
        contact_values["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-roomflow-contact:{workspace_id}:{identity}"))
        contact = store.create_record("contacts", contact_values, actor_id=str(actor.get("id")))

    address = _roomflow_address(property_data)
    if not address["street"]:
        raise HTTPException(status_code=422, detail="Choose a customer property or enter a service street address before saving RoomFlow.")
    if not address["city"]:
        raise HTTPException(status_code=422, detail="Service city is required.")
    if len(address["state"]) < 2:
        raise HTTPException(status_code=422, detail="Service state is required.")
    if len(address["postal_code"]) < 3:
        raise HTTPException(status_code=422, detail="Service ZIP/postal code is required.")

    property_record = _roomflow_find_property(str(contact["id"]), property_data, workspace_id)
    property_values = {
        "contact_id": str(contact["id"]),
        "name": _roomflow_property_label(property_data),
        "property_name": _roomflow_property_label(property_data),
        "property_type": _roomflow_clean(property_data.get("property_type") or "Service property", 80),
        "service_address": address,
        "service_street": address["street"],
        "service_street2": address["street2"],
        "service_city": address["city"],
        "service_state": address["state"],
        "service_postal_code": address["postal_code"],
        "claim_number": _roomflow_clean(property_data.get("claim_number"), 100),
        "insurance_company": _roomflow_clean(property_data.get("insurance_company") or property_data.get("insurer"), 150),
        "notes": _roomflow_clean(property_data.get("notes"), 5000),
        "source": "ROOMFLOW",
        "workspace_id": workspace_id,
    }
    if property_record:
        if property_record.get("workspace_id"):
            property_values.pop("workspace_id", None)
        property_record = store.update_record("properties", str(property_record["id"]), {key: value for key, value in property_values.items() if value not in (None, "")}, actor_id=str(actor.get("id")))
    else:
        property_key = f"{contact['id']}:{address['street']}:{address['city']}:{address['state']}:{address['postal_code']}".lower()
        property_values["id"] = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-roomflow-property:{property_key}"))
        property_record = store.create_record("properties", property_values, actor_id=str(actor.get("id")))

    raw_lines = estimate_data.get("lines") if isinstance(estimate_data.get("lines"), list) else []
    raw_sections = estimate_data.get("sections") if isinstance(estimate_data.get("sections"), list) else []
    lines: list[dict[str, Any]] = []
    calculated_total = 0
    section_names: list[str] = []
    for index, raw in enumerate(raw_lines, start=1):
        if not isinstance(raw, dict):
            continue
        name = _roomflow_clean(raw.get("name") or raw.get("description"), 250)
        if not name:
            continue
        quantity = _roomflow_decimal(raw.get("quantity"), Decimal("1"))
        if quantity <= 0:
            raise HTTPException(status_code=422, detail=f"RoomFlow line {index} has an invalid quantity.")
        unit_price_cents = _roomflow_int(raw.get("unit_price_cents"), -1)
        if unit_price_cents < 0:
            unit_price_cents = int((_roomflow_decimal(raw.get("unit_price"), Decimal("0")) * 100).quantize(Decimal("1")))
        if unit_price_cents < 0:
            raise HTTPException(status_code=422, detail=f"RoomFlow line {index} has an invalid price.")
        line_total_cents = int((quantity * Decimal(unit_price_cents)).quantize(Decimal("1")))
        calculated_total += line_total_cents
        section_name = _roomflow_clean(raw.get("section_name") or estimate_data.get("title") or payload.get("job_name") or "Scope of Work", 240)
        if section_name not in section_names:
            section_names.append(section_name)
        raw_catalog_id = _roomflow_clean(raw.get("catalog_item_id"), 120)
        local_catalog = next((item for item in store.records("catalog_items") if raw_catalog_id and (str(item.get("source_id") or "") == raw_catalog_id or str(item.get("id") or "") == raw_catalog_id)), None)
        lines.append({
            "id": _roomflow_clean(raw.get("id") or raw.get("line_id") or raw.get("roomflow_line_id"), 120) or str(uuid.uuid4()),
            "section_id": _roomflow_clean(raw.get("section_id"), 120),
            "section_name": section_name,
            "catalog_item_id": str(local_catalog.get("id")) if local_catalog else None,
            "source_catalog_item_id": raw_catalog_id or None,
            "name": name,
            "description": _roomflow_clean(raw.get("description"), 5000),
            "quantity": float(quantity),
            "unit": _roomflow_clean(raw.get("unit") or "each", 50),
            "unit_price_cents": unit_price_cents,
            "line_total_cents": line_total_cents,
            "price": unit_price_cents / 100,
            "totalValue": line_total_cents / 100,
            "taxable": bool(raw.get("taxable")),
            "optional": bool(raw.get("optional")),
            "selected": raw.get("selected") is not False,
            "pricing_method": _roomflow_clean(raw.get("pricing_method") or "fixed", 50),
            "sort_order": _roomflow_int(raw.get("sort_order"), index - 1),
            "category": _roomflow_clean(raw.get("category") or section_name, 120),
            "pricing_reference": _roomflow_clean(raw.get("pricing_reference"), 160),
            "pricing_source": _roomflow_clean(raw.get("pricing_source"), 120),
            "pricing_price_list": _roomflow_clean(raw.get("pricing_price_list"), 160),
            "pricing_effective_date": _roomflow_clean(raw.get("pricing_effective_date"), 80),
            "pricing_market": _roomflow_clean(raw.get("pricing_market"), 200),
            "custom": not bool(raw_catalog_id),
            "save_to_catalog": not bool(raw_catalog_id),
            "source": "ROOMFLOW",
        })

    if raw_sections:
        section_payload = raw_sections
    else:
        section_payload = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"roomflow-section:{name}")), "name": name, "description": "", "sort_order": idx} for idx, name in enumerate(section_names)]
    # Normalize section IDs and line references through the same grouped-document parser used by Office estimates.
    try:
        sections, lines, calculated_total = normalize_document_payload({"sections": section_payload, "line_items": lines}, title=_roomflow_clean(estimate_data.get("title") or payload.get("job_name") or "Scope of Work", 240))
        lines = _save_custom_catalog_lines(lines, str(actor.get("id")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not lines:
        raise HTTPException(status_code=422, detail="Add at least one RoomFlow estimate line before saving.")

    tax_cents = max(0, _roomflow_int(estimate_data.get("tax_cents"), 0))
    discount_cents = max(0, _roomflow_int(estimate_data.get("discount_cents"), 0))
    total_cents = calculated_total + tax_cents - discount_cents
    if total_cents <= 0:
        raise HTTPException(status_code=422, detail="RoomFlow estimate total must be greater than zero.")

    roomflow_job_id = _roomflow_clean(payload.get("roomflow_job_id") or payload.get("job_id") or estimate_data.get("job_id"), 150)
    if not roomflow_job_id:
        roomflow_job_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"roomflow-job:{contact['id']}:{property_record['id']}"))
    roomflow_estimate_id = _roomflow_clean(payload.get("roomflow_estimate_id") or estimate_data.get("roomflow_estimate_id") or estimate_data.get("id"), 150)
    if not roomflow_estimate_id:
        roomflow_estimate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"roomflow-estimate:{roomflow_job_id}"))
    estimate_mapping_key = f"workspace:{workspace_id}:estimate:{roomflow_estimate_id}"
    estimate_id = store.external_mapping("roomflow", estimate_mapping_key)
    if not estimate_id:
        legacy_estimate_id = store.external_mapping("roomflow", f"estimate:{roomflow_estimate_id}")
        legacy_estimate = store.record("estimates", legacy_estimate_id) if legacy_estimate_id else None
        if legacy_estimate and str(legacy_estimate.get("workspace_id") or "") in {"", workspace_id}:
            estimate_id = legacy_estimate_id
    if not estimate_id:
        estimate_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-roomflow-estimate:{workspace_id}:{roomflow_estimate_id}"))
    estimate_number = _roomflow_clean(estimate_data.get("estimate_number"), 80) or f"RF-{len(store.records('estimates')) + 1001}"
    estimate_values = {
        "id": estimate_id,
        "estimate_number": estimate_number,
        "contact_id": str(contact["id"]),
        "property_id": str(property_record["id"]),
        "title": _roomflow_clean(estimate_data.get("title") or payload.get("job_name") or f"{property_record.get('name')} estimate", 250),
        "project_category": _roomflow_clean(estimate_data.get("project_category") or payload.get("project_category") or "general-restoration", 120),
        "status": _roomflow_clean(estimate_data.get("status") or "DRAFT", 40).upper(),
        "currency": "USD",
        "sections": sections,
        "line_items": lines,
        "subtotal_cents": calculated_total,
        "tax_cents": tax_cents,
        "discount_cents": discount_cents,
        "total_cents": total_cents,
        "balance_cents": total_cents,
        "deposit_percent": max(0.0, min(100.0, float(estimate_data.get("deposit_percent") or 30))),
        "expiration_days": max(1, min(365, _roomflow_int(estimate_data.get("expiration_days"), 30))),
        "terms": _roomflow_clean(estimate_data.get("terms") or "Payment is due upon receipt of each issued invoice. Additional work requires a signed Change Order.", 20000),
        "internal_note": _roomflow_clean(estimate_data.get("internal_note"), 5000),
        "roomflow_job_id": roomflow_job_id,
        "roomflow_estimate_id": roomflow_estimate_id,
        "workspace_id": workspace_id,
        "revision": max(1, _roomflow_int(payload.get("revision") or estimate_data.get("revision"), 1)),
        "issued_at": datetime.now(UTC).isoformat(),
        "source": "ROOMFLOW",
    }
    estimate_values = merge_project_plan(estimate_values)
    existing_estimate = store.record("estimates", estimate_id)
    created_estimate = existing_estimate is None
    if existing_estimate:
        existing_revision = max(1, _roomflow_int(existing_estimate.get("revision"), 1))
        incoming_revision = estimate_values["revision"]
        if incoming_revision < existing_revision:
            raise HTTPException(status_code=409, detail=f"RoomFlow revision {incoming_revision} is older than the saved revision {existing_revision}.")
        locked_status = str(existing_estimate.get("status") or "").upper()
        if locked_status in {"ACCEPTED", "CONVERTED", "VOID", "CANCELED", "CANCELLED"}:
            changed = int(existing_estimate.get("total_cents") or 0) != total_cents or existing_estimate.get("line_items") != lines or existing_estimate.get("sections") != sections
            if changed:
                raise HTTPException(status_code=409, detail=f"Estimate {estimate_number} is {locked_status.lower()} and cannot be changed from RoomFlow. Create a Change Order or a new revision.")
        estimate = store.update_record("estimates", estimate_id, estimate_values, actor_id=str(actor.get("id")))
    else:
        estimate = store.create_record("estimates", estimate_values, actor_id=str(actor.get("id")))
    store.set_external_mapping("roomflow", estimate_mapping_key, str(estimate["id"]))
    store.set_external_mapping("roomflow", f"workspace:{workspace_id}:job:{roomflow_job_id}", str(property_record["id"]))

    snapshot, snapshot_sha256, snapshot_bytes = _roomflow_snapshot(payload.get("roomflow_snapshot") or estimate_data.get("roomflow_snapshot") or {})
    snapshot["workspaceId"] = workspace_id
    snapshot_encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    snapshot_sha256 = hashlib.sha256(snapshot_encoded).hexdigest()
    snapshot_bytes = len(snapshot_encoded)
    snapshot_summary = {
        "rooms": len(snapshot.get("rooms") or []),
        "levels": len(snapshot.get("levels") or []),
        "measurements": len(snapshot.get("capturedMeasurements") or []),
        "total_cents": total_cents,
    }
    layout_values: dict[str, Any] = {}
    layout_input = payload.get("roomflow_layout_data_url") or estimate_data.get("roomflow_layout_data_url") or payload.get("layout_image")
    if layout_input:
        try:
            layout_values = store_layout_image(store, layout_input, filename=f"{estimate_number}-roomflow-layout.jpg") or {}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    existing_roomflow_job = next(
        (
            record
            for record in store.records("roomflow_jobs")
            if str(record.get("roomflow_job_id") or "") == roomflow_job_id
            and str(record.get("workspace_id") or "") in {"", workspace_id}
        ),
        None,
    )
    job_id = str((existing_roomflow_job or {}).get("id") or uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-roomflow-job:{workspace_id}:{roomflow_job_id}"))
    job_values = {
        "id": job_id,
        "roomflow_job_id": roomflow_job_id,
        "roomflow_estimate_id": roomflow_estimate_id,
        "job_name": _roomflow_clean(payload.get("job_name") or property_record.get("name"), 250),
        "contact_id": str(contact["id"]),
        "property_id": str(property_record["id"]),
        "estimate_id": str(estimate["id"]),
        "estimate_number": estimate_number,
        "workspace_id": workspace_id,
        "revision": estimate_values["revision"],
        "total_cents": total_cents,
        "status": "SYNCED",
        "last_sync_at": datetime.now(UTC).isoformat(),
        "source": "ROOMFLOW",
        "snapshot": snapshot,
        "snapshot_sha256": snapshot_sha256,
        "snapshot_bytes": snapshot_bytes,
        "summary": snapshot_summary,
    }
    if store.record("roomflow_jobs", job_id):
        roomflow_job = store.update_record("roomflow_jobs", job_id, job_values, actor_id=str(actor.get("id")))
    else:
        roomflow_job = store.create_record("roomflow_jobs", job_values, actor_id=str(actor.get("id")))

    note_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"roomflow-sync-note:{workspace_id}:{roomflow_estimate_id}:{estimate_values['revision']}"))
    note_values = {
        "id": note_id,
        "entity_type": "CONTACT",
        "entity_id": str(contact["id"]),
        "note_type": "ESTIMATE",
        "body": f"RoomFlow estimate {estimate_number} synchronized for {money_cents(total_cents)}.",
        "pinned": False,
        "created_by_name": str(actor.get("name") or actor.get("email") or "Floodman staff"),
        "source": "ROOMFLOW",
    }
    if store.record("notes", note_id):
        store.update_record("notes", note_id, note_values, actor_id=str(actor.get("id")))
    else:
        store.create_record("notes", note_values, actor_id=str(actor.get("id")))

    warnings: list[str] = []
    external_ids: dict[str, str | None] = {"contact": None, "property": None, "estimate": None}
    try:
        external_ids["contact"] = await _sync_contact_to_real_gauzy(contact, str(actor.get("id")))
    except Exception as exc:
        warnings.append(f"Customer ERP sync needs review: {exc}")
    try:
        external_ids["property"] = await _sync_property_to_real_gauzy(property_record, str(actor.get("id")))
    except Exception as exc:
        warnings.append(f"Property ERP sync needs review: {exc}")
    try:
        external_ids["estimate"] = await _sync_financial_to_real_gauzy("estimate", estimate, str(actor.get("id")), is_estimate=True)
    except Exception as exc:
        warnings.append(f"Estimate ERP sync needs review: {exc}")

    return {
        "ok": True,
        "created": created_estimate,
        "status": "SYNCED",
        "roomflow_job": roomflow_job,
        "workspace": workspace_public(active_workspace),
        "workspace_id": workspace_id,
        "contact_id": str(contact["id"]),
        "property_id": str(property_record["id"]),
        "estimate_id": str(estimate["id"]),
        "estimate_number": estimate_number,
        "estimate_url": f"/office/estimates/{estimate['id']}",
        "total_cents": total_cents,
        "erp_synced": bool(external_ids.get("estimate")),
        "warning": " ".join(warnings),
        "urls": {
            "customer": f"/office/contacts/{contact['id']}",
            "property": f"/office/properties/{property_record['id']}",
            "estimate": f"/office/estimates/{estimate['id']}",
            "roomflow": "/office/roomflow",
        },
        "external_ids": external_ids,
        "warnings": warnings,
    }

@app.get("/office/apps")
def applications_page() -> HTMLResponse:
    _require("apps.view")
    everyday_apps = [
        ("Floodman Office", settings.public_url, "Customers, properties, estimates, invoices, payments, documents, tasks, and daily operations.", "Open office"),
        ("Main Floodman ERP", settings.gauzy_hub_url, "Employees, time, projects, accounting, inventory, reporting, and organization management.", "Open main ERP"),
        ("Documents & Signing", settings.documenso_web_url, "Reusable templates and customer signatures for Work Authorizations, Change Orders, and Completion of Service.", "Open signing"),
        ("RoomFlow", f"{settings.public_url}/office/roomflow", "Customer-linked field layouts, measurements, scopes, and estimates using the same Floodman sign-in.", "Open RoomFlow"),
        ("Market Research", f"{settings.public_url}/office/intelligence", "Approved public-site monitoring, comparisons, and evidence-backed sales opportunities.", "Open research"),
    ]
    installer_apps = [
        ("Test Email Inbox", settings.mailpit_url, "Review messages captured during local testing without contacting real customers.", "Open test inbox"),
        ("Workflow Test Lab", f"{settings.engineering_public_url}/lab", "Test signing, payments, text messages, reminders, and end-to-end workflows.", "Open test lab"),
        ("API Explorer", f"{settings.api_public_url}/docs", "Developer documentation for the narrow RoomFlow, payment, signing, messaging, and receivables APIs.", "Open developer API"),
    ]
    render_apps = lambda apps: "".join(
        f"<div class='card app-card'><h2>{esc(name)}</h2><p>{esc(description)}</p><a class='button' href='{esc(url)}' target='_blank' rel='noreferrer'>{esc(action)}</a></div>"
        for name, url, description, action in apps
    )
    credentials = f"""<div class='card'><h2>Floodman business identity</h2><div class='grid two'>
    <div><h3>Primary Floodman ERP owner</h3><p><span class='mono'>{esc(settings.gauzy_admin_email)}</span></p><p class='muted'>The password is intentionally never displayed by the front end. Use the owner password configured in the Pterodactyl Startup settings.</p></div>
    <div><h3>Staff accounts</h3><p>Create employees and invitations inside native Floodman ERP, then assign Floodman module roles under Members &amp; Access.</p><p class='muted'>No seeded employee test account is enabled in clean business mode.</p></div></div></div>"""
    body = f"<div class='callout success'><b>Choose the job you want to do.</b> Your Floodman ERP sign-in carries into the connected Floodman browser modules; RoomFlow does not need a second account.</div><div class='grid two'>{render_apps(everyday_apps)}</div><details class='card plain-details'><summary>Installer and testing tools</summary><p class='muted'>These tools are for local testing or technical troubleshooting, not everyday customer work.</p><div class='grid two' style='margin-top:12px'>{render_apps(installer_apps)}</div></details>{credentials}"
    return _page("All Applications", body, "apps")


@app.get("/office/documents")
async def documents_page(contact_id: str = "", property_id: str = "", invoice_id: str = "") -> HTMLResponse:
    _require("documents.view")
    await _reconcile_local_signatures_once()
    state = await _state_page_data()
    local_documents = store.records("documents")
    workflow_documents = _rows(state.get("envelopes"))
    imported_documents = _rows(state.get("imported_documents"))
    rows = []
    seen: set[str] = set()
    for item in local_documents + workflow_documents:
        identity = str(item.get("id") or item.get("envelope_id") or "")
        if identity in seen:
            continue
        seen.add(identity)
        recipients = item.get("recipients") or []
        signing_url = item.get("signing_url") or ((recipients[0] if recipients else {}).get("signingUrl"))
        local_url = item.get("download_url")
        signed_url = item.get("signed_download_url")
        actions = []
        if signing_url:
            actions.append(f"<a href='{esc(signing_url)}' target='_blank'>Sign / review</a>")
        if signed_url:
            actions.append(f"<a href='{esc(signed_url)}' target='_blank'><b>Signed PDF</b></a>")
        if local_url:
            actions.append(f"<a href='{esc(local_url)}' target='_blank'>Original PDF</a>")
        if item.get("contact_id"):
            actions.append(f"<a href='/office/contacts/{esc(item.get('contact_id'))}'>Client file</a>")
        if store.record("documents", identity) and has_permission(_user(), "documents.manage"):
            actions.append(f"<form method='post' action='/office/documents/{esc(identity)}/delete' style='display:inline'><button class='danger small'>Delete draft</button></form>")
        rows.append([
            esc(item.get("title") or item.get("document_type") or identity),
            badge(item.get("status") or "DRAFT"),
            esc(item.get("recipient_name") or ((recipients[0] if recipients else {}).get("name")) or ""),
            esc(item.get("recipient_email") or ((recipients[0] if recipients else {}).get("email")) or ""),
            esc(item.get("completedAt") or item.get("createdAt") or item.get("created_at") or ""),
            " · ".join(actions),
        ])
    imported_rows = []
    for item in imported_documents:
        run_id = item.get("import_run_id") or item.get("_import_run_id")
        file_path = item.get("file_path") or ""
        archive_url = item.get("archive_url")
        if not archive_url and run_id and file_path:
            archive_url = f"/office/imports/{quote(str(run_id))}/files/{quote(str(file_path), safe='/')}"
        imported_rows.append([
            esc(item.get("document_type") or item.get("id")),
            badge(item.get("status") or "REFERENCE_ONLY"),
            esc(item.get("signed_at") or ""),
            esc(item.get("legacy_document_id") or item.get("id") or ""),
            f"<a href='{esc(archive_url)}' target='_blank'>Open archived file</a>" if archive_url else esc(file_path),
        ])
    create = ""
    if has_permission(_user(), "documents.manage"):
        create = f"""<div class='card'><h2>Upload and send a document for signature</h2><form method='post' action='/office/documents/add' enctype='multipart/form-data'><div class='form-grid three'>
        <div class='field'><label>Document type</label><select name='document_type'><option>WORK_AUTHORIZATION</option><option>CHANGE_ORDER</option><option>COMPLETION_OF_SERVICE</option><option>PAYMENT_AUTHORIZATION</option><option>CUSTOM</option></select></div>
        {_entity_picker(kind='contacts', name='contact_id', label='Customer', selected_id=contact_id, selected_label=_contact_name(contact_id, state) if contact_id else '', required=True)}{_entity_picker(kind='properties', name='property_id', label='Property / job', selected_id=property_id, selected_label=_property_label(next((i for i in _all_property_rows(state) if str(i.get('id')) == property_id), {})) if property_id else '', contact_source='contact_id')}
        <div class='field'><label>Related invoice ID</label><input name='invoice_id' value='{esc(invoice_id)}' placeholder='Optional invoice reference'></div>
        <div class='field full'><label>Document title</label><input name='title' placeholder='Work Authorization – 123 Main Street' required></div>
        <div class='field'><label>Signer name</label><input name='recipient_name' required></div><div class='field'><label>Signer email</label><input type='email' name='recipient_email' required></div>
        <div class='field full'><label>PDF file</label><input type='file' name='document' accept='application/pdf,.pdf' required><div class='muted'>The Engineering Sandbox stores the original PDF and creates a controlled signing envelope. Use the full Floodman Signing workspace for visual field placement, reusable templates, multi-recipient routing, and production signing.</div></div></div><button style='margin-top:12px'>Create signing envelope</button></form></div>"""
    body = f"{create}<div class='actions'><a class='button' href='{esc(settings.documenso_web_url)}' target='_blank'>Open Floodman Signing</a></div><div class='card'><h2>Active signing documents</h2>{table(('Document','Status','Signer','Email','Timestamp','Action'), rows)}</div><div class='card'><h2>Imported document archive</h2>{table(('Document','Status','Signed','Legacy ID','File'), imported_rows)}</div>"
    return _page("Documents & Signing", body, "documents")


@app.post("/office/documents/add")
async def add_document(
    document_type: str = Form(...),
    contact_id: str = Form(...),
    property_id: str = Form(default=""),
    invoice_id: str = Form(default=""),
    title: str = Form(...),
    recipient_name: str = Form(...),
    recipient_email: str = Form(...),
    document: UploadFile = File(...),
) -> RedirectResponse:
    actor = _require("documents.manage")
    state = await _state_page_data()
    _ensure_local_contact(contact_id, state)
    if property_id:
        selected_property = next((item for item in _all_property_rows(state) if str(item.get("id") or "") == property_id), None)
        if not selected_property or str(selected_property.get("contact_id") or "") != contact_id:
            store.set_notice("Choose a property that belongs to the selected customer.")
            return RedirectResponse("/office/documents", status_code=303)
    content = await document.read()
    if not content or len(content) > settings.max_upload_bytes:
        store.set_notice(f"Document must contain data and be no larger than {settings.max_upload_bytes // (1024*1024)} MB.")
        return RedirectResponse("/office/documents", status_code=303)
    if not content.startswith(b"%PDF"):
        store.set_notice("Only PDF documents may be sent for signature.")
        return RedirectResponse("/office/documents", status_code=303)
    file_id, saved = store.save_upload(document.filename or "document.pdf", content)
    record = store.create_record("documents", {
        "document_type": document_type.upper(),
        "contact_id": contact_id or None,
        "property_id": property_id or None,
        "invoice_id": invoice_id or None,
        "title": title.strip(),
        "recipient_name": recipient_name.strip(),
        "recipient_email": recipient_email.strip().lower(),
        "file_id": file_id,
        "filename": saved.name,
        "download_url": f"/office/uploads/{file_id}/{quote(saved.name)}",
        "status": "DRAFT",
    }, actor_id=actor.get("id"))
    try:
        envelope = await providers.create_signing_document(
            filename=saved.name,
            content=content,
            title=title.strip(),
            external_id=record["id"],
            recipient_name=recipient_name.strip(),
            recipient_email=recipient_email.strip().lower(),
        )
        recipients = envelope.get("recipients") or []
        signing_url = (recipients[0] if recipients else {}).get("signingUrl")
        record = store.update_record("documents", record["id"], {
            "status": envelope.get("status") or "SENT",
            "envelope_id": envelope.get("id"),
            "signing_url": signing_url,
            "provider_response": envelope,
        }, actor_id=actor.get("id"))
        store.set_notice(f"{title.strip()} was created and sent to the local signing workflow.")
    except Exception as exc:
        store.set_notice(f"Document saved as a draft. Signing bridge warning: {exc}")
    return RedirectResponse("/office/documents", status_code=303)


@app.get("/office/uploads/{file_id}/{filename}")
def uploaded_file(file_id: str, filename: str) -> Response:
    _require("documents.view")
    try:
        path = store.upload_path(file_id, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not path.exists():
        raise HTTPException(404, "File not found")
    return Response(path.read_bytes(), media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream", headers={"Content-Disposition": f'inline; filename="{path.name}"'})


@app.get("/office/notes")
async def notes_page() -> HTMLResponse:
    _require("notes.view")
    state = await _state_page_data()
    notes = store.records("notes") + _rows(state.get("notes"))
    rows = [
        [esc(item.get("created_at") or ""), badge(item.get("entity_type") or "NOTE"), esc(item.get("entity_id") or ""), esc(item.get("note") or ""), esc(item.get("legacy_note_id") or item.get("id") or ""), f"<form method='post' action='/office/notes/{esc(item.get('id'))}/delete'><button class='danger small'>Delete</button></form>" if store.record("notes", str(item.get("id") or "")) and has_permission(_user(), "notes.manage") else ""]
        for item in notes
    ]
    create = ""
    if has_permission(_user(), "notes.manage"):
        create = """<div class='card'><h2>Add internal note</h2><form method='post' action='/office/notes/add'><div class='form-grid three'><div class='field'><label>Record type</label><select name='entity_type'><option>CONTACT</option><option>PROPERTY</option><option>ESTIMATE</option><option>INVOICE</option><option>JOB</option><option>GENERAL</option></select></div><div class='field'><label>Record ID / reference</label><input name='entity_id'></div><div class='field full'><label>Note</label><textarea name='note' required></textarea></div></div><button style='margin-top:12px'>Save note</button></form></div>"""
    return _page("Notes", f"{create}<div class='card'><h2>Internal notes</h2>{table(('Created','Record type','Record','Note','Reference','Action'), rows)}</div>", "notes")


@app.post("/office/notes/add")
def add_note(entity_type: str = Form(...), entity_id: str = Form(default=""), note: str = Form(...)) -> RedirectResponse:
    actor = _require("notes.manage")
    store.create_record("notes", {"entity_type": entity_type.upper(), "entity_id": entity_id.strip(), "note": note.strip()}, actor_id=actor.get("id"))
    store.set_notice("Note saved.")
    return RedirectResponse("/office/notes", status_code=303)


@app.get("/office/tasks")
def tasks_page() -> HTMLResponse:
    _require("tasks.view")
    tasks = store.records("tasks")
    rows = [
        [esc(item.get("title")), badge(item.get("status") or "OPEN"), badge(item.get("priority") or "NORMAL"), esc(item.get("assigned_to_name") or "Unassigned"), esc(item.get("due_at") or ""), f"<form method='post' action='/office/tasks/{esc(item.get('id'))}/toggle'><button>{'Reopen' if item.get('status')=='COMPLETED' else 'Complete'}</button></form>" if has_permission(_user(), 'tasks.manage') else ""]
        for item in tasks
    ]
    member_options = "".join(f"<option value='{esc(user.get('id'))}'>{esc(user.get('name'))} · {esc(user.get('role'))}</option>" for user in store.list_users() if user.get("status") == "ACTIVE")
    create = ""
    if has_permission(_user(), "tasks.manage"):
        create = f"""<div class='card'><h2>Create task</h2><form method='post' action='/office/tasks/add'><div class='form-grid three'><div class='field full'><label>Task</label><input name='title' required></div><div class='field'><label>Assign to</label><select name='assigned_to'><option value=''>Unassigned</option>{member_options}</select></div><div class='field'><label>Priority</label><select name='priority'><option>NORMAL</option><option>HIGH</option><option>URGENT</option><option>LOW</option></select></div><div class='field'><label>Due date</label><input type='datetime-local' name='due_at'></div><div class='field full'><label>Description</label><textarea name='description'></textarea></div></div><button style='margin-top:12px'>Create task</button></form></div>"""
    return _page("Tasks", f"{create}<div class='card'><h2>Team tasks</h2>{table(('Task','Status','Priority','Assigned','Due','Action'), rows)}</div>", "tasks")


@app.post("/office/tasks/add")
def add_task(title: str = Form(...), assigned_to: str = Form(default=""), priority: str = Form(default="NORMAL"), due_at: str = Form(default=""), description: str = Form(default="")) -> RedirectResponse:
    actor = _require("tasks.manage")
    assignee = store.get_user(assigned_to) if assigned_to else None
    store.create_record("tasks", {"title": title.strip(), "assigned_to": assigned_to or None, "assigned_to_name": (assignee or {}).get("name"), "priority": priority.upper(), "due_at": due_at or None, "description": description.strip(), "status": "OPEN"}, actor_id=actor.get("id"))
    store.set_notice("Task created.")
    return RedirectResponse("/office/tasks", status_code=303)


@app.post("/office/tasks/{task_id}/toggle")
def toggle_task(task_id: str) -> RedirectResponse:
    actor = _require("tasks.manage")
    task = store.record("tasks", task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    completed = task.get("status") == "COMPLETED"
    store.update_record("tasks", task_id, {"status": "OPEN" if completed else "COMPLETED", "completed_at": None if completed else datetime.now(UTC).isoformat()}, actor_id=actor.get("id"))
    return RedirectResponse("/office/tasks", status_code=303)


@app.get("/office/time")
def time_page() -> HTMLResponse:
    user = _require("time.self")
    current = store.current_clock(str(user.get("id")))
    all_entries = store.records("time_entries")
    if not has_permission(user, "time.manage"):
        all_entries = [item for item in all_entries if item.get("user_id") == user.get("id")]
    rows = []
    for item in all_entries:
        member = store.get_user(str(item.get("user_id") or "")) or {}
        approval = badge(item.get("approval_status") or "PENDING")
        if has_permission(user, "time.manage") and item.get("status") == "COMPLETED" and item.get("approval_status") != "APPROVED":
            approval += f" <form method='post' action='/office/time/{esc(item.get('id'))}/approve' style='display:inline'><button class='small'>Approve</button></form>"
        rows.append([esc(member.get("name") or item.get("user_id")), esc(item.get("job_reference") or ""), esc(item.get("clock_in") or ""), esc(item.get("clock_out") or "Running"), _duration(item.get("duration_seconds")), badge(item.get("status")), approval, esc(item.get("note") or "")])
    if current:
        action = f"""<div class='callout good'><b>Clocked in:</b> {esc(current.get('job_reference') or 'General work')} since {esc(current.get('clock_in'))}</div><form method='post' action='/office/time/out'><div class='field'><label>Clock-out note</label><input name='note'></div><button class='danger' style='margin-top:12px'>Clock out</button></form>"""
    else:
        action = """<form method='post' action='/office/time/in'><div class='form-grid'><div class='field'><label>Job / project reference</label><input name='job_reference' placeholder='Job 1042 or office administration' required></div><div class='field'><label>Note</label><input name='note'></div></div><button style='margin-top:12px'>Clock in</button></form>"""
    manual = ""
    if has_permission(user, "time.manage"):
        member_options = "".join(f"<option value='{esc(member.get('id'))}'>{esc(member.get('name'))}</option>" for member in store.list_users() if member.get("status") == "ACTIVE")
        manual = f"""<div class='card'><h2>Add manual time entry</h2><form method='post' action='/office/time/manual'><div class='form-grid three'><div class='field'><label>Member</label><select name='user_id'>{member_options}</select></div><div class='field'><label>Job / project</label><input name='job_reference' required></div><div class='field'><label>Clock in</label><input type='datetime-local' name='clock_in_at' required></div><div class='field'><label>Clock out</label><input type='datetime-local' name='clock_out_at' required></div><div class='field full'><label>Note</label><input name='note'></div></div><button style='margin-top:12px'>Add approved entry</button></form></div>"""
    body = f"<div class='grid two'><div class='card'><h2>Your time clock</h2>{action}</div><div class='card'><h2>Floodman ERP time tracking</h2><p>Use the Floodman ERP interface for projects, tasks, timesheets, approvals, activity levels, screenshots, time-off, and employee reports.</p><a class='button' href='{esc(settings.gauzy_web_url)}' target='_blank'>Open Floodman ERP time tracking</a></div></div>{manual}<div class='card'><h2>Time entries</h2>{table(('Member','Job','Clock in','Clock out','Duration','Status','Approval','Note'), rows)}</div>"
    return _page("Time Clock", body, "time")


@app.post("/office/time/in")
def clock_in(job_reference: str = Form(...), note: str = Form(default="")) -> RedirectResponse:
    user = _require("time.self")
    store.clock_in(str(user.get("id")), job_reference, note)
    store.set_notice("You are clocked in.")
    return RedirectResponse("/office/time", status_code=303)


@app.post("/office/time/out")
def clock_out(note: str = Form(default="")) -> RedirectResponse:
    user = _require("time.self")
    entry = store.clock_out(str(user.get("id")), note)
    store.set_notice("You are clocked out." if entry else "No running time entry was found.")
    return RedirectResponse("/office/time", status_code=303)


@app.get("/office/members")
def members_page() -> HTMLResponse:
    _require("members.manage")
    users = store.list_users()
    invites = store.list_invites()
    role_labels = {
        "ADMIN": "Administrator",
        "OFFICE_MANAGER": "Office manager",
        "BILLING": "Billing",
        "ESTIMATOR": "Estimator",
        "TECHNICIAN": "Field technician",
        "VIEWER": "View only",
    }
    role_help = {
        "ADMIN": "Everything except ownership; use for a trusted backup administrator.",
        "OFFICE_MANAGER": "Customers, jobs, estimates, billing, documents, messages, tasks, and calendar.",
        "BILLING": "Invoices, payments, receivables, and customer billing records.",
        "ESTIMATOR": "Customers, properties, RoomFlow, estimates, documents, notes, and assigned work.",
        "TECHNICIAN": "View job records, add notes, complete tasks, and clock time.",
        "VIEWER": "Read-only access to normal business records.",
    }
    assignable_roles = tuple(role_labels)
    role_options = "".join(
        f"<option value='{esc(role)}' {'selected' if role == 'VIEWER' else ''}>{esc(role_labels[role])}</option>"
        for role in assignable_roles
    )
    user_rows = []
    for item in users:
        if item.get("role") == "OWNER":
            controls = f"""{badge('Primary owner', 'good')}<form method='post' action='/office/members/{esc(item.get('id'))}/update'><input type='hidden' name='role' value='OWNER'><input type='hidden' name='status' value='ACTIVE'><label class='muted'>Call alert mobile<input name='phone' inputmode='tel' autocomplete='tel' value='{esc(item.get('phone') or '')}' placeholder='+12315550199'></label><button>Save alerts</button></form>"""
        else:
            controls = f"""<form method='post' action='/office/members/{esc(item.get('id'))}/update'><label class='muted'>Access level<select aria-label='Access level for {esc(item.get('name'))}' name='role'>{''.join(f"<option value='{esc(role)}' {'selected' if role==item.get('role') else ''}>{esc(role_labels[role])}</option>" for role in assignable_roles)}</select></label><label class='muted'>Account status<select aria-label='Account status for {esc(item.get('name'))}' name='status'><option value='ACTIVE' {'selected' if item.get('status')=='ACTIVE' else ''}>Active</option><option value='DISABLED' {'selected' if item.get('status')=='DISABLED' else ''}>Disabled</option></select></label><label class='muted'>Call alert mobile<input name='phone' inputmode='tel' autocomplete='tel' value='{esc(item.get('phone') or '')}' placeholder='+12315550199'></label><details><summary>Set a local recovery password</summary><input name='password' type='password' minlength='10' autocomplete='new-password' placeholder='At least 10 characters'></details><button>Save access</button></form>"""
        source = item.get("auth_source") or ("FLOODMAN" if item.get("gauzy_user_id") else "LOCAL")
        user_rows.append([esc(item.get("name")), esc(item.get("email")), esc(item.get("phone") or "Not set"), badge("Owner" if item.get("role") == "OWNER" else role_labels.get(str(item.get("role")), str(item.get("role")).replace("_", " ").title())), badge("ERP sign-in" if source in {"GAUZY", "FLOODMAN"} else "ERP + local" if source == "LOCAL_AND_GAUZY" else "Local recovery"), badge("Active" if item.get("status") == "ACTIVE" else "Disabled", "good" if item.get("status") == "ACTIVE" else "neutral"), controls])
    invite_rows = [[esc(item.get("name")), esc(item.get("email")), badge(role_labels.get(str(item.get("role")), str(item.get("role")).replace("_", " ").title())), badge(str(item.get("status") or "Pending").title()), esc(str(item.get("expires_at") or "")[:10])] for item in invites]
    role_guide = "".join(f"<div><b>{esc(role_labels[role])}</b><small>{esc(role_help[role])}</small></div>" for role in assignable_roles)
    body = f"""
    <div class='callout success'><b>Use one Floodman ERP sign-in.</b> Add the employee in the main ERP first. The first time they choose <b>Continue with Floodman ERP</b>, Floodman creates their module access automatically—no second RoomFlow account is needed.</div>
    <div class='card'><div class='actions spread'><div><h2>Add or invite an employee</h2><p class='muted'>Create the person once in the main ERP, then return here only if their module access level needs adjustment.</p></div><div class='actions'><a class='button good' href='{esc(settings.gauzy_web_url)}/index.html?desktop=1#/pages/employees' target='_top'>Open ERP employees</a><a class='button secondary' href='{esc(settings.gauzy_web_url)}/index.html?desktop=1#/pages/employees/invites' target='_top'>Open ERP invitations</a></div></div><h3>Which access level should I choose?</h3><div class='role-guide'>{role_guide}</div><p class='muted'>Start with the narrowest role that fits the job. Only the primary owner can control ownership.</p></div>
    <div class='card'><h2>Floodman and RoomFlow access</h2><p class='muted'>Changes apply to the integrated Floodman modules. ERP employment and organization permissions remain managed in the main ERP.</p>{table(('Team member','Email','Call alert mobile','Access level','Sign-in','Status','Change access'), user_rows)}</div>
    <details class='card plain-details'><summary>Advanced: create a Floodman-only recovery account</summary><p class='muted'>Use this only when the person cannot use the main ERP identity. The invitation expires in seven days and creates a separate local password.</p><form method='post' action='/office/members/invite'><div class='form-grid three'><div class='field'><label>Full name</label><input name='name' minlength='2' maxlength='160' autocomplete='name' required></div><div class='field'><label>Email / username</label><input type='email' name='email' autocomplete='email' required></div><div class='field'><label>Call alert mobile</label><input name='phone' inputmode='tel' autocomplete='tel' placeholder='+12315550199'></div><div class='field'><label>Access level</label><select name='role'>{role_options}</select></div></div><button style='margin-top:12px'>Create recovery invitation</button></form></details>
    <details class='card plain-details'><summary>Invitation history</summary>{table(('Name','Email','Access level','Status','Expires'), invite_rows)}</details>"""
    return _page("Team & Access", body, "members")


@app.post("/office/members/invite")
async def invite_member(
    name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(default=""),
    role: str = Form(default="VIEWER"),
) -> HTMLResponse:
    actor = _require("members.manage")
    try:
        invite, token = store.create_invite(name, email, role, str(actor.get("id")), phone)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/members", status_code=303)
    url = f"{settings.public_url.rstrip('/')}/invite/{token}"
    mail_status = ""
    try:
        await providers.send_email(
            to=str(invite.get("email")),
            subject="Your Floodman Office invitation",
            text=(
                f"Hello {invite.get('name') or ''},\n\n"
                f"You were invited to Floodman Office as {invite.get('role')}.\n"
                f"Create your account here: {url}\n\n"
                "This invitation expires in seven days."
            ),
        )
        mail_status = "<div class='callout success'>The invitation email was captured by the local mail system. Open the Engineering Sandbox mail view, or Mailpit for messages produced by Floodman ERP and Documenso.</div>"
    except Exception as exc:
        mail_status = f"<div class='callout warning'>The account invitation was created, but email delivery was unavailable: {esc(exc)}</div>"
    body = f"<h1>Invitation created</h1>{mail_status}<p>Send this local invitation link to <b>{esc(invite.get('email'))}</b> if they did not receive the test email. It is shown once.</p><div class='callout'><span class='mono'>{esc(url)}</span></div><a class='button' href='{esc(url)}'>Open invitation</a> <a class='button secondary' href='/office/members'>Return to members</a>"
    return HTMLResponse(simple_page("Invitation created", body))


@app.post("/office/members/{user_id}/update")
def update_member(
    user_id: str,
    role: str = Form(...),
    status: str = Form(...),
    phone: str = Form(default=""),
    password: str = Form(default=""),
) -> RedirectResponse:
    _require("members.manage")
    try:
        store.update_user(user_id, role=role, status=status, password=password or None, phone=phone)
        store.set_notice("Member access updated.")
    except (KeyError, ValueError) as exc:
        store.set_notice(str(exc))
    return RedirectResponse("/office/members", status_code=303)


@app.get("/invite/{token}")
def invite_page(token: str) -> HTMLResponse:
    invite = store.invite_for_token(token)
    if not invite:
        return HTMLResponse(simple_page("Invitation unavailable", "<h1>Invitation unavailable</h1><p>This invitation is invalid, expired, or already used.</p>"), status_code=404)
    body = f"""<h1>Join Floodman Office</h1><p>You were invited as <b>{esc(invite.get('role'))}</b>.</p><form method='post' action='/invite/{esc(token)}'><div class='field'><label>Name</label><input value='{esc(invite.get('name'))}' disabled></div><div class='field' style='margin-top:12px'><label>Email</label><input value='{esc(invite.get('email'))}' disabled></div><div class='field' style='margin-top:12px'><label>Create password</label><input type='password' name='password' minlength='10' required></div><div class='field' style='margin-top:12px'><label>Confirm password</label><input type='password' name='confirm_password' minlength='10' required></div><button style='margin-top:16px;width:100%'>Create account</button></form>"""
    return HTMLResponse(simple_page("Join Floodman Office", body))


@app.post("/invite/{token}")
def accept_invitation(token: str, password: str = Form(...), confirm_password: str = Form(...)) -> Response:
    if password != confirm_password:
        return HTMLResponse(simple_page("Join Floodman Office", "<h1>Passwords do not match</h1><a class='button' href='javascript:history.back()'>Return</a>"), status_code=422)
    try:
        user = store.accept_invite(token, password)
    except ValueError as exc:
        return HTMLResponse(simple_page("Invitation unavailable", f"<h1>Invitation unavailable</h1><p>{esc(exc)}</p>"), status_code=422)
    response = RedirectResponse("/office", status_code=303)
    response.set_cookie("floodman_session", store.create_session(user["id"]), httponly=True, secure=settings.session_cookie_secure, samesite="lax", max_age=14*86400, path="/")
    return response


def _portal_document_for_thread(thread: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    preferred_kind = str(thread.get("last_document_kind") or "")
    preferred_id = str(thread.get("last_document_id") or "")
    if preferred_kind in {"estimate", "invoice"} and preferred_id:
        preferred = store.record(preferred_kind + "s", preferred_id)
        if preferred and preferred.get("public_enabled") is not False and preferred.get("public_token"):
            return preferred_kind, preferred
    contact_id = str(thread.get("contact_id") or "")
    property_id = str(thread.get("property_id") or "")
    candidates: list[tuple[str, dict[str, Any]]] = []
    for kind in ("invoice", "estimate"):
        candidates.extend(
            (kind, item)
            for item in store.records(kind + "s")
            if str(item.get("contact_id") or "") == contact_id
            and (not property_id or str(item.get("property_id") or "") == property_id)
            and item.get("public_enabled") is not False
            and item.get("public_token")
        )
    return candidates[0] if candidates else None


def _mark_thread_read_for_staff(thread_id: str, user_id: str) -> None:
    now = datetime.now(UTC).isoformat()
    for message in _customer_thread_messages(thread_id):
        if str(message.get("sender_kind") or "").upper() == "CUSTOMER" and not message.get("staff_read_at"):
            store.update_record("customer_messages", str(message["id"]), {"staff_read_at": now}, actor_id=user_id)
    for notification in store.records("notifications"):
        if (
            str(notification.get("user_id") or "") == user_id
            and str(notification.get("reference_id") or "") == thread_id
            and str(notification.get("status") or "UNREAD").upper() == "UNREAD"
        ):
            store.update_record("notifications", str(notification["id"]), {"status": "READ", "read_at": now}, actor_id=user_id)


@app.get("/office/messages")
async def messages_page(thread: str = "") -> HTMLResponse:
    user = _require("messages.view")
    threads = store.records("customer_threads")
    selected = store.record("customer_threads", thread) if thread else (threads[0] if threads else None)
    if selected:
        _mark_thread_read_for_staff(str(selected["id"]), str(user.get("id") or ""))
        selected = store.record("customer_threads", str(selected["id"])) or selected

    thread_links = []
    for item in threads:
        contact = store.record("contacts", str(item.get("contact_id") or "")) or {}
        messages = _customer_thread_messages(str(item.get("id") or ""))
        unread = sum(1 for message in messages if str(message.get("sender_kind") or "").upper() == "CUSTOMER" and not message.get("staff_read_at"))
        latest = messages[-1] if messages else {}
        unread_badge = f" {badge(f'{unread} new', 'warn')}" if unread else ""
        active_class = " active" if selected and str(selected.get("id")) == str(item.get("id")) else ""
        thread_links.append(
            f"<a class='thread-link{active_class}' href='/office/messages?thread={quote(str(item.get('id') or ''))}'><b>{esc(_contact_display_name(contact))}{unread_badge}</b><small>{esc(str(latest.get('body') or 'No messages yet')[:90])}</small><small>{esc(str(latest.get('created_at') or '')[:16].replace('T', ' '))}</small></a>"
        )

    conversation = "<div class='card'><h2>Select a conversation</h2><p class='muted'>Customer replies will appear here as soon as they send a secure portal message.</p></div>"
    if selected:
        thread_id = str(selected["id"])
        contact = store.record("contacts", str(selected.get("contact_id") or "")) or {}
        messages = _customer_thread_messages(thread_id)
        rendered = "".join(
            f"<article class='staff-message {'staff' if str(item.get('sender_kind') or '').upper() == 'STAFF' else 'customer'}'><div class='staff-message-head'><b>{esc(item.get('sender_name') or ('Floodman team' if str(item.get('sender_kind') or '').upper() == 'STAFF' else _contact_display_name(contact)))}</b><span>{esc(str(item.get('created_at') or '')[:16].replace('T', ' '))} UTC</span></div><p>{esc(item.get('body') or '')}</p>{f"<small class='staff-message-delivery'>Customer email notification: {esc(str(item.get('customer_email_status') or 'not requested').replace('_', ' ').title())}</small>" if str(item.get('sender_kind') or '').upper() == 'STAFF' else ''}</article>"
            for item in messages
        ) or "<div class='callout'>No messages are in this conversation yet.</div>"
        portal_document = _portal_document_for_thread(selected)
        portal_link = f"<a class='button secondary' href='{esc(portal_document[1].get('public_url') or '')}' target='_blank'>Open customer portal</a>" if portal_document else ""
        reply_form = ""
        if has_permission(user, "messages.manage"):
            reply_request_id = secrets.token_urlsafe(24)
            reply_form = f"<form method='post' action='/office/messages/{esc(thread_id)}/reply'><input type='hidden' name='request_id' value='{esc(reply_request_id)}'><div class='field'><label for='staff-reply'>Reply to customer</label><textarea id='staff-reply' name='body' maxlength='3000' required placeholder='Write a clear reply for the customer...'></textarea><small class='field-help'>Floodman saves the reply in the portal and emails a secure notification when the customer has an email address.</small></div><button class='good' style='margin-top:12px'>Send reply</button></form>"
        conversation = f"<div class='card'><div class='actions spread'><div><h2>{esc(_contact_display_name(contact))}</h2><p class='muted'>{esc(contact.get('email') or 'No customer email')} · Secure customer portal conversation</p></div><div class='actions'><a class='button secondary' href='/office/contacts/{esc(contact.get('id') or '')}'>Open customer</a>{portal_link}</div></div><div class='staff-message-list'>{rendered}</div>{reply_form}</div>"

    state = await _state_page_data()
    sms = _rows(state.get("sms_messages"))
    emails = _rows(state.get("emails"))
    sms_rows = [[esc(item.get("created_at")), esc(item.get("to")), badge(item.get("status")), esc(item.get("body"))] for item in sms]
    email_rows = [[esc(item.get("received_at")), esc(", ".join(item.get("to") or [])), esc(item.get("subject")), f"<details><summary>Open</summary><pre>{esc(item.get('text') or item.get('html') or '')}</pre></details>"] for item in emails]
    test_tools = ""
    if has_permission(user, "messages.manage"):
        test_tools = """<div class='card'><h2>Send local test SMS</h2><form method='post' action='/office/messages/send'><div class='form-grid'><div class='field'><label>Phone</label><input name='phone' value='+13135550199' required></div><div class='field full'><label>Message</label><textarea name='body' required></textarea></div></div><button style='margin-top:12px'>Send test message</button></form></div>"""
    body = f"<div class='callout success'><b>Customer portal messaging is active.</b> Customers can write from a secure estimate or invoice link. Staff with message access receive an in-app/mobile alert and email notification; customer replies are never exposed on public administrative pages.</div><div class='conversation-shell'><aside class='card'><h2>Customer conversations</h2><div class='thread-list'>{''.join(thread_links) or '<div class=\'empty\'>No portal conversations yet.</div>'}</div></aside><section>{conversation}</section></div><details class='card plain-details'><summary>SMS, captured email, and testing tools</summary><div style='margin-top:14px'>{test_tools}<div class='card'><h2>Outbound and automated SMS</h2>{table(('Time','To','Status','Message'), sms_rows)}</div><div class='card'><h2>Captured email</h2>{table(('Time','To','Subject','Body'), email_rows)}</div><div class='card'><h2>Try the AI text assistant</h2><form method='post' action='{esc(settings.engineering_public_url)}/lab/sms/inbound'><div class='form-grid'><div class='field full'><label>Customer message</label><input name='body' value='What is my balance?' required></div></div><button>Send local inbound SMS</button></form></div></div></details>"
    return _page("Messages", body, "messages")


@app.post("/office/messages/{thread_id}/reply")
async def reply_to_customer(thread_id: str, body: str = Form(...), request_id: str = Form(...)) -> RedirectResponse:
    user = _require("messages.manage")
    thread = store.record("customer_threads", thread_id)
    if not thread:
        raise HTTPException(404, "Customer conversation not found")
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(request_id or "")):
        store.set_notice("Refresh the conversation and send your reply again.")
        return RedirectResponse(f"/office/messages?thread={quote(thread_id)}", status_code=303)
    try:
        message_body = _clean_portal_message(body)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/messages?thread={quote(thread_id)}", status_code=303)
    contact = store.record("contacts", str(thread.get("contact_id") or "")) or {}
    now = datetime.now(UTC).isoformat()
    message_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"floodman-staff-message:{thread_id}:{user.get('id')}:{request_id}"))
    message, created = store.create_record_if_absent(
        "customer_messages",
        message_id,
        {
            "thread_id": thread_id,
            "contact_id": thread.get("contact_id"),
            "property_id": thread.get("property_id"),
            "document_kind": thread.get("last_document_kind"),
            "document_id": thread.get("last_document_id"),
            "sender_kind": "STAFF",
            "sender_id": user.get("id"),
            "sender_name": user.get("name") or "Floodman team",
            "body": message_body,
            "staff_read_at": now,
            "customer_read_at": None,
            "customer_email_status": "PENDING",
            "source": "FLOODMAN_CUSTOMER_PORTAL",
        },
        actor_id=str(user.get("id") or ""),
    )
    if not created:
        store.set_notice("That reply was already sent; Floodman did not create a duplicate.")
        return RedirectResponse(f"/office/messages?thread={quote(thread_id)}", status_code=303)
    store.update_record(
        "customer_threads",
        thread_id,
        {"status": "OPEN", "last_message_at": message.get("created_at"), "last_sender_kind": "STAFF"},
        actor_id=str(user.get("id") or ""),
    )
    email = str(contact.get("email") or contact.get("primaryEmail") or "").strip()
    portal_document = _portal_document_for_thread(thread)
    if not email:
        store.update_record("customer_messages", str(message["id"]), {"customer_email_status": "NO_EMAIL"}, actor_id=str(user.get("id") or ""))
        store.set_notice("Reply saved. Add a customer email address if they should receive email notifications.")
    elif not portal_document:
        store.update_record("customer_messages", str(message["id"]), {"customer_email_status": "NO_PORTAL_LINK"}, actor_id=str(user.get("id") or ""))
        store.set_notice("Reply saved, but a secure customer portal link is not available for email delivery.")
    else:
        portal_url = str(portal_document[1].get("public_url") or "") + "#messages"
        try:
            await providers.send_email(
                to=email,
                subject="Floodman replied to your secure message",
                text=f"The Floodman team replied to your customer portal message.\n\nRead and reply securely: {portal_url}",
                html=_payment_email_html("You have a new Floodman reply", "The Floodman team replied to your secure customer message.", portal_url, "Read secure reply"),
            )
            store.update_record("customer_messages", str(message["id"]), {"customer_email_status": "SENT", "customer_email_sent_at": datetime.now(UTC).isoformat()}, actor_id=str(user.get("id") or ""))
            store.set_notice("Reply sent. The customer portal was updated and an email notification was sent.")
        except Exception:
            store.update_record("customer_messages", str(message["id"]), {"customer_email_status": "FAILED"}, actor_id=str(user.get("id") or ""))
            store.set_notice("Reply saved in the portal, but the customer email notification could not be delivered.")
    return RedirectResponse(f"/office/messages?thread={quote(thread_id)}", status_code=303)


@app.post("/office/messages/send")
async def send_message(phone: str = Form(...), body: str = Form(...)) -> RedirectResponse:
    _require("messages.manage")
    try:
        await providers.send_sms(phone, body)
        store.set_notice("Local SMS sent and captured.")
    except Exception as exc:
        store.set_notice(f"SMS could not be sent: {exc}")
    return RedirectResponse("/office/messages", status_code=303)


@app.get("/office/receivables")
async def receivables_page() -> HTMLResponse:
    _require("receivables.view")
    state = await _state_page_data()
    cases = _rows(state.get("ar_cases"))
    local_due = [item for item in store.records("invoices") if int(item.get("balance_cents") or 0) > 0]
    rows = [[esc(item.get("invoice_number") or item.get("provider_invoice_id") or item.get("id")), badge(item.get("ar_status") or item.get("status")), money_cents(item.get("outstanding_cents") or item.get("balance_cents"), item.get("currency") or "USD"), esc(item.get("due_at") or ""), esc(item.get("next_reminder_at") or ""), esc(item.get("reminder_count") or 0)] for item in cases]
    local_rows = [[f"<a href='/office/invoices/{esc(item.get('id'))}'>{esc(item.get('invoice_number'))}</a>", badge(item.get("status")), money_cents(item.get("balance_cents")), esc(item.get("due_at") or ""), esc(item.get("send_channel") or "") ] for item in local_due]
    body = f"<div class='card'><h2>Automated accounts receivable</h2>{table(('Invoice','Status','Balance','Due','Next reminder','Sent'), rows)}</div><div class='card'><h2>Floodman Office open balances</h2>{table(('Invoice','Status','Balance','Due','Channel'), local_rows)}</div><div class='callout'>Invoices are due the moment they are sent. Production enrollment occurs through the orchestrator and signed payment webhook workflow; local Office invoices remain safe test records until that link is enabled.</div><div class='actions'><a class='button' href='{esc(settings.engineering_public_url)}/lab'>Open reminder simulator</a></div>"
    return _page("Receivables", body, "receivables")


@app.get("/office/alerts")
async def alerts_page() -> HTMLResponse:
    user = _require("alerts.view")
    user_id = str(user.get("id") or "")
    notifications = [item for item in store.records("notifications") if str(item.get("user_id") or "") == user_id]
    local_rows = []
    for item in notifications:
        action_url = str(item.get("action_url") or "")
        open_action = f"<a class='button small secondary' href='/office/alerts/{esc(item.get('id'))}/open'>Open</a>" if action_url.startswith("/office/") else ""
        read_action = (
            f"<form method='post' action='/office/alerts/{esc(item.get('id'))}/read'><button class='small'>Mark read</button></form>"
            if str(item.get("status") or "UNREAD").upper() == "UNREAD"
            else ""
        )
        local_rows.append([
            esc(str(item.get("created_at") or "")[:16].replace("T", " ")),
            badge(item.get("status") or "UNREAD", "warn" if str(item.get("status") or "UNREAD").upper() == "UNREAD" else "neutral"),
            esc(str(item.get("kind") or "GENERAL").replace("_", " ").title()),
            f"<b>{esc(item.get('title') or '')}</b><br><span class='muted'>{esc(item.get('body') or '')}</span>",
            badge(str(item.get("email_status") or "IN APP").replace("_", " ").title()),
            f"<div class='actions'>{open_action}{read_action}</div>",
        ])
    state = await _state_page_data()
    alerts = _rows(state.get("staff_alerts"))
    rows = [[esc(item.get("created_at") or ""), badge(item.get("severity") or item.get("alert_status") or "OPEN"), esc(item.get("alert_type") or item.get("type") or ""), esc(item.get("message") or item.get("summary") or "")] for item in alerts]
    unread = sum(1 for item in notifications if str(item.get("status") or "UNREAD").upper() == "UNREAD")
    mark_all = "<form method='post' action='/office/alerts/read-all'><button class='secondary'>Mark all read</button></form>" if unread else ""
    body = f"<div class='card'><div class='actions spread'><div><h2>Your Floodman notifications</h2><p class='muted'>Payment confirmations and customer messages appear here and in the mobile notifications list.</p></div>{mark_all}</div>{table(('Created','Status','Type','Notification','Email','Action'), local_rows)}</div><details class='card plain-details'><summary>Connected-service staff alerts</summary><div style='margin-top:12px'>{table(('Created','Severity','Type','Message'), rows)}</div></details>"
    return _page("Staff Alerts", body, "alerts")


@app.post("/office/alerts/{notification_id}/read")
def read_staff_notification(notification_id: str) -> RedirectResponse:
    user = _require("alerts.view")
    notification = store.record("notifications", notification_id)
    if not notification or str(notification.get("user_id") or "") != str(user.get("id") or ""):
        raise HTTPException(404, "Notification not found")
    store.update_record("notifications", notification_id, {"status": "READ", "read_at": datetime.now(UTC).isoformat()}, actor_id=str(user.get("id") or ""))
    return RedirectResponse("/office/alerts", status_code=303)


@app.get("/office/alerts/{notification_id}/open")
def open_staff_notification(notification_id: str) -> RedirectResponse:
    user = _require("alerts.view")
    notification = store.record("notifications", notification_id)
    if not notification or str(notification.get("user_id") or "") != str(user.get("id") or ""):
        raise HTTPException(404, "Notification not found")
    store.update_record("notifications", notification_id, {"status": "READ", "read_at": datetime.now(UTC).isoformat()}, actor_id=str(user.get("id") or ""))
    action_url = str(notification.get("action_url") or "")
    if not action_url.startswith("/office/"):
        action_url = "/office/alerts"
    return RedirectResponse(action_url, status_code=303)


@app.post("/office/alerts/read-all")
def read_all_staff_notifications() -> RedirectResponse:
    user = _require("alerts.view")
    user_id = str(user.get("id") or "")
    now = datetime.now(UTC).isoformat()
    for notification in store.records("notifications"):
        if str(notification.get("user_id") or "") == user_id and str(notification.get("status") or "UNREAD").upper() == "UNREAD":
            store.update_record("notifications", str(notification["id"]), {"status": "READ", "read_at": now}, actor_id=user_id)
    return RedirectResponse("/office/alerts", status_code=303)


def _list_items(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if value:
        return [str(value)]
    return []


def _report_section(title: str, value: Any) -> str:
    items = _list_items(value)
    if not items:
        return ""
    return f"<div class='report-section'><h3>{esc(title)}</h3><ul>{''.join(f'<li>{esc(item)}</li>' for item in items)}</ul></div>"


@app.get("/office/intelligence")
async def intelligence_page() -> HTMLResponse:
    _require("intelligence.view")
    try:
        targets = await providers.competitor_targets()
        reports = await providers.competitor_reports()
        error = ""
    except Exception as exc:
        targets, reports, error = [], [], str(exc)
    target_names = {str(item.get("id")): item.get("name") for item in targets}
    target_rows = []
    for item in targets:
        target_id = esc(item.get("id"))
        actions = ""
        if has_permission(_user(), "intelligence.manage"):
            actions = (
                f"<div class='actions'><form method='post' action='/office/intelligence/{target_id}/run'><button>Run now</button></form>"
                f"<a class='button secondary' href='/office/intelligence/{target_id}/edit'>Edit</a>"
                f"<form method='post' action='/office/intelligence/{target_id}/delete' onsubmit=\"return confirm('Delete this competitor and all of its reports?')\"><button class='danger'>Delete</button></form></div>"
            )
        target_rows.append([
            esc(item.get("name")),
            f"<a href='{esc(item.get('url'))}' target='_blank' rel='noreferrer'>{esc(item.get('url'))}</a>",
            badge("Enabled" if item.get("enabled", True) else "Disabled"),
            esc(item.get("frequency_hours") or 168),
            esc(item.get("last_run_at") or "Never"),
            esc(item.get("last_error") or ""),
            actions,
        ])
    report_cards = []
    for item in reports:
        report = item.get("report") or {}
        summary = report.get("executive_summary") or report.get("summary") or "Analysis completed."
        sections = "".join([
            _report_section("Floodman opportunities", report.get("floodman_opportunities")),
            _report_section("Competitor strengths", report.get("strengths")),
            _report_section("Weaknesses and market gaps", report.get("weaknesses_or_gaps")),
            _report_section("Services and offers", report.get("offers_and_prices")),
            _report_section("Sales talking points", report.get("sales_talking_points")),
            _report_section("Claims needing verification", report.get("claims_needing_human_verification")),
        ])
        changes = item.get("change_summary") or {}
        report_cards.append(f"<div class='card'><div class='actions spread'><div><h2>{esc(item.get('target_name') or target_names.get(str(item.get('target_id'))) or 'Competitor report')}</h2><p class='muted'>{esc(item.get('created_at') or '')}</p></div><div class='actions'>{badge(item.get('status') or 'COMPLETED')}<a class='button secondary' href='/office/intelligence/reports/{esc(item.get('id'))}'>Open evidence</a></div></div><p>{esc(summary)}</p><div class='grid two'>{sections}</div><details><summary>Evidence and raw report</summary>{json_pre({'changes': changes, 'report': report})}</details></div>")
    add_form = ""
    if has_permission(_user(), "intelligence.manage"):
        add_form = """<div class='card'><h2>Add competitor monitor</h2><form method='post' action='/office/intelligence/add'><div class='form-grid'><div class='field'><label>Name</label><input name='name' required></div><div class='field'><label>Public website URL</label><input type='url' name='url' placeholder='https://example.com' required></div><div class='field'><label>Category</label><input name='category' value='Waterproofing and restoration'></div><div class='field'><label>Frequency in hours</label><input type='number' name='frequency_hours' min='6' max='8760' value='168'></div><div class='field full'><label>Additional paths, comma separated</label><input name='additional_paths' placeholder='/services,/about,/financing'></div></div><button style='margin-top:12px'>Add monitor</button></form></div>"""
    error_html = f"<div class='callout danger'>{esc(error)}</div>" if error else ""
    body = f"{error_html}<div class='grid'><div class='card metric'><small>Monitored competitors</small><strong>{len(targets)}</strong></div><div class='card metric'><small>Reports</small><strong>{len(reports)}</strong></div><div class='card metric'><small>Automation</small><strong>Scheduled</strong></div></div>{add_form}<div class='card'><h2>Monitored competitors</h2>{table(('Name','URL','State','Hours','Last run','Last error','Actions'), target_rows)}</div>{''.join(report_cards) or '<div class=\'card\'><h2>No reports yet</h2><p>Add a public competitor website and run the first scan.</p></div>'}"
    return _page("AI Competitor Intelligence", body, "intelligence")


@app.post("/office/intelligence/add")
async def add_competitor(name: str = Form(...), url: str = Form(...), category: str = Form(default=""), frequency_hours: int = Form(default=168), additional_paths: str = Form(default="")) -> RedirectResponse:
    _require("intelligence.manage")
    paths = [value.strip() for value in additional_paths.split(",") if value.strip()]
    try:
        await providers.add_competitor({"name": name.strip(), "url": url.strip(), "category": category.strip() or None, "additional_paths": paths, "frequency_hours": frequency_hours})
        store.set_notice(f"Competitor target {name.strip()} added.")
    except Exception as exc:
        store.set_notice(f"Could not add competitor: {exc}")
    return RedirectResponse("/office/intelligence", status_code=303)


@app.post("/office/intelligence/{target_id}/run")
async def run_competitor(target_id: str) -> RedirectResponse:
    _require("intelligence.manage")
    try:
        result = await providers.run_competitor(target_id)
        store.set_notice("Competitor scan completed." if not result.get("unchanged") else "No public-site changes were detected.")
    except Exception as exc:
        store.set_notice(f"Competitor scan failed: {exc}")
    return RedirectResponse("/office/intelligence", status_code=303)

@app.get("/office/intelligence/{target_id}/edit")
async def edit_competitor_page(target_id: str) -> HTMLResponse:
    _require("intelligence.manage")
    try:
        item = await providers.competitor_target(target_id)
    except Exception as exc:
        raise HTTPException(404, f"Competitor monitor could not be loaded: {exc}") from exc
    paths = ",".join(item.get("additional_paths") or [])
    checked = "checked" if item.get("enabled", True) else ""
    body = f"""<div class='card'><div class='actions spread'><div><h2>Edit competitor monitor</h2><p>Update schedule, pages, or temporarily disable automated scans.</p></div><a class='button secondary' href='/office/intelligence'>Back</a></div>
    <form method='post' action='/office/intelligence/{esc(target_id)}/edit'><div class='form-grid'>
    <div class='field'><label>Name</label><input name='name' value='{esc(item.get('name'))}' required></div>
    <div class='field'><label>Public website URL</label><input type='url' name='url' value='{esc(item.get('url'))}' required></div>
    <div class='field'><label>Category</label><input name='category' value='{esc(item.get('category') or '')}'></div>
    <div class='field'><label>Frequency in hours</label><input type='number' name='frequency_hours' min='6' max='8760' value='{esc(item.get('frequency_hours') or 168)}'></div>
    <div class='field full'><label>Additional paths, comma separated</label><input name='additional_paths' value='{esc(paths)}'></div>
    <div class='field full'><label><input type='checkbox' name='enabled' value='true' {checked}> Monitor enabled</label></div>
    </div><button style='margin-top:12px'>Save monitor</button></form></div>"""
    return _page("Edit Competitor Monitor", body, "intelligence")


@app.post("/office/intelligence/{target_id}/edit")
async def edit_competitor(
    target_id: str,
    name: str = Form(...),
    url: str = Form(...),
    category: str = Form(default=""),
    frequency_hours: int = Form(default=168),
    additional_paths: str = Form(default=""),
    enabled: str | None = Form(default=None),
) -> RedirectResponse:
    _require("intelligence.manage")
    paths = [value.strip() for value in additional_paths.split(",") if value.strip()]
    try:
        await providers.update_competitor(target_id, {
            "name": name.strip(), "url": url.strip(), "category": category.strip() or None,
            "additional_paths": paths, "frequency_hours": frequency_hours, "enabled": enabled == "true",
        })
        store.set_notice(f"Competitor target {name.strip()} updated.")
    except Exception as exc:
        store.set_notice(f"Could not update competitor: {exc}")
    return RedirectResponse("/office/intelligence", status_code=303)


@app.post("/office/intelligence/{target_id}/delete")
async def delete_competitor(target_id: str) -> RedirectResponse:
    _require("intelligence.manage")
    try:
        await providers.delete_competitor(target_id)
        store.set_notice("Competitor monitor and its stored reports were deleted.")
    except Exception as exc:
        store.set_notice(f"Could not delete competitor: {exc}")
    return RedirectResponse("/office/intelligence", status_code=303)


@app.get("/office/intelligence/reports/{report_id}")
async def competitor_report_page(report_id: str) -> HTMLResponse:
    _require("intelligence.view")
    try:
        item = await providers.competitor_report(report_id)
    except Exception as exc:
        raise HTTPException(404, f"Competitor report could not be loaded: {exc}") from exc
    report = item.get("report") or {}
    evidence = item.get("evidence") or []
    rows = [[
        f"<a href='{esc(entry.get('url'))}' target='_blank' rel='noreferrer'>{esc(entry.get('title') or entry.get('url'))}</a>",
        f"<code>{esc(entry.get('sha256'))}</code>", esc(entry.get("captured_at") or "")
    ] for entry in evidence]
    body = f"""<div class='actions spread'><div><h1>{esc(item.get('target_name') or 'Competitor report')}</h1><p>{esc(item.get('created_at') or '')}</p></div><a class='button secondary' href='/office/intelligence'>Back</a></div>
    <div class='card'><h2>Executive summary</h2><p>{esc(report.get('executive_summary') or 'Analysis completed.')}</p></div>
    <div class='grid two'>{_report_section('Floodman opportunities', report.get('floodman_opportunities'))}{_report_section('Competitor strengths', report.get('strengths'))}{_report_section('Weaknesses and gaps', report.get('weaknesses_or_gaps'))}{_report_section('Services and offers', report.get('offers_and_prices'))}{_report_section('Sales talking points', report.get('sales_talking_points'))}{_report_section('Claims requiring human verification', report.get('claims_needing_human_verification'))}</div>
    <div class='card'><h2>Captured evidence</h2>{table(('Source','SHA-256','Captured'), rows)}</div>
    <div class='card'><details><summary>Complete extracted data and report JSON</summary>{json_pre({'change_summary': item.get('change_summary'), 'report': report, 'extracted_data': item.get('extracted_data'), 'model': item.get('model')})}</details></div>"""
    return _page("Competitor Evidence", body, "intelligence")


# ======================================================================
# Full operations administration
# ======================================================================


def _local_record_or_404(kind: str, record_id: str) -> dict[str, Any]:
    record = store.record(kind, record_id)
    if not record:
        raise HTTPException(404, "This record is imported or provider-owned. Edit it in the full Floodman ERP application.")
    return record


@app.get("/office/platform")
async def gauzy_suite_page() -> HTMLResponse:
    _require("apps.view")
    try:
        context = await providers.gauzy_context()
        connection = badge("CONNECTED", "good")
        context_error = ""
    except Exception as exc:
        context = {
            "tenant_id": settings.gauzy_tenant_id,
            "organization_id": settings.gauzy_organization_id,
            "from_organization_id": settings.gauzy_from_organization_id,
            "sync_enabled": settings.gauzy_sync_enabled,
        }
        connection = badge("NOT RUNNING", "warn")
        context_error = str(exc)
    mappings = store.external_mappings("gauzy")
    modules = [
        "CRM contacts and clients", "Employees and member invitations", "Teams and departments",
        "Time clock, activity, timesheets and approvals", "Projects, tasks and work management",
        "Estimates, invoices, payments and proposals", "Income, expenses and accounting views",
        "Sales pipelines and deals", "Goals, KPIs and reports", "Candidates, interviews and HR",
        "Time off, policies and approvals", "Inventory, equipment, vendors and organization settings",
        "Email templates and email history", "Roles and permissions", "Imports, exports and integrations",
    ]
    status_html = f"""<div class='grid'>
    <div class='card metric'><small>Floodman Hub</small><strong>{connection}</strong></div>
    <div class='card metric'><small>Tenant ID</small><strong style='font-size:14px'>{esc(context.get('tenant_id') or 'Not discovered')}</strong></div>
    <div class='card metric'><small>Organization ID</small><strong style='font-size:14px'>{esc(context.get('organization_id') or 'Not discovered')}</strong></div>
    <div class='card metric'><small>Mapped records</small><strong>{len(mappings)}</strong></div></div>"""
    error_html = f"<div class='callout warning'><b>Floodman ERP is not reachable yet.</b><br>{esc(context_error)}<br><br>Run <code>Start-Floodman-Full-System.cmd</code> from C:\\FloodmanLab.</div>" if context_error else ""
    sync_status = badge("AUTOMATIC", "good") if settings.gauzy_sync_enabled else badge("LOCKED", "warn")
    sync_button = ""
    if has_permission(_user(), "connections.manage") and settings.gauzy_sync_enabled:
        sync_button = "<form method='post' action='/office/platform/sync'><button class='good'>Run recovery / historical sync</button></form>"
    elif has_permission(_user(), "connections.manage"):
        sync_button = "<div class='callout'><b>Synchronization is locked.</b> Enable ERP synchronization in the server Startup settings, then restart Floodman.</div>"
    body = f"""{status_html}{error_html}
    <div class='grid two'><div class='card'><h2>Floodman ERP is the main hub</h2><p>Open the complete Floodman ERP with the Floodman Operations launcher injected into the same interface. Floodman ERP remains fully native underneath, including employees, time tracking, projects, estimates, invoices, payments, inventory, reports and permissions.</p><div class='actions'><a class='button good' href='{esc(settings.gauzy_hub_url)}' target='_blank' rel='noreferrer'>Open Floodman Hub</a><a class='button secondary' href='/office/apps'>Application directory</a></div><hr><p><b>Primary owner:</b> <span class='mono'>{esc(settings.gauzy_admin_email)}</span></p><p class='muted'>Clean business mode is non-demo. Passwords are never shown in this interface. Create staff accounts through Floodman ERP Employees &amp; Invitations.</p></div>
    <div class='card'><h2>Automatic RoomFlow → Floodman data path</h2><p>Bridge state: {sync_status}</p><p>New RoomFlow jobs are sent directly through the Floodman workflow engine into Floodman ERP. The bridge creates or reuses the customer, creates a Floodman project for the service property/job, then creates the estimate and attaches invoice items and payments to the same project.</p><p>The button below is only for recovery, local Office records and historical Townsquare imports.</p>{sync_button}</div></div>
    <div class='card'><h2>Native Floodman ERP modules included</h2><div class='grid two'>{''.join(f"<div class='callout success'>{esc(item)}</div>" for item in modules)}</div></div>
    <div class='card'><h2>Resolved Floodman workspace</h2><div class='grid two'><div><small>Workspace</small><p class='mono'>{esc(context.get('tenant_id') or 'Automatically discovered')}</p></div><div><small>Organization</small><p class='mono'>{esc(context.get('organization_id') or 'Automatically discovered')}</p></div></div><p class='muted'>Floodman discovers the active workspace and organization automatically. No upstream product configuration is exposed in the normal interface.</p></div>"""
    return _page("Floodman ERP", body, "platform")


@app.post("/office/platform/sync")
async def sync_full_gauzy() -> HTMLResponse:
    """Recovery and historical-import synchronization into the Floodman ERP suite.

    Normal RoomFlow jobs are synchronized by the orchestrator as they are created. This
    owner-only action catches locally created Office records and historical Townsquare
    imports, preserving stable provider mappings so it remains safe to run repeatedly.
    """
    actor = _require("connections.manage")
    if not settings.gauzy_sync_enabled:
        raise HTTPException(409, "Floodman ERP synchronization is locked in .env.windows")
    context = await providers.gauzy_context()
    if not context.get("tenant_id") or not context.get("organization_id"):
        raise HTTPException(409, "Floodman ERP tenant and organization IDs could not be discovered.")

    merged = _merge_archive_state({})
    contacts = store.records("contacts") + _rows(merged.get("gauzy_contacts"))
    properties = store.records("properties") + _rows(merged.get("properties"))
    estimates = store.records("estimates") + [
        item for item in _rows(merged.get("gauzy_invoices")) if item.get("isEstimate") is True
    ]
    invoices = store.records("invoices") + [
        item for item in _rows(merged.get("gauzy_invoices")) if item.get("isEstimate") is not True
    ]
    payments = store.records("payments") + _rows(merged.get("gauzy_payments"))
    summary: dict[str, Any] = {
        "contacts": 0,
        "projects": 0,
        "estimates": 0,
        "invoices": 0,
        "payments": 0,
        "skipped": 0,
        "errors": [],
    }

    legacy_fields = {
        "contact": ("legacy_contact_id", "legacyContactId"),
        "property": ("legacy_property_id", "legacyPropertyId"),
        "estimate": ("legacy_estimate_id", "legacyEstimateId"),
        "invoice": ("legacy_invoice_id", "legacyInvoiceId"),
        "payment": ("legacy_payment_id", "legacyPaymentId"),
    }

    def source_identifier(kind: str, item: dict[str, Any]) -> str:
        value = item.get("id")
        if value:
            return str(value)
        for field in legacy_fields.get(kind, ()):
            if item.get(field):
                return str(item[field])
        return ""

    def identity(kind: str, item: dict[str, Any]) -> str:
        return f"{kind}:{source_identifier(kind, item)}"

    def alias(mapping: dict[str, str], *keys: Any, value: str) -> None:
        for key in keys:
            key_text = str(key or "").strip()
            if key_text:
                mapping[key_text] = value

    contact_external: dict[str, str] = {}
    for item in contacts:
        source_id = source_identifier("contact", item)
        key = identity("contact", item)
        if not source_id:
            summary["errors"].append(f"Contact {item.get('name') or 'unknown'}: source ID is missing")
            continue
        external = store.external_mapping("gauzy", key)
        if not external:
            try:
                created = await providers.full_gauzy_create_contact(item, context)
                external = str(created.get("id") or "")
                if not external:
                    raise RuntimeError("Floodman ERP did not return a contact ID")
                store.set_external_mapping("gauzy", key, external)
                summary["contacts"] += 1
            except Exception as exc:
                summary["errors"].append(f"Contact {item.get('name') or source_id}: {exc}")
                continue
        else:
            summary["skipped"] += 1
        legacy_contact = str(item.get("legacy_contact_id") or item.get("legacyContactId") or "")
        alias(
            contact_external,
            source_id,
            item.get("id"),
            legacy_contact,
            f"archive-contact:{legacy_contact}" if legacy_contact else "",
            value=external,
        )
        local = store.record("contacts", str(item.get("id") or ""))
        if local and local.get("full_gauzy_id") != external:
            store.update_record(
                "contacts",
                str(item.get("id")),
                {"full_gauzy_id": external},
                actor_id=str(actor.get("id")),
            )

    project_external: dict[str, str] = {}
    for item in properties:
        source_id = source_identifier("property", item)
        key = identity("property", item)
        if not source_id:
            summary["errors"].append(f"Property {item.get('name') or 'unknown'}: source ID is missing")
            continue
        local_contact = str(item.get("contact_id") or item.get("organizationContactId") or "")
        if not local_contact:
            legacy_contact = str(item.get("legacy_contact_id") or item.get("legacyContactId") or "")
            local_contact = f"archive-contact:{legacy_contact}" if legacy_contact else ""
        external_contact = contact_external.get(local_contact) or store.external_mapping(
            "gauzy", f"contact:{local_contact}"
        )
        if not external_contact:
            summary["errors"].append(f"Property {item.get('name') or source_id}: customer mapping is missing")
            continue
        external = store.external_mapping("gauzy", key)
        if not external:
            try:
                created = await providers.full_gauzy_create_project(item, context, contact_id=external_contact)
                external = str(created.get("id") or "")
                if not external:
                    raise RuntimeError("Floodman ERP did not return a project ID")
                store.set_external_mapping("gauzy", key, external)
                summary["projects"] += 1
            except Exception as exc:
                summary["errors"].append(f"Property {item.get('name') or source_id}: {exc}")
                continue
        else:
            summary["skipped"] += 1
        legacy_property = str(item.get("legacy_property_id") or item.get("legacyPropertyId") or "")
        alias(
            project_external,
            source_id,
            item.get("id"),
            legacy_property,
            f"archive-property:{legacy_property}" if legacy_property else "",
            value=external,
        )
        local = store.record("properties", str(item.get("id") or ""))
        if local and local.get("full_gauzy_id") != external:
            store.update_record(
                "properties",
                str(item.get("id")),
                {"full_gauzy_id": external},
                actor_id=str(actor.get("id")),
            )

    financial_project: dict[str, str] = {}

    async def sync_financial(kind: str, rows: list[dict[str, Any]], is_estimate: bool) -> None:
        for item in rows:
            source_id = source_identifier(kind, item)
            key = identity(kind, item)
            if not source_id:
                summary["errors"].append(f"{kind.title()}: source ID is missing")
                continue
            existing = store.external_mapping("gauzy", key)
            local_property = str(item.get("property_id") or item.get("organizationProjectId") or "")
            if not local_property:
                legacy_property = str(item.get("legacy_property_id") or item.get("legacyPropertyId") or "")
                local_property = f"archive-property:{legacy_property}" if legacy_property else ""
            external_project = project_external.get(local_property) or store.external_mapping(
                "gauzy", f"property:{local_property}"
            )
            if existing:
                summary["skipped"] += 1
                alias(financial_project, source_id, item.get("id"), key, value=external_project or "")
                continue
            local_contact = str(item.get("contact_id") or item.get("organizationContactId") or "")
            if not local_contact:
                legacy = str(item.get("legacy_contact_id") or item.get("legacyContactId") or "")
                local_contact = f"archive-contact:{legacy}" if legacy else ""
            external_contact = contact_external.get(local_contact) or store.external_mapping(
                "gauzy", f"contact:{local_contact}"
            )
            if not external_contact:
                summary["errors"].append(f"{kind.title()} {source_id}: customer mapping is missing")
                continue
            try:
                created = await providers.full_gauzy_create_invoice(
                    item,
                    context,
                    contact_id=external_contact,
                    is_estimate=is_estimate,
                    project_id=external_project,
                )
                external_id = str(created.get("id") or "")
                if not external_id:
                    raise RuntimeError("Floodman ERP did not return an ID")
                store.set_external_mapping("gauzy", key, external_id)
                summary[kind + "s"] += 1
                alias(financial_project, source_id, item.get("id"), key, value=external_project or "")
                local = store.record(kind + "s", str(item.get("id") or ""))
                if local:
                    store.update_record(
                        kind + "s",
                        str(item.get("id")),
                        {"full_gauzy_id": external_id, "full_gauzy_project_id": external_project},
                        actor_id=str(actor.get("id")),
                    )
            except Exception as exc:
                summary["errors"].append(
                    f"{kind.title()} {item.get('estimate_number') or item.get('invoice_number') or source_id}: {exc}"
                )

    await sync_financial("estimate", estimates, True)
    await sync_financial("invoice", invoices, False)

    for item in payments:
        source_id = source_identifier("payment", item)
        key = identity("payment", item)
        if not source_id:
            summary["errors"].append("Payment: source ID is missing")
            continue
        if store.external_mapping("gauzy", key):
            summary["skipped"] += 1
            continue
        local_invoice = str(item.get("invoice_id") or "")
        if not local_invoice:
            legacy = str(item.get("legacy_invoice_id") or item.get("legacyInvoiceId") or "")
            local_invoice = f"archive-invoice:{legacy}" if legacy else ""
        external_invoice = store.external_mapping("gauzy", f"invoice:{local_invoice}")
        if not external_invoice:
            summary["errors"].append(f"Payment {source_id}: invoice mapping is missing")
            continue
        local_contact = str(item.get("contact_id") or item.get("organizationContactId") or "")
        if not local_contact:
            legacy_contact = str(item.get("legacy_contact_id") or item.get("legacyContactId") or "")
            local_contact = f"archive-contact:{legacy_contact}" if legacy_contact else ""
        external_contact = contact_external.get(local_contact)
        project_id = financial_project.get(local_invoice) or financial_project.get(f"invoice:{local_invoice}")
        if not project_id:
            local_property = str(item.get("property_id") or "")
            project_id = project_external.get(local_property)
        try:
            created = await providers.full_gauzy_create_payment(
                item,
                context,
                invoice_id=external_invoice,
                contact_id=external_contact,
                project_id=project_id,
            )
            external_id = str(created.get("id") or "")
            if external_id:
                store.set_external_mapping("gauzy", key, external_id)
            summary["payments"] += 1
        except Exception as exc:
            summary["errors"].append(f"Payment {source_id}: {exc}")

    store.set_notice(
        f"Floodman ERP recovery sync finished: {summary['contacts']} contacts, {summary['projects']} projects, "
        f"{summary['estimates']} estimates, {summary['invoices']} invoices, {summary['payments']} payments; "
        f"{len(summary['errors'])} errors."
    )
    result = f"<div class='card'><h2>Floodman ERP synchronization result</h2>{json_pre(summary)}<div class='actions'><a class='button' href='/office/gauzy'>Return</a><a class='button good' href='{esc(settings.gauzy_hub_url)}' target='_blank'>Open Floodman Hub</a></div></div>"
    return _page("Floodman ERP Synchronization", result, "gauzy")


@app.get("/office/signing")
def signing_suite_page() -> HTMLResponse:
    _require("documents.view")
    body = f"""<div class='grid two'><div class='card'><h2>Floodman document workflow</h2><p>Create a PDF, select the customer, choose Work Authorization, Change Order, Completion of Service, or a custom type, then send it through the local signing workflow.</p><div class='actions'><a class='button' href='/office/documents'>Create signing request</a><a class='button secondary' href='{esc(settings.engineering_public_url)}/lab' target='_blank'>Open workflow lab</a></div></div><div class='card'><h2>Full Documenso application</h2><p>The full-system profile also starts the genuine signing application for reusable templates, teams, recipients, fields, and signing history.</p><a class='button good' href='{esc(settings.documenso_web_url)}' target='_blank'>Open Documenso</a><p class='muted'>Create the first local account on its sign-up page. Verification email appears in Mailpit.</p></div></div><div class='card'><h2>Document types</h2><div class='grid'><div class='callout'>Work Authorization and deposit terms</div><div class='callout'>Change Orders and revised contract totals</div><div class='callout'>Completion of Service and final-balance release</div><div class='callout'>Custom disclosures, warranties, inspection forms, and acknowledgements</div></div></div>"""
    return _page("Documents & Signing Suite", body, "signing")


@app.get("/office/contacts/{contact_id}/edit")
def edit_contact_page(contact_id: str) -> HTMLResponse:
    _require("contacts.manage")
    item = _local_record_or_404("contacts", contact_id)
    body = f"""<div class='card'><h2>Edit contact</h2><form method='post' action='/office/contacts/{esc(contact_id)}/edit'><div class='form-grid three'><div class='field'><label>First name</label><input name='first_name' value='{esc(item.get('first_name'))}' required></div><div class='field'><label>Last name</label><input name='last_name' value='{esc(item.get('last_name'))}' required></div><div class='field'><label>Company</label><input name='company' value='{esc(item.get('company'))}'></div><div class='field'><label>Email</label><input type='email' name='email' value='{esc(item.get('email'))}'></div><div class='field'><label>Phone</label><input name='phone' value='{esc(item.get('phone'))}'></div><div class='field'><label>Lead source</label><input name='lead_source' value='{esc(item.get('lead_source'))}'></div><div class='field full'><label>Profile summary</label><textarea name='notes'>{esc(item.get('notes'))}</textarea></div><div class='field full'><label>Tags</label><input name='tags' value='{esc(', '.join(item.get('tags') or []))}' placeholder='VIP, insurance, repeat customer'></div></div><div class='actions' style='margin-top:12px'><button>Save changes</button><a class='button secondary' href='/office/contacts/{esc(contact_id)}'>Cancel</a></div></form></div><div class='card danger'><h2>Delete contact</h2><p>Deletion is blocked when local properties, estimates, or invoices still reference this contact.</p><form method='post' action='/office/contacts/{esc(contact_id)}/delete'><button class='danger'>Delete contact</button></form></div>"""
    return _page("Edit Contact", body, "contacts")


@app.post("/office/contacts/{contact_id}/edit")
def update_contact(contact_id: str, first_name: str = Form(...), last_name: str = Form(...), company: str = Form(default=""), email: str = Form(default=""), phone: str = Form(default=""), lead_source: str = Form(default=""), notes: str = Form(default=""), tags: str = Form(default="")) -> RedirectResponse:
    actor = _require("contacts.manage")
    _local_record_or_404("contacts", contact_id)
    name = " ".join(filter(None, [first_name.strip(), last_name.strip()]))
    store.update_record("contacts", contact_id, {"first_name": first_name.strip(), "last_name": last_name.strip(), "name": name, "company": company.strip(), "email": email.strip(), "phone": phone.strip(), "lead_source": lead_source.strip(), "notes": notes.strip(), "tags": [value.strip()[:60] for value in re.split(r"[,;\n]+", tags) if value.strip()][:30]}, actor_id=str(actor.get("id")))
    store.set_notice("Contact updated.")
    return RedirectResponse(f"/office/contacts/{contact_id}", status_code=303)


@app.post("/office/contacts/{contact_id}/delete")
def delete_contact(contact_id: str) -> RedirectResponse:
    _require("contacts.manage")
    _local_record_or_404("contacts", contact_id)
    related = any(str(item.get("contact_id")) == contact_id for kind in ("properties", "estimates", "invoices") for item in store.records(kind))
    if related:
        store.set_notice("Contact cannot be deleted while local properties, estimates, or invoices reference it.")
        return RedirectResponse(f"/office/contacts/{contact_id}/edit", status_code=303)
    store.delete_record("contacts", contact_id)
    store.set_notice("Contact deleted.")
    return RedirectResponse("/office/contacts", status_code=303)


@app.get("/office/properties/{property_id}/edit")
def edit_property_page(property_id: str) -> HTMLResponse:
    _require("properties.manage")
    item = _local_record_or_404("properties", property_id)
    contact_id = str(item.get("contact_id") or "")
    body = f"""<div class='card'><h2>Edit property</h2><form method='post' action='/office/properties/{esc(property_id)}/edit'><div class='form-grid three'><div class='field'><label>Property name</label><input name='name' value='{esc(item.get('name'))}' required></div><div class='field'><label>Property type</label><input name='property_type' value='{esc(item.get('property_type'))}'></div>{_entity_picker(kind='contacts', name='contact_id', label='Customer', selected_id=contact_id, selected_label=_contact_name(contact_id), required=True)}<div class='field full'><label>Service street</label><input name='service_street' value='{esc(item.get('service_street'))}' required></div><div class='field'><label>City</label><input name='service_city' value='{esc(item.get('service_city'))}' required></div><div class='field'><label>State</label><input name='service_state' value='{esc(item.get('service_state'))}' required></div><div class='field'><label>Postal code</label><input name='service_postal_code' value='{esc(item.get('service_postal_code'))}' required></div><div class='field'><label>Insurance company</label><input name='insurance_company' value='{esc(item.get('insurance_company'))}'></div><div class='field'><label>Claim number</label><input name='claim_number' value='{esc(item.get('claim_number'))}'></div><div class='field full'><label>Notes</label><textarea name='notes'>{esc(item.get('notes'))}</textarea></div></div><div class='actions' style='margin-top:12px'><button>Save changes</button><a class='button secondary' href='/office/properties/{esc(property_id)}'>Cancel</a></div></form></div><div class='card danger'><form method='post' action='/office/properties/{esc(property_id)}/delete'><button class='danger'>Delete property</button></form></div>"""
    return _page("Edit Property", body, "properties")


@app.post("/office/properties/{property_id}/edit")
async def update_property(property_id: str, contact_id: str = Form(...), name: str = Form(...), property_type: str = Form(default="Residential"), service_street: str = Form(...), service_city: str = Form(...), service_state: str = Form(default="MI"), service_postal_code: str = Form(...), insurance_company: str = Form(default=""), claim_number: str = Form(default=""), notes: str = Form(default="")) -> RedirectResponse:
    actor = _require("properties.manage")
    _local_record_or_404("properties", property_id)
    _ensure_local_contact(contact_id, await _state_page_data())
    store.update_record("properties", property_id, {"contact_id": contact_id, "name": name.strip(), "property_name": name.strip(), "property_type": property_type.strip(), "service_street": service_street.strip(), "service_city": service_city.strip(), "service_state": service_state.strip(), "service_postal_code": service_postal_code.strip(), "insurance_company": insurance_company.strip(), "claim_number": claim_number.strip(), "notes": notes.strip()}, actor_id=str(actor.get("id")))
    store.set_notice("Property updated.")
    return RedirectResponse(f"/office/properties/{property_id}", status_code=303)


@app.post("/office/properties/{property_id}/delete")
def delete_property(property_id: str) -> RedirectResponse:
    _require("properties.manage")
    _local_record_or_404("properties", property_id)
    related = any(str(item.get("property_id")) == property_id for kind in ("estimates", "invoices") for item in store.records(kind))
    if related:
        store.set_notice("Property cannot be deleted while local estimates or invoices reference it.")
        return RedirectResponse(f"/office/properties/{property_id}/edit", status_code=303)
    store.delete_record("properties", property_id)
    store.set_notice("Property deleted.")
    return RedirectResponse("/office/properties", status_code=303)


@app.get("/office/estimates/{estimate_id}/edit")
def edit_estimate_page(estimate_id: str) -> HTMLResponse:
    _require("estimates.manage")
    item = _local_record_or_404("estimates", estimate_id)
    deposit_type = str(item.get("deposit_type") or "PERCENT").upper()
    due_stage = str(item.get("deposit_due_stage") or "AFTER_AUTHORIZATION").upper()
    contact_id = str(item.get("contact_id") or "")
    property_id = str(item.get("property_id") or "")
    contact_link = f"<a href='/office/contacts/{esc(contact_id)}'>{esc(_contact_name(contact_id))}</a>" if contact_id else "Not linked"
    property_record = store.record("properties", property_id) if property_id else None
    property_link = f"<a href='/office/properties/{esc(property_id)}'>{esc(_property_label(property_record or {}))}</a>" if property_id else "Not linked"
    body = f"""<div class='actions'><a class='button secondary' href='/office/estimates/{esc(estimate_id)}'>Back to estimate</a><a class='button secondary' href='/office/estimates'>Estimate list</a></div><div class='card'><div class='estimate-linked-records'><div><small>Customer</small><b>{contact_link}</b></div><div><small>Service property</small><b>{property_link}</b></div></div></div><div class='card'><h2>Edit estimate</h2><form method='post' action='/office/estimates/{esc(estimate_id)}/edit' data-estimate-edit-form><div class='form-grid three'><div class='field'><label>Estimate number</label><input name='estimate_number' value='{esc(item.get('estimate_number'))}' required></div><div class='field two-wide'><label>Title</label><input name='title' value='{esc(item.get('title'))}' required></div><div class='field full'><label>Project summary</label><textarea name='project_summary'>{esc(item.get('project_summary') or item.get('summary') or '')}</textarea></div><div class='field'><label>Estimated duration</label><input name='estimated_duration' value='{esc(item.get('estimated_duration') or '')}'></div><div class='field'><label>Deposit requirement</label><select name='deposit_type'><option value='PERCENT' {'selected' if deposit_type == 'PERCENT' else ''}>Percentage</option><option value='FIXED' {'selected' if deposit_type == 'FIXED' else ''}>Fixed amount</option><option value='NONE' {'selected' if deposit_type == 'NONE' else ''}>No deposit</option></select></div><div class='field'><label>Deposit percent</label><input type='number' name='deposit_percent' min='0' max='100' step='0.01' value='{esc(item.get('deposit_percent') if item.get('deposit_percent') is not None else 50)}'></div><div class='field'><label>Fixed deposit amount</label><input type='number' name='deposit_fixed_amount' min='0' step='0.01' value='{int(item.get('deposit_fixed_cents') or 0)/100:.2f}'></div><div class='field'><label>Deposit becomes payable</label><select name='deposit_due_stage'><option value='AFTER_AUTHORIZATION' {'selected' if due_stage == 'AFTER_AUTHORIZATION' else ''}>After authorization</option><option value='IMMEDIATELY' {'selected' if due_stage == 'IMMEDIATELY' else ''}>When estimate is sent</option></select></div><div class='field'><label>Expiration days</label><input type='number' name='expiration_days' min='1' max='365' value='{esc(item.get('expiration_days') or 30)}'></div><div class='field full'><label>Project assumptions</label><textarea name='assumptions'>{esc(item.get('assumptions') or '')}</textarea></div><div class='field full'><label>Not included unless listed</label><textarea name='exclusions'>{esc(item.get('exclusions') or '')}</textarea></div><div class='field full'><label>Customer-facing notes</label><textarea name='customer_notes'>{esc(item.get('customer_notes') or '')}</textarea></div><div class='field full'>{_estimate_builder_html(item, default_section=str(item.get('title') or 'Scope of Work'))}</div><div class='field full'><label>Terms</label><textarea name='terms'>{esc(item.get('terms'))}</textarea></div></div><div class='actions' style='margin-top:12px'><button type='submit' data-estimate-submit>Save draft changes</button><a class='button secondary' href='/office/estimates/{esc(estimate_id)}'>Cancel</a></div></form></div><div class='card'><div class='actions'><form method='post' action='/office/estimates/{esc(estimate_id)}/send'><button>Send Floodman estimate</button></form><form method='post' action='/office/estimates/{esc(estimate_id)}/accept'><button class='good'>Mark accepted</button></form><form method='post' action='/office/estimates/{esc(estimate_id)}/delete'><button class='danger'>Delete draft</button></form></div></div>"""
    return _page("Edit Estimate", body, "estimates")


@app.post("/office/estimates/{estimate_id}/edit")
def update_estimate(
    estimate_id: str, estimate_number: str = Form(...), title: str = Form(...), estimate_payload: str = Form(...),
    project_summary: str = Form(default=""), estimated_duration: str = Form(default=""),
    assumptions: str = Form(default=""), exclusions: str = Form(default=""), customer_notes: str = Form(default=""),
    deposit_type: str = Form(default="PERCENT"), deposit_percent: float = Form(default=50.0),
    deposit_fixed_amount: str = Form(default="0"), deposit_due_stage: str = Form(default="AFTER_AUTHORIZATION"),
    expiration_days: int = Form(default=30), terms: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("estimates.manage")
    item = _local_record_or_404("estimates", estimate_id)
    if str(item.get("status") or "DRAFT").upper() not in {"DRAFT", "SENT", "VIEWED"}:
        store.set_notice("Accepted or converted estimates are immutable. Create a revision or Change Order instead.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    try:
        sections, lines, total_cents = normalize_document_payload(estimate_payload, title=title)
        lines = _save_custom_catalog_lines(lines, str(actor.get("id")))
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/estimates/{estimate_id}/edit", status_code=303)
    updated = store.update_record("estimates", estimate_id, {
        "estimate_number": estimate_number.strip(), "title": title.strip(), "sections": sections,
        "line_items": lines, "total_cents": total_cents, "summary": project_summary.strip(),
        "project_summary": project_summary.strip(), "estimated_duration": estimated_duration.strip(),
        "assumptions": assumptions.strip(), "exclusions": exclusions.strip(), "customer_notes": customer_notes.strip(),
        "deposit_type": deposit_type.upper() if deposit_type.upper() in {"PERCENT", "FIXED", "NONE"} else "PERCENT",
        "deposit_percent": max(0, min(100, float(deposit_percent))),
        "deposit_fixed_cents": _parse_money(deposit_fixed_amount) if str(deposit_fixed_amount).strip() else 0,
        "deposit_due_stage": deposit_due_stage.upper() if deposit_due_stage.upper() in {"AFTER_AUTHORIZATION", "IMMEDIATELY"} else "AFTER_AUTHORIZATION",
        "deposit_payable": deposit_due_stage.upper() == "IMMEDIATELY" or bool(item.get("deposit_payable")),
        "expiration_days": max(1, int(expiration_days)), "terms": terms.strip(),
    }, actor_id=str(actor.get("id")))
    deposit_values = _estimate_payment_values(updated)
    store.update_record("estimates", estimate_id, {"deposit_balance_cents": max(0, int(deposit_values["deposit_cents"]) - int(deposit_values["paid_cents"]))}, actor_id=str(actor.get("id")))
    store.set_notice("Estimate details, headers, line items, and deposit terms updated.")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/send")
async def send_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("estimates.manage")
    document = _local_record_or_404("estimates", estimate_id)
    if (
        str(document.get("publication_status") or "").upper() == "UNPUBLISHED"
        or str(document.get("pricing_status") or "PRICED").upper() != "PRICED"
        or int(document.get("total_cents") or 0) <= 0
    ):
        store.set_notice("This call-intake draft cannot be sent until staff add verified measurements, line items, and pricing.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    if str(document.get("deposit_due_stage") or "AFTER_AUTHORIZATION").upper() == "IMMEDIATELY":
        document = store.update_record("estimates", estimate_id, {"deposit_payable": True}, actor_id=str(actor.get("id")))
    try:
        updated, recipient = await _send_customer_document("estimate", document, actor_id=str(actor.get("id")))
        values = _estimate_payment_values(updated)
        detail = f" A secure deposit button for {money_cents(values['due_cents'])} is included." if values["payable"] and int(values["due_cents"]) else " The deposit button will activate after authorization."
        store.set_notice(f"Floodman estimate sent to {recipient}.{detail}")
    except Exception as exc:
        store.set_notice(f"Estimate was not sent: {exc}")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/accept")
def accept_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("estimates.manage")
    estimate = _local_record_or_404("estimates", estimate_id)
    if (
        str(estimate.get("publication_status") or "").upper() == "UNPUBLISHED"
        or str(estimate.get("pricing_status") or "PRICED").upper() != "PRICED"
        or int(estimate.get("total_cents") or 0) <= 0
    ):
        store.set_notice("This call-intake draft cannot be accepted until staff verify and price the work.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    store.update_record("estimates", estimate_id, {"status": "ACCEPTED", "accepted_at": datetime.now(UTC).isoformat(), "deposit_payable": True}, actor_id=str(actor.get("id")))
    store.set_notice("Estimate accepted. The requested deposit is now payable and the estimate can be converted into an invoice.")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/delete")
def delete_estimate(estimate_id: str) -> RedirectResponse:
    _require("estimates.manage")
    item = _local_record_or_404("estimates", estimate_id)
    if str(item.get("status") or "DRAFT").upper() not in {"DRAFT", "SENT", "VIEWED"}:
        store.set_notice("Accepted or converted estimates cannot be deleted.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    store.delete_record("estimates", estimate_id)
    store.set_notice("Estimate deleted.")
    return RedirectResponse("/office/estimates", status_code=303)


@app.get("/office/invoices/{invoice_id}/edit")
def edit_invoice_page(invoice_id: str) -> HTMLResponse:
    _require("invoices.manage")
    item = _local_record_or_404("invoices", invoice_id)
    is_draft = str(item.get("status") or "DRAFT").upper() == "DRAFT"
    edit_form = f"""<div class='card'><h2>Edit draft invoice</h2><form method='post' action='/office/invoices/{esc(invoice_id)}/edit'><div class='form-grid'><div class='field'><label>Invoice number</label><input name='invoice_number' value='{esc(item.get('invoice_number'))}' required></div><div class='field'><label>Title</label><input name='title' value='{esc(item.get('title'))}' required></div><div class='field full'>{_estimate_builder_html(item, default_section=str(item.get('title') or 'Completed Scope'))}</div><div class='field full'><label>Terms</label><textarea name='terms'>{esc(item.get('terms'))}</textarea></div></div><button style='margin-top:12px'>Save draft</button></form></div>""" if is_draft else "<div class='callout warning'>Sent financial records are not edited in place. Void the invoice or issue a corrected invoice / credit according to company policy.</div>"
    actions = f"""<div class='card'><div class='actions'>{f"<form method='post' action='/office/invoices/{esc(invoice_id)}/send'><button class='good'>Send due now</button></form>" if is_draft else ''}<form method='post' action='/office/invoices/{esc(invoice_id)}/void'><button class='danger'>Void invoice</button></form>{f"<form method='post' action='/office/invoices/{esc(invoice_id)}/delete'><button class='danger'>Delete draft</button></form>" if is_draft else ''}</div></div>"""
    return _page("Manage Invoice", edit_form + actions, "invoices")


@app.post("/office/invoices/{invoice_id}/edit")
def update_invoice_local(invoice_id: str, invoice_number: str = Form(...), title: str = Form(...), estimate_payload: str = Form(...), terms: str = Form(default="")) -> RedirectResponse:
    actor = _require("invoices.manage")
    item = _local_record_or_404("invoices", invoice_id)
    if str(item.get("status") or "DRAFT").upper() != "DRAFT":
        store.set_notice("Only draft invoices can be edited.")
        return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)
    try:
        sections, lines, total_cents = normalize_document_payload(estimate_payload, title=title)
        lines = _save_custom_catalog_lines(lines, str(actor.get("id")))
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/invoices/{invoice_id}/edit", status_code=303)
    balance = max(0, total_cents - int(item.get("paid_cents") or 0))
    store.update_record("invoices", invoice_id, {"invoice_number": invoice_number.strip(), "title": title.strip(), "sections": sections, "line_items": lines, "total_cents": total_cents, "balance_cents": balance, "terms": terms.strip()}, actor_id=str(actor.get("id")))
    store.set_notice("Invoice headers and line items updated.")
    return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)


@app.post("/office/square/reconcile")
async def reconcile_square_now(next_path: str = Form(default="/office/invoices")) -> RedirectResponse:
    _require("payments.manage")
    try:
        changed = await _reconcile_square_invoices_once()
        store.set_notice(f"Payment status refresh completed. {changed} invoice(s) updated.")
    except Exception as exc:
        store.set_notice(f"Payment status refresh failed: {exc}")
    target = next_path if str(next_path).startswith("/office/") else "/office/invoices"
    return RedirectResponse(target, status_code=303)


@app.post("/office/invoices/{invoice_id}/send")
async def send_invoice_due_now(invoice_id: str) -> RedirectResponse:
    actor = _require("invoices.manage")
    invoice = _local_record_or_404("invoices", invoice_id)
    try:
        updated, recipient = await _send_customer_document("invoice", invoice, actor_id=str(actor.get("id")))
        store.set_notice(f"Floodman invoice sent to {recipient}. It is due immediately and includes the secure online payment page.")
    except Exception as exc:
        store.set_notice(f"Invoice was not sent: {exc}")
    return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)


@app.post("/office/invoices/{invoice_id}/void")
def void_invoice(invoice_id: str) -> RedirectResponse:
    actor = _require("invoices.manage")
    _local_record_or_404("invoices", invoice_id)
    store.update_record("invoices", invoice_id, {"status": "VOID", "voided_at": datetime.now(UTC).isoformat()}, actor_id=str(actor.get("id")))
    store.set_notice("Invoice voided. Existing payment records were preserved.")
    return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)


@app.post("/office/invoices/{invoice_id}/delete")
def delete_invoice(invoice_id: str) -> RedirectResponse:
    _require("invoices.manage")
    item = _local_record_or_404("invoices", invoice_id)
    if str(item.get("status") or "DRAFT").upper() != "DRAFT" or int(item.get("paid_cents") or 0) > 0:
        store.set_notice("Only unpaid draft invoices can be deleted.")
        return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)
    store.delete_record("invoices", invoice_id)
    store.set_notice("Invoice draft deleted.")
    return RedirectResponse("/office/invoices", status_code=303)


@app.post("/office/documents/{document_id}/delete")
def delete_document(document_id: str) -> RedirectResponse:
    _require("documents.manage")
    item = _local_record_or_404("documents", document_id)
    if str(item.get("status") or "").upper() in {"SIGNED", "COMPLETED"}:
        store.set_notice("Completed signed documents are retained and cannot be deleted from the office interface.")
    else:
        store.delete_record("documents", document_id)
        store.set_notice("Draft document removed.")
    return RedirectResponse("/office/documents", status_code=303)


@app.post("/office/notes/{note_id}/delete")
def delete_note(note_id: str) -> RedirectResponse:
    _require("notes.manage")
    _local_record_or_404("notes", note_id)
    store.delete_record("notes", note_id)
    store.set_notice("Note deleted.")
    return RedirectResponse("/office/notes", status_code=303)


@app.post("/office/time/manual")
def manual_time_entry(user_id: str = Form(...), job_reference: str = Form(...), clock_in_at: str = Form(...), clock_out_at: str = Form(...), note: str = Form(default="")) -> RedirectResponse:
    actor = _require("time.manage")
    try:
        start = datetime.fromisoformat(clock_in_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(clock_out_at.replace("Z", "+00:00"))
        if end <= start:
            raise ValueError("Clock-out time must be after clock-in time.")
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/time", status_code=303)
    store.create_record("time_entries", {"user_id": user_id, "job_reference": job_reference.strip(), "note": note.strip(), "clock_in": start.isoformat(), "clock_out": end.isoformat(), "duration_seconds": int((end-start).total_seconds()), "status": "COMPLETED", "approval_status": "APPROVED"}, actor_id=str(actor.get("id")))
    store.set_notice("Manual time entry added.")
    return RedirectResponse("/office/time", status_code=303)


@app.post("/office/time/{entry_id}/approve")
def approve_time_entry(entry_id: str) -> RedirectResponse:
    actor = _require("time.manage")
    _local_record_or_404("time_entries", entry_id)
    store.update_record("time_entries", entry_id, {"approval_status": "APPROVED", "approved_at": datetime.now(UTC).isoformat(), "approved_by": actor.get("id")}, actor_id=str(actor.get("id")))
    store.set_notice("Time entry approved.")
    return RedirectResponse("/office/time", status_code=303)


@app.get("/office/gauzy", include_in_schema=False)
def legacy_platform_page() -> RedirectResponse:
    return RedirectResponse("/office/platform", status_code=307)


@app.post("/office/gauzy/sync", include_in_schema=False)
async def legacy_platform_sync() -> Response:
    return await sync_full_gauzy()
