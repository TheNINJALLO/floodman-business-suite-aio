from __future__ import annotations

import html
import json
import mimetypes
import uuid
from collections import defaultdict
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from .auth import ROLE_PERMISSIONS, has_permission
from .config import Settings
from .importer import (
    ImportValidationError,
    bundle_files,
    create_zip,
    sample_files,
    template_files,
    validate,
)
from .providers import ProviderClient
from .store import OfficeStore
from .ui import badge, esc, json_pre, layout, money_cents, money_units, progress, simple_page, table


settings = Settings.from_env()
store = OfficeStore(settings.data_dir)
providers = ProviderClient(settings)
app = FastAPI(title="Floodman Office", version="3.0.0", docs_url=None, redoc_url=None)
_current_user: ContextVar[dict[str, Any] | None] = ContextVar("office_current_user", default=None)

PUBLIC_PATHS = {"/health/live", "/health/ready", "/login", "/login/gauzy", "/logout", "/setup/owner"}
PUBLIC_PREFIXES = ("/invite/",)


@app.middleware("http")
async def office_auth(request: Request, call_next):
    path = request.url.path
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
    return {"status": "ok", "service": "floodman-office-console", "version": "3.0.0"}


@app.get("/health/ready")
async def ready() -> dict[str, Any]:
    try:
        state = _merge_archive_state(await providers.lab_state())
        return {"status": "ready", "local_lab": True, "test_job_id": state.get("test_job_id") or state.get("demo_job_id")}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/login")
def login_page(next: str = "/office") -> HTMLResponse:
    if not store.has_users():
        return RedirectResponse("/setup", status_code=303)
    body = f"""<h1>Sign in</h1>
    <div class='card'><h2>Use your Gauzy account</h2><p class='muted'>Employees and administrators created in Gauzy can use the same credentials for Floodman modules. The password is verified by Gauzy and is never stored here.</p>
    <form method='post' action='/login/gauzy'><input type='hidden' name='next' value='{esc(next)}'>
    <div class='field'><label>Gauzy email</label><input type='email' name='email' required autofocus></div>
    <div class='field' style='margin-top:12px'><label>Gauzy password</label><input type='password' name='password' required></div>
    <button class='good' style='margin-top:16px;width:100%'>Continue with Gauzy</button></form></div>
    <div class='card'><h2>Floodman-only account</h2><p class='muted'>Use this for a local owner or a member invited only to Floodman modules.</p>
    <form method='post' action='/login'><input type='hidden' name='next' value='{esc(next)}'>
    <div class='field'><label>Email</label><input type='email' name='email' required></div>
    <div class='field' style='margin-top:12px'><label>Password</label><input type='password' name='password' required></div>
    <button style='margin-top:16px;width:100%'>Sign in locally</button></form></div>"""
    return HTMLResponse(simple_page("Sign in", body))


@app.post("/login")
def login(email: str = Form(...), password: str = Form(...), next: str = Form(default="/office")) -> Response:
    user = store.authenticate(email, password)
    if not user:
        body = "<h1>Sign in</h1><div class='callout danger'>The email or password was not accepted.</div><a class='button' href='/login'>Try again</a>"
        return HTMLResponse(simple_page("Sign in", body), status_code=401)
    target = next if next.startswith("/") and not next.startswith("//") else "/office"
    response = RedirectResponse(target, status_code=303)
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


@app.post("/login/gauzy")
async def login_with_gauzy(
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/office"),
) -> Response:
    try:
        identity = await providers.authenticate_gauzy_member(email, password)
        user = store.upsert_gauzy_user(identity)
    except (RuntimeError, ValueError) as exc:
        body = f"<h1>Gauzy sign in</h1><div class='callout danger'>{esc(exc)}</div><a class='button' href='/login'>Try again</a>"
        if not store.has_users():
            body += " <a class='button secondary' href='/setup'>Return to owner setup</a>"
        return HTMLResponse(simple_page("Gauzy sign in", body), status_code=401)
    target = next if next.startswith("/") and not next.startswith("//") else "/office"
    response = RedirectResponse(target, status_code=303)
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
    target = "/office" if store.checklist().get("setup_complete") else "/setup"
    return RedirectResponse(target, status_code=302)


def _page(title: str, body: str, active: str) -> HTMLResponse:
    snapshot = store.snapshot()
    return HTMLResponse(
        layout(
            title,
            body,
            active=active,
            notice=snapshot.get("last_notice", ""),
            setup_complete=bool(snapshot["checklist"].get("setup_complete")),
            release=settings.release,
            user=_user(),
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

@app.get("/setup")
async def setup_page() -> HTMLResponse:
    if not store.has_users():
        body = """<h1>Create the primary owner</h1><p class='muted'>Gauzy is the main identity and ERP hub. The Floodman owner created during business initialization can become the first Floodman module owner, or you can create a separate local recovery owner.</p>
        <div class='card'><h2>Recommended: use the Floodman Gauzy owner</h2><form method='post' action='/login/gauzy'><input type='hidden' name='next' value='/setup'>
        <div class='field'><label>Gauzy owner email</label><input type='email' name='email' value='' placeholder='owner@your-domain.com' required autofocus></div>
        <div class='field' style='margin-top:12px'><label>Gauzy password</label><input type='password' name='password' required></div>
        <button class='good' style='margin-top:16px;width:100%'>Use Floodman Gauzy owner</button></form></div>
        <div class='card'><h2>Local recovery owner</h2><p class='muted'>This account controls Floodman-specific modules even if Gauzy is temporarily unavailable.</p>
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
<div class='card'><h2>Setup progress</h2><div class='progress'><span style='width:{percentage}%'></span></div>
<div class='steps'>{step_html}</div><p class='muted'>{done} of {total} setup areas reviewed. This setup record is stored in a dedicated Docker volume.</p></div>
<div class='card'><h2>1. Company profile</h2>
<form method='post' action='/setup/profile'><div class='form-grid'>
<div class='field'><label>Display name</label><input name='company_name' value='{esc(profile.get('company_name'))}' required></div>
<div class='field'><label>Legal company name</label><input name='legal_name' value='{esc(profile.get('legal_name'))}'></div>
<div class='field'><label>Office email</label><input type='email' name='office_email' value='{esc(profile.get('office_email'))}' placeholder='office@floodman.com'></div>
<div class='field'><label>Billing email</label><input type='email' name='billing_email' value='{esc(profile.get('billing_email'))}' placeholder='billing@floodman.com'></div>
<div class='field'><label>Office phone</label><input name='office_phone' value='{esc(profile.get('office_phone'))}' placeholder='+1 313 555 0100'></div>
<div class='field'><label>Timezone</label><input name='timezone' value='{esc(profile.get('timezone'))}'></div>
<div class='field full'><label>Street</label><input name='street' value='{esc(profile.get('street'))}'></div>
<div class='field'><label>City</label><input name='city' value='{esc(profile.get('city'))}'></div>
<div class='field'><label>State</label><input name='state' value='{esc(profile.get('state'))}'></div>
<div class='field'><label>Postal code</label><input name='postal_code' value='{esc(profile.get('postal_code'))}'></div>
</div><div class='actions' style='margin-top:14px'><button>Save company profile</button></div></form></div>
<div class='card'><h2>2. Linked services</h2><p>The full local system includes local provider sandboxes plus the genuine clean Gauzy ERP, Documenso signing application, Mailpit inbox, AI messaging, and competitor intelligence. Test every connection here before moving to external sandbox accounts.</p>
<div class='grid'>{connection_cards}</div><div class='actions'><form method='post' action='/setup/test-connections'><button>Test all connections</button></form><a class='button secondary' href='/office/linking'>Open connection guide</a></div></div>
<div class='card'><h2>3. Migration and imports</h2><p>Upload normalized contacts, properties, estimates, estimate lines, invoices, payments, documents, notes, and referenced files. Validation runs before any record is written.</p>
<div class='actions'><a class='button' href='/office/imports'>Open Import Center</a><a class='button secondary' href='/office/imports/sample.zip'>Download sample import</a><a class='button secondary' href='/office/imports/templates.zip'>Download blank templates</a></div></div>
<div class='card'><h2>4. Documents and messaging review</h2><form method='post' action='/setup/checklist' class='checks'>
<label><input type='checkbox' name='legal_reviewed' value='true' {'checked' if checklist.get('legal_reviewed') else ''}> I reviewed the Work Authorization, Change Order, and Completion of Service test workflow. Local templates are not approved production contracts.</label>
<label><input type='checkbox' name='messaging_reviewed' value='true' {'checked' if checklist.get('messaging_reviewed') else ''}> I reviewed SMS consent, STOP/START, AI escalation, immediate-due invoicing, and past-due reminders.</label>
<label><input type='checkbox' name='import_reviewed' value='true' {'checked' if checklist.get('import_reviewed') else ''}> I reviewed the migration format, even if I am not importing records yet.</label>
<button>Save review checklist</button></form></div>
<div class='card'><h2>5. Finish local setup</h2><p>Finishing only changes the console landing page. It does not activate production payments, texts, or contracts.</p>
<form method='post' action='/setup/finish'><button class='good'>Finish local setup</button></form></div>
"""
    return _page("Guided Setup", body, "setup")


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
    store.update_profile(
        {
            "company_name": company_name.strip(),
            "legal_name": legal_name.strip(),
            "office_email": office_email.strip(),
            "billing_email": billing_email.strip(),
            "office_phone": office_phone.strip(),
            "timezone": timezone.strip() or "America/Detroit",
            "street": street.strip(),
            "city": city.strip(),
            "state": state.strip(),
            "postal_code": postal_code.strip(),
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
    return RedirectResponse("/office", status_code=303)


@app.get("/office")
async def office_dashboard() -> HTMLResponse:
    try:
        state = _merge_archive_state(await providers.lab_state())
    except Exception as exc:
        state = _merge_archive_state({"error": str(exc)})
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
    alerts = _rows(state.get("staff_alerts"))
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
    job_card = json_pre(job) if job else "<p class='muted'>No active staging job. Use the Engineering Sandbox to create one.</p>"
    body = f"""
<div class='grid'>
<div class='card metric'><small>Contacts</small><strong>{len(contacts)}</strong></div>
<div class='card metric'><small>Properties</small><strong>{len(properties)}</strong></div>
<div class='card metric'><small>Estimates</small><strong>{len(estimates)}</strong></div>
<div class='card metric'><small>Invoices</small><strong>{len(invoices) + len(square)}</strong></div>
<div class='card metric'><small>Verified live balance</small><strong>{money_cents(outstanding)}</strong></div>
<div class='card metric'><small>Imported archive balance</small><strong>{money_cents(imported_due)}</strong><small>Not enrolled in reminders</small></div>
<div class='card metric'><small>Payments recorded</small><strong>{money_cents(paid_cents)}</strong></div>
<div class='card metric'><small>Documents</small><strong>{len(documents)}</strong></div>
<div class='card metric'><small>Notes</small><strong>{len(notes)}</strong></div>
<div class='card metric'><small>Open A/R cases</small><strong>{len(ar_cases)}</strong></div>
<div class='card metric'><small>Open alerts</small><strong>{len(alerts)}</strong></div>
</div>
<div class='card'><h2>Quick start</h2><div class='actions'><a class='button' href='/office/apps'>All applications</a><a class='button' href='/office/contacts'>Add contact</a><a class='button' href='/office/estimates'>Create estimate</a><a class='button' href='/office/documents'>Send document</a><a class='button' href='/office/members'>Add members</a><a class='button secondary' href='/office/time'>Time clock</a><a class='button secondary' href='/office/intelligence'>AI competition</a></div></div>
<div class='card'><h2>Current workflow job</h2>{job_card}</div>
<div class='card'><h2>How the front ends fit together</h2><div class='grid'>
<div><h3>Floodman Office</h3><p class='muted'>This is the owner command center for Floodman-specific customer, property, billing, signing, A/R, messaging, member, import, and intelligence workflows.</p></div>
<div><h3>RoomFlow</h3><p class='muted'>Build the property scope and estimate, then send it to the orchestrator.</p></div>
<div><h3>Gauzy</h3><p class='muted'>The genuine full ERP is included in the full launch profile for CRM, staff, time, projects, tasks, estimates, invoices, accounting, HR, inventory, reports, roles, and integrations.</p></div>
<div><h3>Documenso</h3><p class='muted'>The genuine signing front end is included for templates, PDF field placement, recipients, signatures, audit records, and document management.</p></div>
<div><h3>Square</h3><p class='muted'>Payment pages and transaction truth. The Windows lab uses local payment pages and signed mock webhooks.</p></div>
</div></div>
"""
    return _page("Operations Dashboard", body, "dashboard")


@app.get("/office/linking")
async def linking_page() -> HTMLResponse:
    _require("connections.manage")
    snapshot = store.snapshot()
    connections = snapshot.get("connections") or {}
    config = snapshot.get("link_config") or {}
    rows = []
    definitions = [
        ("RoomFlow", "roomflow", settings.roomflow_sync_endpoint, "Server-side HMAC integration"),
        ("Gauzy workflow bridge", "gauzy_workflow_bridge", settings.gauzy_base_url, "Safe local workflow adapter"),
        ("Full Gauzy ERP", "gauzy_full_ui", settings.gauzy_web_url, "All upstream Gauzy modules"),
        ("Square", "square", settings.square_base_url, "Orders, invoices, payments and webhooks"),
        ("Signing workflow bridge", "documenso_workflow_bridge", settings.documenso_base_url, "Floodman document workflow adapter"),
        ("Full Documenso", "documenso_full_ui", settings.documenso_web_url, "Templates, signing fields and audit UI"),
        ("Twilio", "twilio", settings.twilio_base_url, "Two-way SMS and delivery callbacks"),
        ("SMTP capture", "smtp", f"{settings.smtp_host}:{settings.smtp_port}", "Workflow email transport"),
        ("Local email inbox", "mailpit", settings.mailpit_url, "View captured local email"),
        ("Messaging AI", "messaging_ai", settings.messaging_ai_url, f"Provider: {settings.messaging_ai_provider}"),
        ("Competitor Intelligence", "competitor_intelligence", settings.competitor_url, "Scheduled public-site monitoring"),
    ]
    for label, key, endpoint, purpose in definitions:
        result = connections.get(key) or {"status": "NOT TESTED", "detail": "Run connection test"}
        rows.append([esc(label), badge(result.get("status")), f"<span class='mono'>{esc(endpoint)}</span>", esc(purpose)])
    connection_table = table(("Service", "Status", "Endpoint", "Responsibility"), rows)
    mode_options = lambda current: "".join(
        f"<option value='{value}' {'selected' if current == value else ''}>{label}</option>"
        for value, label in (("FULL_LOCAL", "Full local application"), ("LOCAL_MOCK", "Local simulator"), ("SANDBOX", "Provider sandbox"), ("PRODUCTION", "Production later"))
    )
    body = f"""
<div class='callout'><b>Full local operations mode:</b> the genuine Gauzy and Documenso applications run beside the Floodman-safe payment, messaging, signing-workflow and webhook simulators. Secrets stay in <code>.env.windows</code>, never in this browser form.</div>
<div class='card'><h2>Running services</h2>{connection_table}<div class='actions' style='margin-top:14px'><form method='post' action='/setup/test-connections'><button>Test all connections</button></form><a class='button' href='/office/apps'>Open all applications</a><a class='button secondary' href='/office/linking/checklist.txt'>Download checklist</a></div></div>
<div class='card'><h2>Connection plan</h2><form method='post' action='/office/linking/plan'><div class='form-grid'>
<div class='field full'><label>RoomFlow web address</label><input type='url' name='roomflow_url' value='{esc(config.get('roomflow_url'))}'></div>
<div class='field'><label>Gauzy mode</label><select name='gauzy_mode'>{mode_options(config.get('gauzy_mode'))}</select></div><div class='field'><label>Gauzy API base URL</label><input name='gauzy_base_url' value='{esc(config.get('gauzy_base_url'))}'></div>
<div class='field'><label>Square mode</label><select name='square_mode'>{mode_options(config.get('square_mode'))}</select></div><div class='field'><label>Square API base URL</label><input name='square_base_url' value='{esc(config.get('square_base_url'))}'></div>
<div class='field'><label>Square location ID</label><input name='square_location_id' value='{esc(config.get('square_location_id'))}'></div><div class='field'><label>Documenso mode</label><select name='documenso_mode'>{mode_options(config.get('documenso_mode'))}</select></div>
<div class='field'><label>Documenso API base URL</label><input name='documenso_base_url' value='{esc(config.get('documenso_base_url'))}'></div><div class='field'><label>Twilio mode</label><select name='twilio_mode'>{mode_options(config.get('twilio_mode'))}</select></div>
<div class='field'><label>Twilio API base URL</label><input name='twilio_base_url' value='{esc(config.get('twilio_base_url'))}'></div><div class='field'><label>Twilio Account SID</label><input name='twilio_account_sid' value='{esc(config.get('twilio_account_sid'))}'></div>
<div class='field'><label>Twilio Messaging Service SID</label><input name='twilio_messaging_service_sid' value='{esc(config.get('twilio_messaging_service_sid'))}'></div><div class='field'><label>SMTP mode</label><select name='smtp_mode'><option value='LOCAL_CAPTURE' {'selected' if config.get('smtp_mode') == 'LOCAL_CAPTURE' else ''}>Local capture</option><option value='SANDBOX' {'selected' if config.get('smtp_mode') == 'SANDBOX' else ''}>Test mailbox</option><option value='PRODUCTION' {'selected' if config.get('smtp_mode') == 'PRODUCTION' else ''}>Production later</option></select></div>
<div class='field'><label>SMTP host</label><input name='smtp_host' value='{esc(config.get('smtp_host'))}'></div><div class='field'><label>SMTP port</label><input type='number' name='smtp_port' value='{esc(config.get('smtp_port'))}'></div>
<div class='field'><label>Messaging AI provider</label><select name='messaging_ai_provider'><option value='deterministic' {'selected' if config.get('messaging_ai_provider') == 'deterministic' else ''}>Deterministic local policy</option><option value='openai' {'selected' if config.get('messaging_ai_provider') == 'openai' else ''}>OpenAI after approval</option></select></div>
</div><div class='actions' style='margin-top:14px'><button>Save plan</button><a class='button secondary' href='/office/linking/env-snippet.txt'>Download .env snippet</a></div></form></div>
<div class='card'><h2>Application launch</h2><div class='actions'><a class='button' href='{esc(settings.gauzy_web_url)}' target='_blank'>Full Gauzy ERP</a><a class='button' href='{esc(settings.documenso_web_url)}' target='_blank'>Documenso</a><a class='button' href='{esc(settings.roomflow_url)}' target='_blank'>RoomFlow</a><a class='button secondary' href='{esc(settings.mailpit_url)}' target='_blank'>Mailpit</a><a class='button secondary' href='{esc(settings.engineering_public_url)}/lab' target='_blank'>Engineering Sandbox</a></div><p class='muted'>Start everything with <code>Start-Floodman-Full-System.cmd</code>.</p></div>
<div class='card'><h2>RoomFlow server bridge</h2><p>The HMAC secret belongs in the authenticated Supabase Edge Function or another server-side worker, never browser JavaScript.</p><pre>FLOODMAN_ORCHESTRATOR_URL={settings.api_public_url}
FLOODMAN_ORCHESTRATOR_KEY_ID=v1
FLOODMAN_ORCHESTRATOR_HMAC_SECRET=&lt;base64 secret from .env.windows&gt;</pre></div>
"""
    return _page("Connections", body, "linking")


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

# Gauzy ({config.get('gauzy_mode')})
GAUZY_BASE_URL={config.get('gauzy_base_url', '')}
GAUZY_EMAIL=CHANGE_ME
GAUZY_PASSWORD=CHANGE_ME
GAUZY_TENANT_ID=CHANGE_ME
GAUZY_ORGANIZATION_ID=CHANGE_ME
GAUZY_FROM_ORGANIZATION_ID=CHANGE_ME

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
Gauzy Operations Hub: {settings.gauzy_hub_url}
Floodman modules: {settings.public_url}/office
Direct Office diagnostic: internal port 8700 (not a public Pterodactyl allocation)
Engineering lab: {esc(settings.engineering_public_url)}
Orchestrator: {esc(settings.api_public_url)}

1. Save a non-secret connection plan in Floodman Office.
2. Download /office/linking/env-snippet.txt.
3. Put credentials only in C:\\FloodmanLab\\.env.windows.
4. Restart the affected containers.
5. Run Test all running connections.
6. Complete sandbox acceptance before any production credentials are used.

Never paste provider tokens into RoomFlow browser JavaScript, Android assets, GitHub, screenshots, or customer-facing pages.
"""


@app.get("/office/imports")
def imports_page() -> HTMLResponse:
    imports = store.list_imports()
    history_rows = []
    for run in imports:
        counts = run.get("counts") or {}
        total_records = sum(int(counts.get(key) or 0) for key in (
            "contacts", "properties", "estimates", "estimate_lines", "invoices", "payments", "documents", "notes"
        ))
        history_rows.append([
            esc(run.get("created_at", "")[:19].replace("T", " ")),
            badge(run.get("status")),
            esc(total_records),
            esc(counts.get("attachments", counts.get("pdfs", 0))),
            money_cents((run.get("totals") or {}).get("outstanding_cents", 0)),
            f"<a href='/office/imports/{esc(run.get('id'))}'>Review</a>",
        ])
    history = table(
        ("Created", "Status", "Records", "Attachments", "Outstanding", "Open"),
        history_rows,
        "No import bundles have been uploaded.",
    )
    body = f"""
<div class='callout'><b>Safe default:</b> imported invoices are historical archive records. They do not create Square payment links, email customers, or start automatic reminders.</div>
<div class='grid'><div class='card'><h2>Upload one complete ZIP</h2><form method='post' action='/office/imports/upload' enctype='multipart/form-data'><label>Migration bundle</label><input type='file' name='bundle' accept='.zip' required><p class='muted'>Include contacts, properties, estimates, estimate lines, invoices, payments, plus documents, notes, and matching files when available.</p><button>Validate bundle</button></form></div>
<div class='card'><h2>Resources</h2><div class='actions'><a class='button' href='/office/imports/sample.zip'>Sample import ZIP</a><a class='button secondary' href='/office/imports/templates.zip'>Blank templates</a></div><p class='muted'>The sample is a complete valid bundle that exercises every import category.</p></div></div>
<div class='card'><h2>Import history</h2>{history}</div>
<div class='card'><h2>What is preserved</h2><p>Legacy IDs, customer details, properties, estimate revisions and line items, invoices, payments, PDFs and other attachments, signed-document references, notes, statuses, timestamps, and provider references are preserved. Original exports remain untouched and separately backed up.</p></div>
"""
    return _page("Import Center", body, "imports")


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


@app.get("/office/imports/{run_id}")
def import_detail(run_id: str) -> HTMLResponse:
    run = store.get_import(run_id)
    if not run:
        raise HTTPException(404, "Import run not found")
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
    if run.get("errors"):
        store.set_notice("This import cannot be committed until its validation errors are fixed.")
        return RedirectResponse(f"/office/imports/{run_id}", status_code=303)
    if run.get("status") == "COMMITTED":
        store.set_notice("That import was already committed; no duplicates were created.")
        return RedirectResponse(f"/office/imports/{run_id}", status_code=303)
    store.update_import(run_id, status="IMPORTING")
    try:
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


@app.get("/office/imports/{run_id}/files/{filename:path}")
def import_file(run_id: str, filename: str) -> Response:
    if not store.get_import(run_id):
        raise HTTPException(404, "Import run not found")
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
    values = _rows(state.get("gauzy_contacts"))
    seen = {str(item.get("id")) for item in values if item.get("id")}
    for item in _operation_contacts():
        if str(item.get("id")) not in seen:
            values.append({
                **item,
                "name": item.get("name") or " ".join(filter(None, [item.get("first_name"), item.get("last_name")])),
                "primaryEmail": item.get("email"),
                "primaryPhone": item.get("phone"),
            })
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


def _parse_money(value: str) -> int:
    raw = (value or "0").replace("$", "").replace(",", "").strip()
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid money value: {value}") from exc
    return int((amount * 100).quantize(Decimal("1")))


def _parse_line_items(value: str) -> tuple[list[dict[str, Any]], int]:
    items: list[dict[str, Any]] = []
    total = 0
    for number, raw in enumerate((value or "").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 3:
            raise ValueError(f"Line {number} must use Description | Quantity | Unit price")
        description = parts[0]
        try:
            quantity = Decimal(parts[1])
        except InvalidOperation as exc:
            raise ValueError(f"Line {number} has an invalid quantity") from exc
        unit_cents = _parse_money(parts[2])
        line_cents = int((quantity * unit_cents).quantize(Decimal("1")))
        total += line_cents
        items.append({
            "id": str(uuid.uuid4()),
            "description": description,
            "name": description,
            "quantity": float(quantity),
            "unit_price_cents": unit_cents,
            "line_total_cents": line_cents,
            "price": unit_cents / 100,
            "totalValue": line_cents / 100,
        })
    if not items:
        raise ValueError("Add at least one line item.")
    return items, total


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
    """Create one native Gauzy contact and persist the stable mapping."""
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
        raise RuntimeError("Gauzy did not return a contact ID")
    store.set_external_mapping("gauzy", key, external)
    if store.record("contacts", record_id):
        store.update_record("contacts", record_id, {"full_gauzy_id": external}, actor_id=actor_id)
    return external


async def _sync_property_to_real_gauzy(record: dict[str, Any], actor_id: str) -> str | None:
    """Represent a Floodman service property/job as a native Gauzy project."""
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
        raise RuntimeError("Gauzy contact mapping is missing")
    context = await providers.gauzy_context()
    created = await providers.full_gauzy_create_project(record, context, contact_id=external_contact)
    external = str(created.get("id") or "")
    if not external:
        raise RuntimeError("Gauzy did not return a project ID")
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
        raise RuntimeError("Gauzy did not return a financial record ID")
    store.set_external_mapping("gauzy", key, external)
    if store.record(kind + "s", record_id):
        store.update_record(
            kind + "s",
            record_id,
            {"full_gauzy_id": external, "full_gauzy_project_id": project_id},
            actor_id=actor_id,
        )
    return external


@app.get("/office/contacts")
async def contacts_page() -> HTMLResponse:
    _require("contacts.view")
    state = await _state_page_data()
    contacts = _all_contact_rows(state)
    rows = [
        [
            f"<a href='/office/contacts/{esc(item.get('id'))}'>{esc(item.get('name') or '')}</a>",
            esc(item.get("primaryEmail") or item.get("email") or ""),
            esc(item.get("primaryPhone") or item.get("phone") or ""),
            badge("Imported" if item.get("legacySource") or item.get("legacy_source") else item.get("source") or "Current"),
            esc(item.get("notes") or ""),
        ]
        for item in contacts
    ]
    create = ""
    if has_permission(_user(), "contacts.manage"):
        create = """<div class='card'><h2>Add customer contact</h2><form method='post' action='/office/contacts/add'><div class='form-grid three'>
        <div class='field'><label>First name</label><input name='first_name' required></div><div class='field'><label>Last name</label><input name='last_name' required></div>
        <div class='field'><label>Company</label><input name='company'></div><div class='field'><label>Email</label><input type='email' name='email'></div>
        <div class='field'><label>Phone</label><input name='phone'></div><div class='field'><label>Lead source</label><input name='lead_source' placeholder='Website, referral, repeat customer'></div>
        <div class='field full'><label>Notes</label><textarea name='notes'></textarea></div></div><button style='margin-top:12px'>Create contact</button></form></div>"""
    body = f"{create}<div class='card'><h2>Customer contacts</h2>{table(('Name','Email','Phone','Source','Notes'), rows)}</div>"
    return _page("Contacts", body, "contacts")


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
        store.set_notice(f"Contact saved locally; Gauzy bridge warning: {exc}")
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
            notice += " Synced to genuine Gauzy."
    except Exception as exc:
        notice += f" Genuine Gauzy sync needs review: {exc}"
    store.set_notice(notice)
    return RedirectResponse(f"/office/contacts/{record['id']}", status_code=303)


@app.get("/office/contacts/{contact_id}")
async def contact_detail(contact_id: str) -> HTMLResponse:
    _require("contacts.view")
    state = await _state_page_data()
    contact = next((item for item in _all_contact_rows(state) if str(item.get("id")) == contact_id), None)
    if not contact:
        raise HTTPException(404, "Contact not found")
    properties = [item for item in store.records("properties") + _rows(state.get("properties")) if str(item.get("contact_id") or "") == contact_id]
    provider_financials = _rows(state.get("gauzy_invoices"))
    estimates = [item for item in store.records("estimates") + provider_financials if item.get("isEstimate") is True or (item.get("estimate_number") and str(item.get("contact_id") or "") == contact_id)]
    estimates = [item for item in estimates if str(item.get("contact_id") or item.get("organizationContactId") or "") == contact_id]
    invoices = [item for item in store.records("invoices") + provider_financials if item.get("isEstimate") is not True and str(item.get("contact_id") or item.get("organizationContactId") or "") == contact_id]
    def unique(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set(); result: list[dict[str, Any]] = []
        for item in rows:
            identity = str(item.get("id") or "")
            if identity and identity in seen: continue
            if identity: seen.add(identity)
            result.append(item)
        return result
    properties, estimates, invoices = unique(properties), unique(estimates), unique(invoices)
    manage = f"<a class='button secondary' href='/office/contacts/{esc(contact_id)}/edit'>Edit contact</a>" if store.record("contacts", contact_id) and has_permission(_user(), "contacts.manage") else ""
    body = f"""<div class='actions'><a class='button secondary' href='/office/contacts'>Back to contacts</a><a class='button' href='/office/properties?contact_id={quote(contact_id)}'>Add property</a><a class='button' href='/office/estimates?contact_id={quote(contact_id)}'>Create estimate</a>{manage}</div>
    <div class='grid two' style='margin-top:15px'><div class='card'><h2>{esc(contact.get('name'))}</h2><p><b>Email:</b> {esc(contact.get('primaryEmail') or contact.get('email') or '')}</p><p><b>Phone:</b> {esc(contact.get('primaryPhone') or contact.get('phone') or '')}</p><p><b>Company:</b> {esc(contact.get('company') or '')}</p><p><b>Notes:</b> {esc(contact.get('notes') or '')}</p></div>
    <div class='card'><h2>Customer summary</h2><div class='grid'><div class='metric'><small>Properties</small><strong>{len(properties)}</strong></div><div class='metric'><small>Estimates</small><strong>{len(estimates)}</strong></div><div class='metric'><small>Invoices</small><strong>{len(invoices)}</strong></div></div></div></div>
    <div class='card'><h2>Properties</h2>{table(('Property','Address','Type'), [[f"<a href='/office/properties/{esc(i.get('id'))}'>{esc(i.get('name') or i.get('property_name'))}</a>", esc(i.get('service_street')), esc(i.get('property_type'))] for i in properties])}</div>
    <div class='card'><h2>Estimates</h2>{table(('Estimate','Status','Total'), [[f"<a href='/office/estimates/{esc(i.get('id'))}'>{esc(i.get('estimate_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('total_cents') if i.get('total_cents') is not None else int(round(float(i.get('totalValue') or 0)*100)))] for i in estimates])}</div>
    <div class='card'><h2>Invoices</h2>{table(('Invoice','Status','Balance'), [[f"<a href='/office/invoices/{esc(i.get('id'))}'>{esc(i.get('invoice_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('balance_cents') if i.get('balance_cents') is not None else int(round(float(i.get('amountDue') or 0)*100)))] for i in invoices])}</div>"""
    return _page(str(contact.get("name") or "Contact"), body, "contacts")


@app.get("/office/properties")
async def properties_page(contact_id: str = "") -> HTMLResponse:
    _require("properties.view")
    state = await _state_page_data()
    properties: list[dict[str, Any]] = []
    seen_properties: set[str] = set()
    for item in store.records("properties") + _rows(state.get("properties")):
        identity = str(item.get("id") or item.get("legacyPropertyId") or item.get("legacy_property_id") or "")
        if identity and identity in seen_properties:
            continue
        if identity:
            seen_properties.add(identity)
        properties.append(item)
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
            esc(_contact_name(str(item.get("contact_id") or ""), state)),
            esc(formatted),
            esc(item.get("property_type") or ""),
            esc(item.get("claim_number") or ""),
        ])
    create = ""
    if has_permission(_user(), "properties.manage"):
        create = f"""<div class='card'><h2>Add service property</h2><form method='post' action='/office/properties/add'><div class='form-grid three'>
        <div class='field'><label>Customer</label><select name='contact_id' required>{_contact_options(state, contact_id)}</select></div>
        <div class='field'><label>Property name</label><input name='name' placeholder='Home, rental, business' required></div><div class='field'><label>Property type</label><select name='property_type'><option>Residential</option><option>Commercial</option><option>Rental</option><option>Other</option></select></div>
        <div class='field full'><label>Service street</label><input name='service_street' required></div><div class='field'><label>City</label><input name='service_city' required></div>
        <div class='field'><label>State</label><input name='service_state' value='MI' required></div><div class='field'><label>Postal code</label><input name='service_postal_code' required></div>
        <div class='field'><label>Insurance company</label><input name='insurance_company'></div><div class='field'><label>Claim number</label><input name='claim_number'></div>
        <div class='field full'><label>Property notes</label><textarea name='notes'></textarea></div></div><button style='margin-top:12px'>Create property</button></form></div>"""
    body = f"{create}<div class='card'><h2>Service properties</h2>{table(('Property','Customer','Service address','Type','Claim'), rows)}</div>"
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
            notice += " Created as a genuine Gauzy project."
    except Exception as exc:
        notice += f" Genuine Gauzy project sync needs review: {exc}"
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
    body = f"""<div class='actions'><a class='button secondary' href='/office/properties'>Back</a><a class='button' href='/office/estimates?contact_id={quote(str(property_record.get('contact_id') or ''))}&property_id={quote(property_id)}'>Create estimate</a><a class='button' href='/office/documents?property_id={quote(property_id)}'>Send document</a>{manage}</div>
    <div class='grid two' style='margin-top:15px'><div class='card'><h2>{esc(property_record.get('name') or property_record.get('property_name'))}</h2><p><b>Customer:</b> {esc(_contact_name(str(property_record.get('contact_id') or ''), state))}</p><p><b>Address:</b> {esc(address)}</p><p><b>Type:</b> {esc(property_record.get('property_type'))}</p><p><b>Insurance:</b> {esc(property_record.get('insurance_company') or property_record.get('insurer'))}</p><p><b>Claim:</b> {esc(property_record.get('claim_number'))}</p><p><b>Notes:</b> {esc(property_record.get('notes'))}</p></div>
    <div class='card'><h2>Property summary</h2><div class='grid'><div class='metric'><small>Estimates</small><strong>{len(estimates)}</strong></div><div class='metric'><small>Invoices</small><strong>{len(invoices)}</strong></div><div class='metric'><small>Documents</small><strong>{len(documents)}</strong></div></div></div></div>
    <div class='card'><h2>Estimates</h2>{table(('Estimate','Status','Total'), [[f"<a href='/office/estimates/{esc(i.get('id'))}'>{esc(i.get('estimate_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('total_cents') if i.get('total_cents') is not None else int(round(float(i.get('totalValue') or 0)*100)))] for i in estimates])}</div>
    <div class='card'><h2>Invoices</h2>{table(('Invoice','Status','Balance'), [[f"<a href='/office/invoices/{esc(i.get('id'))}'>{esc(i.get('invoice_number') or _invoice_number(i))}</a>", badge(i.get('status')), money_cents(i.get('balance_cents') if i.get('balance_cents') is not None else int(round(float(i.get('amountDue') or 0)*100)))] for i in invoices])}</div>"""
    return _page(str(property_record.get("name") or property_record.get("property_name") or "Property"), body, "properties")


@app.get("/office/estimates")
async def estimates_page(contact_id: str = "", property_id: str = "") -> HTMLResponse:
    _require("estimates.view")
    state = await _state_page_data()
    provider_estimates = [item for item in _rows(state.get("gauzy_invoices")) if item.get("isEstimate") is True]
    local_estimates = store.records("estimates")
    rows = []
    seen = set()
    for item in local_estimates + provider_estimates:
        identity = str(item.get("id") or "")
        if identity in seen:
            continue
        seen.add(identity)
        total = item.get("total_cents")
        if total is None:
            total = int(round(float(item.get("totalValue") or 0) * 100))
        rows.append([
            f"<a href='/office/estimates/{esc(identity)}'>{esc(item.get('estimate_number') or _invoice_number(item))}</a>",
            esc(_contact_name(str(item.get("contact_id") or item.get("organizationContactId") or ""), state) or item.get("organizationContactName") or ""),
            badge(item.get("status")),
            money_cents(total, item.get("currency") or "USD"),
            esc(len(item.get("line_items") or item.get("invoiceItems") or [])),
            badge(item.get("source") or ("Imported" if item.get("legacyEstimateId") else "Gauzy")),
        ])
    create = ""
    if has_permission(_user(), "estimates.manage"):
        create = f"""<div class='card'><h2>Create estimate</h2><form method='post' action='/office/estimates/add'><div class='form-grid three'>
        <div class='field'><label>Customer</label><select name='contact_id' required>{_contact_options(state, contact_id)}</select></div><div class='field'><label>Property</label><select name='property_id'>{_property_options(property_id)}</select></div>
        <div class='field'><label>Estimate number</label><input name='estimate_number' value='{esc(_next_number('EST','estimates'))}' required></div>
        <div class='field full'><label>Title / scope header</label><input name='title' placeholder='Basement waterproofing and drainage improvements' required></div>
        <div class='field full'><label>Line items</label><textarea name='line_items' required placeholder='Interior drainage system | 80 | 125.00\nSump basin and pump | 1 | 895.00\nWall preparation | 500 | 3.25'></textarea><div class='muted'>One line per item: Description | Quantity | Unit price</div></div>
        <div class='field'><label>Status</label><select name='status'><option>DRAFT</option><option>SENT</option><option>ACCEPTED</option></select></div>
        <div class='field'><label>Deposit percent</label><input type='number' name='deposit_percent' min='0' max='100' step='0.01' value='30'></div>
        <div class='field'><label>Expiration days</label><input type='number' name='expiration_days' min='1' max='365' value='30'></div>
        <div class='field full'><label>Terms and notes</label><textarea name='terms'>Payment is due upon receipt of each issued invoice. Additional work requires a signed Change Order.</textarea></div></div>
        <button style='margin-top:12px'>Create estimate</button></form></div>"""
    body = f"{create}<div class='card'><h2>Estimates</h2>{table(('Estimate','Customer','Status','Total','Lines','Source'), rows)}</div><div class='callout'>For the complete Gauzy proposal, pipeline, estimate template, recurring invoice, and approval experience, open the full Gauzy ERP from All Applications.</div>"
    return _page("Estimates", body, "estimates")


@app.post("/office/estimates/add")
async def add_estimate(
    contact_id: str = Form(...),
    property_id: str = Form(default=""),
    estimate_number: str = Form(...),
    title: str = Form(...),
    line_items: str = Form(...),
    status: str = Form(default="DRAFT"),
    deposit_percent: float = Form(default=30.0),
    expiration_days: int = Form(default=30),
    terms: str = Form(default=""),
) -> RedirectResponse:
    actor = _require("estimates.manage")
    try:
        items, total_cents = _parse_line_items(line_items)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/estimates", status_code=303)
    state = await _state_page_data()
    contact_name = _contact_name(contact_id, state)
    provider_id = None
    provider_items = [
        {
            "description": item["description"],
            "quantity": item["quantity"],
            "price": item["unit_price_cents"] / 100,
            "totalValue": item["line_total_cents"] / 100,
            "applyTax": False,
            "applyDiscount": False,
        }
        for item in items
    ]
    try:
        created = await providers.create_invoice({
            "invoiceNumber": len(store.records("estimates")) + 1001,
            "invoiceDate": datetime.now(UTC).isoformat(),
            "dueDate": datetime.now(UTC).isoformat(),
            "status": status.upper(),
            "totalValue": total_cents / 100,
            "currency": "USD",
            "paid": False,
            "terms": terms.strip(),
            "organizationContactId": contact_id,
            "organizationContactName": contact_name,
            "toContactId": contact_id,
            "isEstimate": True,
            "isAccepted": status.upper() == "ACCEPTED",
            "invoiceType": "DETAILED_ITEMS",
        }, provider_items)
        provider_id = created.get("id")
    except Exception as exc:
        store.set_notice(f"Estimate saved locally; Gauzy bridge warning: {exc}")
    record = store.create_record("estimates", {
        "id": provider_id or str(uuid.uuid4()),
        "estimate_number": estimate_number.strip(),
        "contact_id": contact_id,
        "property_id": property_id or None,
        "title": title.strip(),
        "status": status.upper(),
        "currency": "USD",
        "line_items": items,
        "total_cents": total_cents,
        "deposit_percent": max(0, min(100, float(deposit_percent))),
        "expiration_days": max(1, int(expiration_days)),
        "terms": terms.strip(),
        "provider_id": provider_id,
    }, actor_id=actor.get("id"))
    notice = f"Estimate {record['estimate_number']} created."
    try:
        external = await _sync_financial_to_real_gauzy(
            "estimate", record, str(actor.get("id")), is_estimate=True
        )
        if external:
            notice += " Synced to genuine Gauzy under the property project."
    except Exception as exc:
        notice += f" Genuine Gauzy sync needs review: {exc}"
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
    items = estimate.get("line_items") or estimate.get("invoiceItems") or []
    line_rows = []
    for item in items:
        unit = item.get("unit_price_cents")
        total = item.get("line_total_cents")
        if unit is None:
            unit = int(round(float(item.get("price") or 0) * 100))
        if total is None:
            total = int(round(float(item.get("totalValue") or 0) * 100))
        line_rows.append([esc(item.get("description") or item.get("name")), esc(item.get("quantity")), money_cents(unit), money_cents(total)])
    total_cents = estimate.get("total_cents")
    if total_cents is None:
        total_cents = int(round(float(estimate.get("totalValue") or 0) * 100))
    actions = "<a class='button secondary' href='/office/estimates'>Back</a>"
    if store.record("estimates", estimate_id) and has_permission(_user(), "estimates.manage"):
        actions += f"<a class='button secondary' href='/office/estimates/{esc(estimate_id)}/edit'>Manage estimate</a>"
    if has_permission(_user(), "invoices.manage") and not estimate.get("converted_invoice_id"):
        actions += f"<form method='post' action='/office/estimates/{esc(estimate_id)}/convert'><button class='good'>Convert to due-now invoice</button></form>"
    body = f"""<div class='actions'>{actions}</div><div class='grid two' style='margin-top:15px'><div class='card'><h2>{esc(estimate.get('estimate_number') or _invoice_number(estimate))}</h2><p><b>Customer:</b> {esc(_contact_name(str(estimate.get('contact_id') or estimate.get('organizationContactId') or '')) or estimate.get('organizationContactName'))}</p><p><b>Title:</b> {esc(estimate.get('title') or '')}</p><p><b>Status:</b> {badge(estimate.get('status'))}</p><p><b>Total:</b> {money_cents(total_cents)}</p><p><b>Terms:</b> {esc(estimate.get('terms') or '')}</p></div>
    <div class='card'><h2>Payment plan</h2><p><b>Deposit:</b> {esc(estimate.get('deposit_percent') or 0)}%</p><p><b>Expiration:</b> {esc(estimate.get('expiration_days') or '')} days</p><p><b>Converted invoice:</b> {esc(estimate.get('converted_invoice_id') or 'Not yet')}</p></div></div>
    <div class='card'><h2>Line items</h2>{table(('Description','Quantity','Unit price','Line total'), line_rows)}</div>"""
    return _page(str(estimate.get("estimate_number") or "Estimate"), body, "estimates")


@app.post("/office/estimates/{estimate_id}/convert")
async def convert_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("invoices.manage")
    estimate = store.record("estimates", estimate_id)
    if not estimate:
        raise HTTPException(404, "Estimate not found")
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
        "line_items": estimate.get("line_items") or [],
        "total_cents": int(estimate.get("total_cents") or 0),
        "paid_cents": 0,
        "balance_cents": int(estimate.get("total_cents") or 0),
        "issued_at": now,
        "due_at": now,
        "terms": estimate.get("terms") or "Payment due upon receipt.",
    }, actor_id=actor.get("id"))
    store.update_record("estimates", estimate_id, {"status": "ACCEPTED", "converted_invoice_id": invoice["id"]}, actor_id=actor.get("id"))
    notice = f"Invoice {invoice['invoice_number']} issued and due immediately."
    try:
        external = await _sync_financial_to_real_gauzy(
            "invoice", invoice, str(actor.get("id")), is_estimate=False
        )
        if external:
            notice += " Synced to genuine Gauzy under the property project."
    except Exception as exc:
        notice += f" Genuine Gauzy sync needs review: {exc}"
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
            badge(item.get("status")),
            money_cents(total_cents, item.get("currency") or "USD"),
            money_cents(paid_cents, item.get("currency") or "USD"),
            money_cents(balance_cents, item.get("currency") or "USD"),
            esc(item.get("due_at") or item.get("dueDate") or ""),
            f"<a href='{esc(item.get('pdfUrl'))}' target='_blank'>Open PDF</a>" if item.get("pdfUrl") else "",
        ])
    create = ""
    if has_permission(_user(), "invoices.manage"):
        create = f"""<div class='card'><h2>Create and send due-now invoice</h2><form method='post' action='/office/invoices/add'><div class='form-grid three'>
        <div class='field'><label>Customer</label><select name='contact_id' required>{_contact_options(state, contact_id)}</select></div><div class='field'><label>Property</label><select name='property_id'>{_property_options(property_id)}</select></div>
        <div class='field'><label>Invoice number</label><input name='invoice_number' value='{esc(_next_number('INV','invoices'))}' required></div>
        <div class='field full'><label>Invoice title</label><input name='title' placeholder='Final service invoice' required></div>
        <div class='field full'><label>Line items</label><textarea name='line_items' required placeholder='Completed waterproofing scope | 1 | 12500.00'></textarea><div class='muted'>Description | Quantity | Unit price</div></div>
        <div class='field'><label>Status</label><select name='status'><option>SENT</option><option>DRAFT</option></select></div>
        <div class='field'><label>Send channel</label><select name='send_channel'><option value='LOCAL_CAPTURE'>Local email/SMS capture</option><option value='NONE'>Create only</option></select></div>
        <div class='field full'><label>Terms</label><textarea name='terms'>Payment is due upon receipt.</textarea></div></div><button style='margin-top:12px'>Create invoice</button></form></div>"""
    body = f"{create}<div class='card'><h2>Invoices</h2>{table(('Invoice','Customer','Status','Total','Paid','Balance','Due','PDF'), rows)}</div><div class='callout'>Floodman-created invoices set the exact issue time and due time to the same timestamp. The full Gauzy ERP also provides recurring invoices, received invoices, invoice templates, public links, email history and financial reports.</div>"
    return _page("Invoices", body, "invoices")


@app.post("/office/invoices/add")
async def add_invoice(
    contact_id: str = Form(...),
    property_id: str = Form(default=""),
    invoice_number: str = Form(...),
    title: str = Form(...),
    line_items: str = Form(...),
    status: str = Form(default="SENT"),
    send_channel: str = Form(default="LOCAL_CAPTURE"),
    terms: str = Form(default="Payment is due upon receipt."),
) -> RedirectResponse:
    actor = _require("invoices.manage")
    try:
        items, total_cents = _parse_line_items(line_items)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse("/office/invoices", status_code=303)
    now = datetime.now(UTC).isoformat()
    record = store.create_record("invoices", {
        "invoice_number": invoice_number.strip(),
        "contact_id": contact_id,
        "property_id": property_id or None,
        "title": title.strip(),
        "status": status.upper(),
        "currency": "USD",
        "line_items": items,
        "total_cents": total_cents,
        "paid_cents": 0,
        "balance_cents": total_cents,
        "issued_at": now if status.upper() == "SENT" else None,
        "due_at": now if status.upper() == "SENT" else None,
        "terms": terms.strip(),
        "send_channel": send_channel,
    }, actor_id=actor.get("id"))
    notice = f"Invoice {record['invoice_number']} created{' and due immediately' if record['status']=='SENT' else ''}."
    try:
        external = await _sync_financial_to_real_gauzy(
            "invoice", record, str(actor.get("id")), is_estimate=False
        )
        if external:
            notice += " Synced to genuine Gauzy under the property project."
    except Exception as exc:
        notice += f" Genuine Gauzy sync needs review: {exc}"
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
    items = invoice.get("line_items") or invoice.get("invoiceItems") or []
    line_rows = []
    for item in items:
        unit = item.get("unit_price_cents")
        total = item.get("line_total_cents")
        if unit is None:
            unit = int(round(float(item.get("price") or 0) * 100))
        if total is None:
            total = int(round(float(item.get("totalValue") or 0) * 100))
        line_rows.append([esc(item.get("description") or item.get("name")), esc(item.get("quantity")), money_cents(unit), money_cents(total)])
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
    payment_form = ""
    if has_permission(_user(), "payments.manage") and balance_cents > 0:
        payment_form = f"""<div class='card'><h2>Record payment</h2><form method='post' action='/office/invoices/{esc(invoice_id)}/payment'><div class='form-grid three'><div class='field'><label>Amount</label><input name='amount' value='{balance_cents/100:.2f}' required></div><div class='field'><label>Method</label><select name='method'><option>CREDIT_CARD</option><option>ACH</option><option>CHECK</option><option>CASH</option><option>OTHER</option></select></div><div class='field'><label>Reference</label><input name='reference'></div><div class='field full'><label>Note</label><input name='note'></div></div><button style='margin-top:12px'>Record payment</button></form></div>"""
    manage = f"<a class='button secondary' href='/office/invoices/{esc(invoice_id)}/edit'>Manage invoice</a>" if store.record("invoices", invoice_id) and has_permission(_user(), "invoices.manage") else ""
    body = f"""<div class='actions'><a class='button secondary' href='/office/invoices'>Back</a><a class='button' href='/office/documents?invoice_id={quote(invoice_id)}'>Send related document</a>{manage}</div>
    <div class='grid' style='margin-top:15px'><div class='card metric'><small>Total</small><strong>{money_cents(total_cents)}</strong></div><div class='card metric'><small>Paid</small><strong>{money_cents(paid_cents)}</strong></div><div class='card metric'><small>Balance</small><strong>{money_cents(balance_cents)}</strong></div><div class='card metric'><small>Status</small><strong>{badge(invoice.get('status'))}</strong></div></div>
    <div class='card'><h2>{esc(invoice.get('invoice_number') or _invoice_number(invoice))}</h2><p><b>Customer:</b> {esc(_contact_name(str(invoice.get('contact_id') or invoice.get('organizationContactId') or '')) or invoice.get('organizationContactName'))}</p><p><b>Issued:</b> {esc(invoice.get('issued_at') or invoice.get('invoiceDate') or '')}</p><p><b>Due:</b> {esc(invoice.get('due_at') or invoice.get('dueDate') or '')}</p><p><b>Terms:</b> {esc(invoice.get('terms') or '')}</p></div>
    <div class='card'><h2>Line items</h2>{table(('Description','Quantity','Unit price','Line total'), line_rows)}</div>{payment_form}
    <div class='card'><h2>Payments</h2>{table(('Date','Amount','Method','Reference'), [[esc(i.get('payment_date')), money_cents(i.get('amount_cents')), badge(i.get('method')), esc(i.get('reference'))] for i in payments])}</div>"""
    return _page(str(invoice.get("invoice_number") or "Invoice"), body, "invoices")


@app.post("/office/invoices/{invoice_id}/payment")
async def invoice_payment(
    invoice_id: str,
    amount: str = Form(...),
    method: str = Form(default="OTHER"),
    reference: str = Form(default=""),
    note: str = Form(default=""),
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
    payment = store.create_record("payments", {
        "invoice_id": invoice_id,
        "contact_id": invoice.get("contact_id"),
        "amount_cents": amount_cents,
        "currency": invoice.get("currency") or "USD",
        "method": method.upper(),
        "reference": reference.strip(),
        "note": note.strip(),
        "payment_date": datetime.now(UTC).isoformat(),
        "status": "COMPLETED",
    }, actor_id=actor.get("id"))
    new_paid = int(invoice.get("paid_cents") or 0) + amount_cents
    new_balance = max(0, int(invoice.get("total_cents") or 0) - new_paid)
    store.update_record("invoices", invoice_id, {
        "paid_cents": new_paid,
        "balance_cents": new_balance,
        "status": "PAID" if new_balance == 0 else "PARTIALLY_PAID",
    }, actor_id=actor.get("id"))
    try:
        await providers.record_payment({
            "invoiceId": invoice.get("provider_id") or invoice_id,
            "amount": amount_cents / 100,
            "currency": invoice.get("currency") or "USD",
            "paymentDate": payment["payment_date"],
            "paymentMethod": method.upper(),
            "note": note.strip(),
        })
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
            notice += " Synced to genuine Gauzy."
    except Exception as exc:
        notice += f" Genuine Gauzy payment sync needs review: {exc}"
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
    body = f"<div class='card'><h2>Payment ledger</h2>{table(('Date','Amount','Status','Method','Reference','Note'), rows)}</div><div class='callout'>Record manual cash, check, ACH, or card payments from an invoice. Square remains the payment authority once its sandbox or production connection is enabled.</div>"
    return _page("Payments", body, "payments")


@app.get("/office/apps")
def applications_page() -> HTMLResponse:
    _require("apps.view")
    cards = [
        ("Floodman Office", settings.public_url, "Owner command center, custom contacts, properties, jobs, billing, A/R, members, imports, messaging, and intelligence.", "Open command center"),
        ("Gauzy Operations Hub", settings.gauzy_hub_url, "The genuine Gauzy ERP with the Floodman launcher for RoomFlow, signing, receivables, messaging, imports, members, and AI competitor intelligence.", "Open main hub"),
        ("Documenso Signing", settings.documenso_web_url, "Create reusable templates and send Work Authorizations, Change Orders, Completion of Service forms, and other PDFs for signature.", "Open signing system"),
        ("RoomFlow", settings.roomflow_url, "Build property layouts, work scopes, estimates, invoices, and crew work orders from the field.", "Open RoomFlow"),
        ("AI Competitor Intelligence", f"{settings.public_url}/office/intelligence", "Monitor competitors, compare services and offers, identify content gaps, and generate evidence-backed Floodman opportunities.", "Open intelligence"),
        ("Local Email Inbox", settings.mailpit_url, "Inspect local account invites, document messages, invoices, receipts, and reminder emails without contacting real customers.", "Open Mailpit"),
        ("Engineering Sandbox", f"{settings.engineering_public_url}/lab", "Run the end-to-end mock workflow, sign documents, make test payments, simulate customer texts, and force reminders.", "Open lab"),
        ("Floodman API Explorer", f"{settings.api_public_url}/docs", "Inspect and test the orchestrator API used by RoomFlow, Square, signing, messaging, and receivables.", "Open API"),
    ]
    rendered = "".join(
        f"<div class='card app-card'><h2>{esc(name)}</h2><p>{esc(description)}</p><a class='button' href='{esc(url)}' target='_blank' rel='noreferrer'>{esc(action)}</a></div>"
        for name, url, description, action in cards
    )
    credentials = f"""<div class='card'><h2>Floodman business identity</h2><div class='grid two'>
    <div><h3>Primary Gauzy owner</h3><p><span class='mono'>{esc(settings.gauzy_admin_email)}</span></p><p class='muted'>The password is intentionally never displayed by the front end. Use the owner password chosen during Initialize-Floodman-Business.cmd.</p></div>
    <div><h3>Staff accounts</h3><p>Create employees and invitations inside native Gauzy, then assign Floodman module roles under Members &amp; Access.</p><p class='muted'>No seeded employee test account is enabled in clean business mode.</p></div></div></div>"""
    body = f"<div class='callout'><b>Gauzy is the main hub.</b> Its native ERP remains intact, while the Floodman launcher connects RoomFlow, signing, receivables, messaging, imports, members, and competitor intelligence in the same workspace.</div><div class='grid two'>{rendered}</div>{credentials}"
    return _page("All Applications", body, "apps")


@app.get("/office/documents")
async def documents_page(contact_id: str = "", invoice_id: str = "") -> HTMLResponse:
    _require("documents.view")
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
        actions = []
        if signing_url:
            actions.append(f"<a href='{esc(signing_url)}' target='_blank'>Sign / review</a>")
        if local_url:
            actions.append(f"<a href='{esc(local_url)}' target='_blank'>Original PDF</a>")
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
        <div class='field'><label>Customer</label><select name='contact_id'><option value=''>Select customer</option>{_contact_options(state, contact_id)}</select></div>
        <div class='field'><label>Related invoice ID</label><input name='invoice_id' value='{esc(invoice_id)}'></div>
        <div class='field full'><label>Document title</label><input name='title' placeholder='Work Authorization – 123 Main Street' required></div>
        <div class='field'><label>Signer name</label><input name='recipient_name' required></div><div class='field'><label>Signer email</label><input type='email' name='recipient_email' required></div>
        <div class='field full'><label>PDF file</label><input type='file' name='document' accept='application/pdf,.pdf' required><div class='muted'>The Engineering Sandbox stores the original PDF and creates a controlled signing envelope. Use full Documenso for visual field placement, reusable templates, multi-recipient routing, and production signing.</div></div></div><button style='margin-top:12px'>Create signing envelope</button></form></div>"""
    body = f"{create}<div class='actions'><a class='button' href='{esc(settings.documenso_web_url)}' target='_blank'>Open full Documenso</a></div><div class='card'><h2>Active signing documents</h2>{table(('Document','Status','Signer','Email','Timestamp','Action'), rows)}</div><div class='card'><h2>Imported document archive</h2>{table(('Document','Status','Signed','Legacy ID','File'), imported_rows)}</div>"
    return _page("Documents & Signing", body, "documents")


@app.post("/office/documents/add")
async def add_document(
    document_type: str = Form(...),
    contact_id: str = Form(default=""),
    invoice_id: str = Form(default=""),
    title: str = Form(...),
    recipient_name: str = Form(...),
    recipient_email: str = Form(...),
    document: UploadFile = File(...),
) -> RedirectResponse:
    actor = _require("documents.manage")
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
    body = f"<div class='grid two'><div class='card'><h2>Your time clock</h2>{action}</div><div class='card'><h2>Full Gauzy time tracking</h2><p>Use the genuine Gauzy interface for projects, tasks, timesheets, approvals, activity levels, screenshots, time-off, and employee reports.</p><a class='button' href='{esc(settings.gauzy_web_url)}' target='_blank'>Open Gauzy time tracking</a></div></div>{manual}<div class='card'><h2>Time entries</h2>{table(('Member','Job','Clock in','Clock out','Duration','Status','Approval','Note'), rows)}</div>"
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
    role_options = "".join(f"<option value='{esc(role)}'>{esc(role.replace('_',' ').title())}</option>" for role in ROLE_PERMISSIONS)
    user_rows = []
    for item in users:
        controls = badge(item.get("role")) if item.get("role") == "OWNER" else f"""<form method='post' action='/office/members/{esc(item.get('id'))}/update'><select name='role'>{''.join(f"<option value='{esc(role)}' {'selected' if role==item.get('role') else ''}>{esc(role)}</option>" for role in ROLE_PERMISSIONS if role!='OWNER')}</select><select name='status'><option value='ACTIVE' {'selected' if item.get('status')=='ACTIVE' else ''}>ACTIVE</option><option value='DISABLED' {'selected' if item.get('status')=='DISABLED' else ''}>DISABLED</option></select><input name='password' type='password' placeholder='Optional new password'><button>Save</button></form>"""
        source = item.get("auth_source") or ("GAUZY" if item.get("gauzy_user_id") else "LOCAL")
        user_rows.append([esc(item.get("name")), esc(item.get("email")), badge(item.get("role")), badge(source), badge(item.get("status")), controls])
    invite_rows = [[esc(item.get("name")), esc(item.get("email")), badge(item.get("role")), badge(item.get("status")), esc(item.get("expires_at"))] for item in invites]
    body = f"""<div class='card'><h2>Add a staff member</h2><p class='muted'><b>Recommended:</b> create or invite the employee in Gauzy first. They can then choose “Continue with Gauzy” when a Floodman module asks them to sign in, and their module account is provisioned automatically. Use the form below only for a Floodman-only account.</p><form method='post' action='/office/members/invite'><div class='form-grid three'><div class='field'><label>Name</label><input name='name' required></div><div class='field'><label>Email</label><input type='email' name='email' required></div><div class='field'><label>Role</label><select name='role'>{role_options}</select></div></div><button style='margin-top:12px'>Create invitation</button></form></div>
    <div class='actions'><a class='button' href='{esc(settings.gauzy_web_url)}/#/pages/employees' target='_top'>Open Gauzy employees</a><a class='button secondary' href='{esc(settings.gauzy_web_url)}/#/pages/employees/invites' target='_top'>Open Gauzy invitations</a></div><div class='card'><h2>Floodman module access</h2>{table(('Name','Email','Module role','Identity','Status','Administration'), user_rows)}</div><div class='card'><h2>Invitation history</h2>{table(('Name','Email','Role','Status','Expires'), invite_rows)}</div>"""
    return _page("Members & Roles", body, "members")


@app.post("/office/members/invite")
async def invite_member(name: str = Form(...), email: str = Form(...), role: str = Form(default="VIEWER")) -> HTMLResponse:
    actor = _require("members.manage")
    try:
        invite, token = store.create_invite(name, email, role, str(actor.get("id")))
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
        mail_status = "<div class='callout success'>The invitation email was captured by the local mail system. Open the Engineering Sandbox mail view, or Mailpit for messages produced by Gauzy and Documenso.</div>"
    except Exception as exc:
        mail_status = f"<div class='callout warning'>The account invitation was created, but email delivery was unavailable: {esc(exc)}</div>"
    body = f"<h1>Invitation created</h1>{mail_status}<p>Send this local invitation link to <b>{esc(invite.get('email'))}</b> if they did not receive the test email. It is shown once.</p><div class='callout'><span class='mono'>{esc(url)}</span></div><a class='button' href='{esc(url)}'>Open invitation</a> <a class='button secondary' href='/office/members'>Return to members</a>"
    return HTMLResponse(simple_page("Invitation created", body))


@app.post("/office/members/{user_id}/update")
def update_member(user_id: str, role: str = Form(...), status: str = Form(...), password: str = Form(default="")) -> RedirectResponse:
    _require("members.manage")
    try:
        store.update_user(user_id, role=role, status=status, password=password or None)
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


@app.get("/office/messages")
async def messages_page() -> HTMLResponse:
    _require("messages.view")
    state = await _state_page_data()
    sms = _rows(state.get("sms_messages"))
    emails = _rows(state.get("emails"))
    sms_rows = [[esc(item.get("created_at")), esc(item.get("to")), badge(item.get("status")), esc(item.get("body"))] for item in sms]
    email_rows = [[esc(item.get("received_at")), esc(", ".join(item.get("to") or [])), esc(item.get("subject")), f"<details><summary>Open</summary><pre>{esc(item.get('text') or item.get('html') or '')}</pre></details>"] for item in emails]
    send_form = ""
    if has_permission(_user(), "messages.manage"):
        send_form = """<div class='card'><h2>Send local test SMS</h2><form method='post' action='/office/messages/send'><div class='form-grid'><div class='field'><label>Phone</label><input name='phone' value='+13135550199' required></div><div class='field full'><label>Message</label><textarea name='body' required></textarea></div></div><button style='margin-top:12px'>Send message</button></form></div>"""
    body = f"{send_form}<div class='card'><h2>Outbound and automated SMS</h2>{table(('Time','To','Status','Message'), sms_rows)}</div><div class='card'><h2>Captured email</h2>{table(('Time','To','Subject','Body'), email_rows)}</div><div class='card'><h2>Try the AI text assistant</h2><form method='post' action='{esc(settings.engineering_public_url)}/lab/sms/inbound'><div class='form-grid'><div class='field full'><label>Customer message</label><input name='body' value='What is my balance?' required></div></div><button>Send local inbound SMS</button></form></div>"
    return _page("Messages", body, "messages")


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
    body = f"<div class='card'><h2>Automated accounts receivable</h2>{table(('Invoice','Status','Balance','Due','Next reminder','Sent'), rows)}</div><div class='card'><h2>Floodman Office open balances</h2>{table(('Invoice','Status','Balance','Due','Channel'), local_rows)}</div><div class='callout'>Invoices are due the moment they are sent. Production enrollment occurs through the orchestrator and Square webhook workflow; local Office invoices remain safe test records until that link is enabled.</div><div class='actions'><a class='button' href='{esc(settings.engineering_public_url)}/lab'>Open reminder simulator</a></div>"
    return _page("Receivables", body, "receivables")


@app.get("/office/alerts")
async def alerts_page() -> HTMLResponse:
    _require("alerts.view")
    state = await _state_page_data()
    alerts = _rows(state.get("staff_alerts"))
    rows = [[esc(item.get("created_at") or ""), badge(item.get("severity") or item.get("alert_status") or "OPEN"), esc(item.get("alert_type") or item.get("type") or ""), esc(item.get("message") or item.get("summary") or "")] for item in alerts]
    return _page("Staff Alerts", f"<div class='card'><h2>Staff alerts</h2>{table(('Created','Severity','Type','Message'), rows)}</div>", "alerts")


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
        raise HTTPException(404, "This record is imported or provider-owned. Edit it in the full Gauzy application.")
    return record


@app.get("/office/gauzy")
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
    <div class='card metric'><small>Gauzy Hub</small><strong>{connection}</strong></div>
    <div class='card metric'><small>Tenant ID</small><strong style='font-size:14px'>{esc(context.get('tenant_id') or 'Not discovered')}</strong></div>
    <div class='card metric'><small>Organization ID</small><strong style='font-size:14px'>{esc(context.get('organization_id') or 'Not discovered')}</strong></div>
    <div class='card metric'><small>Mapped records</small><strong>{len(mappings)}</strong></div></div>"""
    error_html = f"<div class='callout warning'><b>Gauzy is not reachable yet.</b><br>{esc(context_error)}<br><br>Run <code>Start-Floodman-Full-System.cmd</code> from C:\\FloodmanLab.</div>" if context_error else ""
    sync_status = badge("AUTOMATIC", "good") if settings.gauzy_sync_enabled else badge("LOCKED", "warn")
    sync_button = ""
    if has_permission(_user(), "connections.manage") and settings.gauzy_sync_enabled:
        sync_button = "<form method='post' action='/office/gauzy/sync'><button class='good'>Run recovery / historical sync</button></form>"
    elif has_permission(_user(), "connections.manage"):
        sync_button = "<div class='callout'><b>Synchronization is locked.</b> Set <code>GAUZY_FULL_SYNC_ENABLED=true</code> in <code>.env.windows</code> and restart the full system.</div>"
    body = f"""{status_html}{error_html}
    <div class='grid two'><div class='card'><h2>Gauzy is the main hub</h2><p>Open the complete Ever Gauzy ERP with the Floodman Operations launcher injected into the same interface. Gauzy remains fully native underneath, including employees, time tracking, projects, estimates, invoices, payments, inventory, reports and permissions.</p><div class='actions'><a class='button good' href='{esc(settings.gauzy_hub_url)}' target='_blank' rel='noreferrer'>Open Gauzy Hub</a><a class='button secondary' href='/office/apps'>Application directory</a></div><hr><p><b>Primary owner:</b> <span class='mono'>{esc(settings.gauzy_admin_email)}</span></p><p class='muted'>Clean business mode is non-demo. Passwords are never shown in this interface. Create staff accounts through Gauzy Employees &amp; Invitations.</p></div>
    <div class='card'><h2>Automatic Floodman → Gauzy data path</h2><p>Bridge state: {sync_status}</p><p>New RoomFlow jobs are sent directly through the Floodman Orchestrator into genuine Gauzy. The bridge creates or reuses the customer, creates a Gauzy project for the service property/job, then creates the estimate and attaches invoice items and payments to the same project.</p><p>The button below is only for recovery, local Office records and historical Townsquare imports.</p>{sync_button}</div></div>
    <div class='card'><h2>Native Gauzy modules included</h2><div class='grid two'>{''.join(f"<div class='callout success'>{esc(item)}</div>" for item in modules)}</div></div>
    <div class='card'><h2>Resolved integration context</h2><pre>GAUZY_BASE_URL=http://gauzy-api:3000/api
GAUZY_TENANT_ID={esc(context.get('tenant_id') or 'AUTO')}
GAUZY_ORGANIZATION_ID={esc(context.get('organization_id') or 'AUTO')}
GAUZY_FROM_ORGANIZATION_ID={esc(context.get('from_organization_id') or context.get('organization_id') or 'AUTO')}</pre><p class='muted'>AUTO discovery uses the administrator account and first accessible organization. Set explicit IDs in <code>.env.windows</code> when more than one Gauzy organization exists.</p></div>"""
    return _page("Gauzy Operations Hub", body, "gauzy")


@app.post("/office/gauzy/sync")
async def sync_full_gauzy() -> HTMLResponse:
    """Recovery and historical-import synchronization into the genuine Gauzy suite.

    Normal RoomFlow jobs are synchronized by the orchestrator as they are created. This
    owner-only action catches locally created Office records and historical Townsquare
    imports, preserving stable provider mappings so it remains safe to run repeatedly.
    """
    actor = _require("connections.manage")
    if not settings.gauzy_sync_enabled:
        raise HTTPException(409, "Gauzy synchronization is locked in .env.windows")
    context = await providers.gauzy_context()
    if not context.get("tenant_id") or not context.get("organization_id"):
        raise HTTPException(409, "Gauzy tenant and organization IDs could not be discovered.")

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
                    raise RuntimeError("Gauzy did not return a contact ID")
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
                    raise RuntimeError("Gauzy did not return a project ID")
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
                    raise RuntimeError("Gauzy did not return an ID")
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
        f"Gauzy recovery sync finished: {summary['contacts']} contacts, {summary['projects']} projects, "
        f"{summary['estimates']} estimates, {summary['invoices']} invoices, {summary['payments']} payments; "
        f"{len(summary['errors'])} errors."
    )
    result = f"<div class='card'><h2>Gauzy synchronization result</h2>{json_pre(summary)}<div class='actions'><a class='button' href='/office/gauzy'>Return</a><a class='button good' href='{esc(settings.gauzy_hub_url)}' target='_blank'>Open Gauzy Hub</a></div></div>"
    return _page("Gauzy Synchronization", result, "gauzy")


@app.get("/office/signing")
def signing_suite_page() -> HTMLResponse:
    _require("documents.view")
    body = f"""<div class='grid two'><div class='card'><h2>Floodman document workflow</h2><p>Create a PDF, select the customer, choose Work Authorization, Change Order, Completion of Service, or a custom type, then send it through the local signing workflow.</p><div class='actions'><a class='button' href='/office/documents'>Create signing request</a><a class='button secondary' href='{esc(settings.engineering_public_url)}/lab' target='_blank'>Open workflow lab</a></div></div><div class='card'><h2>Full Documenso application</h2><p>The full-system profile also starts the genuine signing application for reusable templates, teams, recipients, fields, and signing history.</p><a class='button good' href='{esc(settings.documenso_web_url)}' target='_blank'>Open Documenso</a><p class='muted'>Create the first local account on its sign-up page. Verification email appears in Mailpit.</p></div></div><div class='card'><h2>Document types</h2><div class='grid'><div class='callout'>Work Authorization and deposit terms</div><div class='callout'>Change Orders and revised contract totals</div><div class='callout'>Completion of Service and final-balance release</div><div class='callout'>Custom disclosures, warranties, inspection forms, and acknowledgements</div></div></div>"""
    return _page("Documents & Signing Suite", body, "signing")


@app.get("/office/contacts/{contact_id}/edit")
def edit_contact_page(contact_id: str) -> HTMLResponse:
    _require("contacts.manage")
    item = _local_record_or_404("contacts", contact_id)
    body = f"""<div class='card'><h2>Edit contact</h2><form method='post' action='/office/contacts/{esc(contact_id)}/edit'><div class='form-grid three'><div class='field'><label>First name</label><input name='first_name' value='{esc(item.get('first_name'))}' required></div><div class='field'><label>Last name</label><input name='last_name' value='{esc(item.get('last_name'))}' required></div><div class='field'><label>Company</label><input name='company' value='{esc(item.get('company'))}'></div><div class='field'><label>Email</label><input type='email' name='email' value='{esc(item.get('email'))}'></div><div class='field'><label>Phone</label><input name='phone' value='{esc(item.get('phone'))}'></div><div class='field'><label>Lead source</label><input name='lead_source' value='{esc(item.get('lead_source'))}'></div><div class='field full'><label>Notes</label><textarea name='notes'>{esc(item.get('notes'))}</textarea></div></div><div class='actions' style='margin-top:12px'><button>Save changes</button><a class='button secondary' href='/office/contacts/{esc(contact_id)}'>Cancel</a></div></form></div><div class='card danger'><h2>Delete contact</h2><p>Deletion is blocked when local properties, estimates, or invoices still reference this contact.</p><form method='post' action='/office/contacts/{esc(contact_id)}/delete'><button class='danger'>Delete contact</button></form></div>"""
    return _page("Edit Contact", body, "contacts")


@app.post("/office/contacts/{contact_id}/edit")
def update_contact(contact_id: str, first_name: str = Form(...), last_name: str = Form(...), company: str = Form(default=""), email: str = Form(default=""), phone: str = Form(default=""), lead_source: str = Form(default=""), notes: str = Form(default="")) -> RedirectResponse:
    actor = _require("contacts.manage")
    _local_record_or_404("contacts", contact_id)
    name = " ".join(filter(None, [first_name.strip(), last_name.strip()]))
    store.update_record("contacts", contact_id, {"first_name": first_name.strip(), "last_name": last_name.strip(), "name": name, "company": company.strip(), "email": email.strip(), "phone": phone.strip(), "lead_source": lead_source.strip(), "notes": notes.strip()}, actor_id=str(actor.get("id")))
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
    body = f"""<div class='card'><h2>Edit property</h2><form method='post' action='/office/properties/{esc(property_id)}/edit'><div class='form-grid three'><div class='field'><label>Property name</label><input name='name' value='{esc(item.get('name'))}' required></div><div class='field'><label>Property type</label><input name='property_type' value='{esc(item.get('property_type'))}'></div><div class='field'><label>Customer ID</label><input name='contact_id' value='{esc(item.get('contact_id'))}' required></div><div class='field full'><label>Service street</label><input name='service_street' value='{esc(item.get('service_street'))}' required></div><div class='field'><label>City</label><input name='service_city' value='{esc(item.get('service_city'))}' required></div><div class='field'><label>State</label><input name='service_state' value='{esc(item.get('service_state'))}' required></div><div class='field'><label>Postal code</label><input name='service_postal_code' value='{esc(item.get('service_postal_code'))}' required></div><div class='field'><label>Insurance company</label><input name='insurance_company' value='{esc(item.get('insurance_company'))}'></div><div class='field'><label>Claim number</label><input name='claim_number' value='{esc(item.get('claim_number'))}'></div><div class='field full'><label>Notes</label><textarea name='notes'>{esc(item.get('notes'))}</textarea></div></div><div class='actions' style='margin-top:12px'><button>Save changes</button><a class='button secondary' href='/office/properties/{esc(property_id)}'>Cancel</a></div></form></div><div class='card danger'><form method='post' action='/office/properties/{esc(property_id)}/delete'><button class='danger'>Delete property</button></form></div>"""
    return _page("Edit Property", body, "properties")


@app.post("/office/properties/{property_id}/edit")
def update_property(property_id: str, contact_id: str = Form(...), name: str = Form(...), property_type: str = Form(default="Residential"), service_street: str = Form(...), service_city: str = Form(...), service_state: str = Form(default="MI"), service_postal_code: str = Form(...), insurance_company: str = Form(default=""), claim_number: str = Form(default=""), notes: str = Form(default="")) -> RedirectResponse:
    actor = _require("properties.manage")
    _local_record_or_404("properties", property_id)
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
    lines = "\n".join(f"{line.get('description') or line.get('name')} | {line.get('quantity') or 1} | {int(line.get('unit_price_cents') or 0)/100:.2f}" for line in item.get("line_items") or [])
    body = f"""<div class='card'><h2>Edit estimate</h2><form method='post' action='/office/estimates/{esc(estimate_id)}/edit'><div class='form-grid'><div class='field'><label>Estimate number</label><input name='estimate_number' value='{esc(item.get('estimate_number'))}' required></div><div class='field'><label>Title</label><input name='title' value='{esc(item.get('title'))}' required></div><div class='field full'><label>Line items</label><textarea name='line_items' required>{esc(lines)}</textarea></div><div class='field full'><label>Terms</label><textarea name='terms'>{esc(item.get('terms'))}</textarea></div></div><div class='actions' style='margin-top:12px'><button>Save draft</button><a class='button secondary' href='/office/estimates/{esc(estimate_id)}'>Cancel</a></div></form></div><div class='card'><div class='actions'><form method='post' action='/office/estimates/{esc(estimate_id)}/send'><button>Mark sent</button></form><form method='post' action='/office/estimates/{esc(estimate_id)}/accept'><button class='good'>Mark accepted</button></form><form method='post' action='/office/estimates/{esc(estimate_id)}/delete'><button class='danger'>Delete draft</button></form></div></div>"""
    return _page("Edit Estimate", body, "estimates")


@app.post("/office/estimates/{estimate_id}/edit")
def update_estimate(estimate_id: str, estimate_number: str = Form(...), title: str = Form(...), line_items: str = Form(...), terms: str = Form(default="")) -> RedirectResponse:
    actor = _require("estimates.manage")
    item = _local_record_or_404("estimates", estimate_id)
    if str(item.get("status") or "DRAFT").upper() not in {"DRAFT", "SENT", "VIEWED"}:
        store.set_notice("Accepted or converted estimates are immutable. Create a revision or Change Order instead.")
        return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)
    try:
        lines, total_cents = _parse_line_items(line_items)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/estimates/{estimate_id}/edit", status_code=303)
    store.update_record("estimates", estimate_id, {"estimate_number": estimate_number.strip(), "title": title.strip(), "line_items": lines, "total_cents": total_cents, "terms": terms.strip()}, actor_id=str(actor.get("id")))
    store.set_notice("Estimate updated.")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/send")
def send_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("estimates.manage")
    _local_record_or_404("estimates", estimate_id)
    store.update_record("estimates", estimate_id, {"status": "SENT", "sent_at": datetime.now(UTC).isoformat()}, actor_id=str(actor.get("id")))
    store.set_notice("Estimate marked sent. Local mode records the event without contacting a real customer.")
    return RedirectResponse(f"/office/estimates/{estimate_id}", status_code=303)


@app.post("/office/estimates/{estimate_id}/accept")
def accept_estimate(estimate_id: str) -> RedirectResponse:
    actor = _require("estimates.manage")
    _local_record_or_404("estimates", estimate_id)
    store.update_record("estimates", estimate_id, {"status": "ACCEPTED", "accepted_at": datetime.now(UTC).isoformat()}, actor_id=str(actor.get("id")))
    store.set_notice("Estimate accepted. It can now be converted into an invoice.")
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
    lines = "\n".join(f"{line.get('description') or line.get('name')} | {line.get('quantity') or 1} | {int(line.get('unit_price_cents') or 0)/100:.2f}" for line in item.get("line_items") or [])
    is_draft = str(item.get("status") or "DRAFT").upper() == "DRAFT"
    edit_form = f"""<div class='card'><h2>Edit draft invoice</h2><form method='post' action='/office/invoices/{esc(invoice_id)}/edit'><div class='form-grid'><div class='field'><label>Invoice number</label><input name='invoice_number' value='{esc(item.get('invoice_number'))}' required></div><div class='field'><label>Title</label><input name='title' value='{esc(item.get('title'))}' required></div><div class='field full'><label>Line items</label><textarea name='line_items' required>{esc(lines)}</textarea></div><div class='field full'><label>Terms</label><textarea name='terms'>{esc(item.get('terms'))}</textarea></div></div><button style='margin-top:12px'>Save draft</button></form></div>""" if is_draft else "<div class='callout warning'>Sent financial records are not edited in place. Void the invoice or issue a corrected invoice / credit according to company policy.</div>"
    actions = f"""<div class='card'><div class='actions'>{f"<form method='post' action='/office/invoices/{esc(invoice_id)}/send'><button class='good'>Send due now</button></form>" if is_draft else ''}<form method='post' action='/office/invoices/{esc(invoice_id)}/void'><button class='danger'>Void invoice</button></form>{f"<form method='post' action='/office/invoices/{esc(invoice_id)}/delete'><button class='danger'>Delete draft</button></form>" if is_draft else ''}</div></div>"""
    return _page("Manage Invoice", edit_form + actions, "invoices")


@app.post("/office/invoices/{invoice_id}/edit")
def update_invoice_local(invoice_id: str, invoice_number: str = Form(...), title: str = Form(...), line_items: str = Form(...), terms: str = Form(default="")) -> RedirectResponse:
    actor = _require("invoices.manage")
    item = _local_record_or_404("invoices", invoice_id)
    if str(item.get("status") or "DRAFT").upper() != "DRAFT":
        store.set_notice("Only draft invoices can be edited.")
        return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)
    try:
        lines, total_cents = _parse_line_items(line_items)
    except ValueError as exc:
        store.set_notice(str(exc))
        return RedirectResponse(f"/office/invoices/{invoice_id}/edit", status_code=303)
    store.update_record("invoices", invoice_id, {"invoice_number": invoice_number.strip(), "title": title.strip(), "line_items": lines, "total_cents": total_cents, "balance_cents": total_cents - int(item.get("paid_cents") or 0), "terms": terms.strip()}, actor_id=str(actor.get("id")))
    store.set_notice("Invoice draft updated.")
    return RedirectResponse(f"/office/invoices/{invoice_id}", status_code=303)


@app.post("/office/invoices/{invoice_id}/send")
def send_invoice_due_now(invoice_id: str) -> RedirectResponse:
    actor = _require("invoices.manage")
    _local_record_or_404("invoices", invoice_id)
    now = datetime.now(UTC).isoformat()
    store.update_record("invoices", invoice_id, {"status": "SENT", "issued_at": now, "due_at": now}, actor_id=str(actor.get("id")))
    store.set_notice("Invoice sent in local capture mode and is due immediately.")
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
