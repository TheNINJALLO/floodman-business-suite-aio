from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import html
import json
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from typing import Any
from urllib.parse import parse_qs

import httpx
try:
    from aiosmtpd.controller import Controller
except ImportError:  # Allows unit tests to run without the optional SMTP server dependency.
    Controller = None  # type: ignore[assignment,misc]
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .archive_import import apply_historical_import
from .persistence import JsonStateFile
from .util import classify_start_state, make_pdf, twilio_signature


ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:9004").rstrip("/")
LAB_PUBLIC_URL = os.getenv("LAB_PUBLIC_URL", "http://localhost:9003").rstrip("/")
LAB_INTERNAL_URL = os.getenv("LOCAL_LAB_URL", "http://127.0.0.1:9003").rstrip("/")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:9004").rstrip("/")
SQUARE_WEBHOOK_SIGNATURE_KEY = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY", "local-square-signature-key")
DOCUMENSO_WEBHOOK_SECRET = os.getenv("DOCUMENSO_WEBHOOK_SECRET", "local-documenso-webhook-secret")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "local-twilio-auth-token")
TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "+13135550100")
INTERNAL_HMAC_KEYS = os.getenv("INTERNAL_HMAC_KEYS", "")
MESSAGING_AI_URL = os.getenv("MESSAGING_AI_URL", "http://messaging-ai-api:8100").rstrip("/")
COMPETITOR_INTEL_URL = os.getenv("COMPETITOR_INTEL_URL", "http://competitor-intel-api:8090").rstrip("/")
FLOODMAN_RELEASE = os.getenv("FLOODMAN_RELEASE", "windows-business-suite-v3.0.0")
FLOODMAN_ENV = os.getenv("FLOODMAN_ENV", "development").lower()


def _parse_hmac_key() -> tuple[str, bytes]:
    for entry in INTERNAL_HMAC_KEYS.split(","):
        entry = entry.strip()
        if not entry or ":" not in entry:
            continue
        key_id, encoded = entry.split(":", 1)
        return key_id, base64.b64decode(encoded)
    raise RuntimeError("INTERNAL_HMAC_KEYS is missing from local-lab")


INTERNAL_KEY_ID, INTERNAL_SECRET = _parse_hmac_key()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")


def _internal_headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    digest = hmac.new(INTERNAL_SECRET, timestamp.encode("ascii") + b"." + body, hashlib.sha256).digest()
    return {
        "x-floodman-key-id": INTERNAL_KEY_ID,
        "x-floodman-timestamp": timestamp,
        "x-floodman-signature": base64.b64encode(digest).decode("ascii"),
        "content-type": "application/json",
    }


async def call_orchestrator(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = b"" if payload is None else _json_bytes(payload)
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(
            method,
            f"{ORCHESTRATOR_URL}{path}",
            content=body if body else None,
            headers=_internal_headers(body),
        )
    if response.is_error:
        raise RuntimeError(f"Orchestrator {method} {path} failed: {response.status_code} {response.text[:1000]}")
    if not response.content:
        return {}
    value = response.json()
    return dict(value) if isinstance(value, dict) else {"value": value}


class LabState:
    PERSISTED_FIELDS = (
        "contacts",
        "properties",
        "gauzy_invoices",
        "gauzy_payments",
        "square_customers",
        "square_orders",
        "square_invoices",
        "square_idempotency",
        "envelopes",
        "items",
        "sms_messages",
        "emails",
        "imported_documents",
        "notes",
        "legacy_mappings",
        "import_previews",
        "import_runs",
        "setup",
        "import_sessions",
        "import_history",
        "imported_records",
        "demo_job_id",
        "demo_portal_url",
        "last_action",
        "counters",
    )

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.store = JsonStateFile()
        loaded = self.store.load()
        if loaded:
            self._restore(loaded)
        else:
            self.reset(preserve_setup=False)

    @staticmethod
    def default_setup() -> dict[str, Any]:
        return {
            "company": {
                "name": "Floodman",
                "office_email": "office@example.com",
                "billing_email": "billing@example.com",
                "phone": "+13135550100",
                "timezone": "America/Detroit",
                "currency": "USD",
            },
            "roomflow": {
                "mode": "ONLINE",
                "web_url": "https://theninjallo.github.io/roomflow/",
                "organization_id": "floodman-local",
                "edge_function_configured": False,
            },
            "gauzy": {"mode": "MOCK", "base_url": f"{LAB_PUBLIC_URL}/gauzy", "linked": True},
            "square": {"mode": "MOCK", "base_url": f"{LAB_PUBLIC_URL}/square", "linked": True},
            "documenso": {"mode": "MOCK", "base_url": f"{LAB_PUBLIC_URL}/documenso", "linked": True},
            "twilio": {"mode": "MOCK", "base_url": f"{LAB_PUBLIC_URL}/twilio", "linked": True, "a2p_approved": False},
            "email": {"mode": "CAPTURE", "inbox_url": f"{LAB_PUBLIC_URL}/office#/mail", "linked": True},
            "ai": {"mode": "DETERMINISTIC", "customer_auto_reply": False, "linked": True},
            "launch": {"legal_templates_approved": False, "migration_reconciled": False, "ready_for_production": False},
        }

    def _initialize_empty(self, setup: dict[str, Any] | None = None) -> None:
        self.contacts: dict[str, dict[str, Any]] = {}
        self.properties: dict[str, dict[str, Any]] = {}
        self.gauzy_invoices: dict[str, dict[str, Any]] = {}
        self.gauzy_payments: dict[str, dict[str, Any]] = {}
        self.square_customers: dict[str, dict[str, Any]] = {}
        self.square_orders: dict[str, dict[str, Any]] = {}
        self.square_invoices: dict[str, dict[str, Any]] = {}
        self.square_idempotency: dict[str, str] = {}
        self.envelopes: dict[str, dict[str, Any]] = {}
        self.items: dict[str, dict[str, Any]] = {}
        self.sms_messages: list[dict[str, Any]] = []
        self.emails: list[dict[str, Any]] = []
        self.imported_documents: dict[str, dict[str, Any]] = {}
        self.notes: dict[str, dict[str, Any]] = {}
        self.legacy_mappings: dict[str, dict[str, str]] = {
            "contacts": {}, "properties": {}, "estimates": {}, "estimate_lines": {},
            "invoices": {}, "payments": {}, "documents": {}, "notes": {}
        }
        self.import_previews: dict[str, dict[str, Any]] = {}
        self.import_runs: list[dict[str, Any]] = []
        self.import_sessions: dict[str, dict[str, Any]] = {}
        self.import_history: list[dict[str, Any]] = []
        self.imported_records: dict[str, dict[str, dict[str, Any]]] = {
            kind: {} for kind in ("contacts", "properties", "estimates", "invoices", "payments", "documents", "notes")
        }
        self.setup: dict[str, Any] = setup or self.default_setup()
        self.demo_job_id: str | None = None
        self.demo_portal_url: str | None = None
        self.last_action = "Lab initialized"
        self.counters: dict[str, int] = {}

    def reset(self, preserve_setup: bool = True) -> None:
        with getattr(self, "lock", threading.RLock()):
            prior_setup = getattr(self, "setup", None) if preserve_setup else None
            self._initialize_empty(prior_setup)
            self.save()

    def _restore(self, value: dict[str, Any]) -> None:
        with self.lock:
            self._initialize_empty()
            for name in self.PERSISTED_FIELDS:
                if name in value:
                    setattr(self, name, value[name])
            if not isinstance(getattr(self, "setup", None), dict):
                self.setup = self.default_setup()
            if not isinstance(getattr(self, "legacy_mappings", None), dict):
                self.legacy_mappings = {}
            for key in ("contacts", "properties", "estimates", "estimate_lines", "invoices", "payments", "documents", "notes"):
                self.legacy_mappings.setdefault(key, {})
            if not isinstance(getattr(self, "imported_records", None), dict):
                self.imported_records = {}
            for key in ("contacts", "properties", "estimates", "invoices", "payments", "documents", "notes"):
                self.imported_records.setdefault(key, {})
            if not isinstance(getattr(self, "import_sessions", None), dict):
                self.import_sessions = {}
            if not isinstance(getattr(self, "import_history", None), list):
                self.import_history = []
            self.rebuild_counters()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {name: getattr(self, name) for name in self.PERSISTED_FIELDS}

    def save(self) -> None:
        self.store.save(self.snapshot())

    def restore_api_snapshot(self, payload: dict[str, Any]) -> None:
        """Restore the public v1.1.x state shape after the front-end update."""
        with self.lock:
            self.demo_job_id = payload.get("demo_job_id") or self.demo_job_id
            for source_key, target_name in (
                ("gauzy_contacts", "contacts"),
                ("properties", "properties"),
                ("gauzy_invoices", "gauzy_invoices"),
                ("gauzy_payments", "gauzy_payments"),
                ("square_orders", "square_orders"),
                ("square_invoices", "square_invoices"),
                ("envelopes", "envelopes"),
                ("documenso_items", "items"),
                ("imported_documents", "imported_documents"),
                ("notes", "notes"),
            ):
                values = payload.get(source_key)
                if isinstance(values, list):
                    setattr(
                        self,
                        target_name,
                        {str(item.get("id")): dict(item) for item in values if isinstance(item, dict) and item.get("id")},
                    )
            if isinstance(payload.get("sms_messages"), list):
                self.sms_messages = payload["sms_messages"]
            if isinstance(payload.get("emails"), list):
                self.emails = payload["emails"]
            if isinstance(payload.get("legacy_mappings"), dict):
                for key, mapping in payload["legacy_mappings"].items():
                    if key in self.legacy_mappings and isinstance(mapping, dict):
                        self.legacy_mappings[key].update({str(k): str(v) for k, v in mapping.items()})
            if isinstance(payload.get("import_runs"), list):
                self.import_runs = list(payload["import_runs"])
            self.last_action = str(payload.get("last_action") or "Restored state after Floodman Office update")

            # Rebuild private mock records that were not exposed by the older /api/state endpoint.
            for invoice in self.square_invoices.values():
                order_id = str(invoice.get("order_id") or self.next_id("sorder"))
                invoice["order_id"] = order_id
                total = sum(
                    int((request.get("computed_amount_money") or {}).get("amount") or 0)
                    for request in invoice.get("payment_requests") or []
                )
                currency = str((invoice.get("next_payment_amount_money") or {}).get("currency") or "USD")
                self.square_orders[order_id] = {
                    "id": order_id,
                    "state": "COMPLETED" if invoice.get("status") == "PAID" else "OPEN",
                    "version": 1,
                    "total_money": {"amount": total, "currency": currency},
                    "line_items": [],
                }
            for envelope in self.envelopes.values():
                for item in envelope.get("items") or []:
                    item_id = str(item.get("id") or self.next_id("item"))
                    item["id"] = item_id
                    self.items.setdefault(
                        item_id,
                        {
                            "id": item_id,
                            "envelope_id": envelope.get("id"),
                            "pdf": make_pdf(
                                str(envelope.get("title") or "Restored local document"),
                                "Restored after the Floodman Office front-end update.",
                            ),
                        },
                    )
            self.rebuild_counters()
        self.save()

    def rebuild_counters(self) -> None:
        pattern = re.compile(r"^([A-Za-z][A-Za-z0-9-]*)_(\d+)$")
        candidates: list[str] = []
        for mapping in (
            self.contacts, self.properties, self.gauzy_invoices, self.gauzy_payments,
            self.square_customers, self.square_orders, self.square_invoices,
            self.envelopes, self.items, self.imported_documents, self.notes,
        ):
            candidates.extend(str(identifier) for identifier in mapping)
        for collection in (self.sms_messages, self.emails, self.import_runs, self.import_history):
            candidates.extend(
                str(item.get("id")) for item in collection
                if isinstance(item, dict) and item.get("id")
            )
        for identifier in candidates:
            match = pattern.match(identifier)
            if match:
                prefix, number = match.groups()
                self.counters[prefix] = max(self.counters.get(prefix, 0), int(number))

    def next_id(self, prefix: str) -> str:
        with self.lock:
            self.counters[prefix] = self.counters.get(prefix, 0) + 1
            return f"{prefix}_{self.counters[prefix]:04d}"


state = LabState()


class MailHandler:
    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:
        raw = bytes(envelope.original_content or envelope.content or b"")
        parsed = BytesParser(policy=policy.default).parsebytes(raw)
        text = ""
        html_body = ""
        if parsed.is_multipart():
            for part in parsed.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain" and not text:
                    text = str(part.get_content())
                elif ctype == "text/html" and not html_body:
                    html_body = str(part.get_content())
        else:
            content = str(parsed.get_content())
            if parsed.get_content_type() == "text/html":
                html_body = content
            else:
                text = content
        message = {
            "id": state.next_id("mail"),
            "received_at": datetime.now(UTC).isoformat(),
            "from": str(parsed.get("From") or envelope.mail_from),
            "to": [str(value) for value in envelope.rcpt_tos],
            "subject": str(parsed.get("Subject") or ""),
            "text": text,
            "html": html_body,
        }
        with state.lock:
            state.emails.insert(0, message)
            state.emails[:] = state.emails[:100]
        return "250 Message accepted for local testing"


smtp_controller: Any | None = None


async def _persist_state_loop() -> None:
    while True:
        await asyncio.sleep(2)
        try:
            state.save()
        except Exception:
            # Persistence must never interrupt provider simulation requests.
            pass


@asynccontextmanager
async def lifespan(_: FastAPI):
    global smtp_controller
    if Controller is not None:
        smtp_controller = Controller(MailHandler(), hostname="0.0.0.0", port=1025)
        smtp_controller.start()
    persist_task = asyncio.create_task(_persist_state_loop())
    try:
        yield
    finally:
        persist_task.cancel()
        try:
            await persist_task
        except asyncio.CancelledError:
            pass
        state.save()
        if smtp_controller is not None:
            smtp_controller.stop()


app = FastAPI(title="Floodman Engineering Sandbox", version=FLOODMAN_RELEASE, lifespan=lifespan)


@app.get("/health/live")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "floodman-local-lab"}


# ---------------------------------------------------------------------------
# Local PDF sources
# ---------------------------------------------------------------------------
@app.get("/files/{name}.pdf")
def pdf_source(name: str) -> Response:
    title = name.replace("-", " ").title()
    return Response(make_pdf(title, "Floodman engineering-sandbox document. Not a legal production form."), media_type="application/pdf")


# ---------------------------------------------------------------------------
# Gauzy-compatible mock
# ---------------------------------------------------------------------------
@app.post("/gauzy/auth/login")
def gauzy_login() -> dict[str, str]:
    return {"token": "local-gauzy-token"}


@app.get("/gauzy/organization-contact/")
def gauzy_contacts() -> dict[str, Any]:
    return {"items": list(state.contacts.values()), "total": len(state.contacts)}


@app.post("/gauzy/organization-contact/")
def gauzy_contact_create(payload: dict[str, Any]) -> dict[str, Any]:
    contact_id = state.next_id("gcontact")
    record = {"id": contact_id, **payload}
    state.contacts[contact_id] = record
    return record


@app.get("/gauzy/invoices")
def gauzy_invoice_list() -> dict[str, Any]:
    return {"items": list(state.gauzy_invoices.values()), "total": len(state.gauzy_invoices)}


@app.post("/gauzy/invoices")
def gauzy_invoice_create(payload: dict[str, Any]) -> dict[str, Any]:
    invoice_id = state.next_id("ginvoice")
    record = {"id": invoice_id, "invoiceItems": [], "payments": [], "token": None, **payload}
    state.gauzy_invoices[invoice_id] = record
    return record


@app.put("/gauzy/invoices/generate/{invoice_id}")
def gauzy_invoice_link(invoice_id: str) -> dict[str, Any]:
    record = state.gauzy_invoices.get(invoice_id)
    if not record:
        raise HTTPException(404, "invoice not found")
    record["token"] = f"local-{invoice_id}"
    return record


@app.get("/gauzy/invoices/{invoice_id}")
def gauzy_invoice_get(invoice_id: str) -> dict[str, Any]:
    record = state.gauzy_invoices.get(invoice_id)
    if not record:
        raise HTTPException(404, "invoice not found")
    return record


@app.put("/gauzy/invoices/{invoice_id}")
def gauzy_invoice_update(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = state.gauzy_invoices.get(invoice_id)
    if not record:
        raise HTTPException(404, "invoice not found")
    record.update(payload)
    return record


@app.put("/gauzy/invoices/{invoice_id}/action")
def gauzy_invoice_action(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = state.gauzy_invoices.get(invoice_id)
    if not record:
        raise HTTPException(404, "invoice not found")
    record.update(payload)
    return record


@app.post("/gauzy/invoice-item/bulk/{invoice_id}")
def gauzy_items(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    record = state.gauzy_invoices.get(invoice_id)
    if not record:
        raise HTTPException(404, "invoice not found")
    new_items = []
    for item in payload.get("list") or []:
        new_items.append({"id": state.next_id("gitem"), **item})
    record.setdefault("invoiceItems", []).extend(new_items)
    return {"items": new_items}


@app.get("/gauzy/payments/")
def gauzy_payment_list() -> dict[str, Any]:
    return {"items": list(state.gauzy_payments.values()), "total": len(state.gauzy_payments)}


@app.post("/gauzy/payments/")
def gauzy_payment_create(payload: dict[str, Any]) -> dict[str, Any]:
    payment_id = state.next_id("gpayment")
    record = {"id": payment_id, **payload}
    state.gauzy_payments[payment_id] = record
    invoice_id = str(payload.get("invoiceId") or "")
    if invoice_id in state.gauzy_invoices:
        state.gauzy_invoices[invoice_id].setdefault("payments", []).append(record)
    return record


# ---------------------------------------------------------------------------
# Square-compatible mock
# ---------------------------------------------------------------------------
@app.get("/square/v2/locations/{location_id}")
def square_location(location_id: str) -> dict[str, Any]:
    return {"location": {"id": location_id, "status": "ACTIVE", "name": "Floodman Engineering Sandbox"}}


@app.post("/square/v2/customers/search")
def square_customer_search(payload: dict[str, Any]) -> dict[str, Any]:
    exact = (((payload.get("query") or {}).get("filter") or {}).get("email_address") or {}).get("exact")
    values = list(state.square_customers.values())
    if exact:
        values = [item for item in values if item.get("email_address", "").lower() == str(exact).lower()]
    return {"customers": values}


@app.post("/square/v2/customers")
def square_customer_create(payload: dict[str, Any]) -> dict[str, Any]:
    customer_id = state.next_id("scustomer")
    record = {"id": customer_id, **{k: v for k, v in payload.items() if k != "idempotency_key"}}
    state.square_customers[customer_id] = record
    return {"customer": record}


def _order_total(order: dict[str, Any]) -> int:
    total = 0
    for line in order.get("line_items") or []:
        quantity = Decimal(str(line.get("quantity") or "0"))
        amount = int((line.get("base_price_money") or {}).get("amount") or 0)
        total += int(quantity * amount)
    for discount in order.get("discounts") or []:
        total -= int((discount.get("amount_money") or {}).get("amount") or 0)
    return max(0, total)


@app.post("/square/v2/orders")
def square_order_create(payload: dict[str, Any]) -> dict[str, Any]:
    order_payload = dict(payload.get("order") or {})
    order_id = state.next_id("sorder")
    total = _order_total(order_payload)
    order = {
        "id": order_id,
        "state": "OPEN",
        "version": 1,
        "total_money": {"amount": total, "currency": (order_payload.get("line_items") or [{}])[0].get("base_price_money", {}).get("currency", "USD")},
        **order_payload,
    }
    state.square_orders[order_id] = order
    return {"order": order}


def _refresh_square_invoice(invoice: dict[str, Any]) -> None:
    order = state.square_orders.get(str(invoice.get("order_id"))) or {}
    order_total = int((order.get("total_money") or {}).get("amount") or 0)
    requests = invoice.setdefault("payment_requests", [])
    fixed = sum(
        int((item.get("fixed_amount_requested_money") or {}).get("amount") or 0)
        for item in requests
        if item.get("request_type") != "BALANCE"
    )
    for item in requests:
        if item.get("request_type") == "BALANCE":
            computed = max(0, order_total - fixed)
        else:
            computed = int((item.get("fixed_amount_requested_money") or {}).get("amount") or 0)
        item.setdefault("computed_amount_money", {"amount": computed, "currency": order.get("total_money", {}).get("currency", "USD")})
        item.setdefault("total_completed_amount_money", {"amount": 0, "currency": order.get("total_money", {}).get("currency", "USD")})
    remaining = sum(
        max(0, int(item["computed_amount_money"]["amount"]) - int(item["total_completed_amount_money"]["amount"]))
        for item in requests
    )
    invoice["next_payment_amount_money"] = {"amount": remaining, "currency": order.get("total_money", {}).get("currency", "USD")}
    if remaining <= 0:
        invoice["status"] = "PAID"
        order["state"] = "COMPLETED"
    elif any(int(item["total_completed_amount_money"]["amount"]) > 0 for item in requests):
        invoice["status"] = "PARTIALLY_PAID"
    elif invoice.get("status") != "DRAFT":
        invoice["status"] = "UNPAID"


@app.post("/square/v2/invoices")
def square_invoice_create(payload: dict[str, Any]) -> dict[str, Any]:
    idem = str(payload.get("idempotency_key") or "")
    if idem and idem in state.square_idempotency:
        return {"invoice": state.square_invoices[state.square_idempotency[idem]]}
    invoice_id = state.next_id("sinvoice")
    invoice = {"id": invoice_id, "version": 0, "status": "DRAFT", **dict(payload.get("invoice") or {})}
    _refresh_square_invoice(invoice)
    state.square_invoices[invoice_id] = invoice
    if idem:
        state.square_idempotency[idem] = invoice_id
    return {"invoice": invoice}


@app.post("/square/v2/invoices/{invoice_id}/publish")
def square_invoice_publish(invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    invoice = state.square_invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(404, "invoice not found")
    invoice["version"] = int(invoice.get("version", 0)) + 1
    invoice["status"] = "UNPAID"
    invoice["public_url"] = f"{LAB_PUBLIC_URL}/pay/{invoice_id}"
    invoice["created_at"] = datetime.now(UTC).isoformat()
    invoice["updated_at"] = invoice["created_at"]
    _refresh_square_invoice(invoice)
    return {"invoice": invoice}


@app.get("/square/v2/invoices/{invoice_id}")
def square_invoice_get(invoice_id: str) -> dict[str, Any]:
    invoice = state.square_invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(404, "invoice not found")
    _refresh_square_invoice(invoice)
    return {"invoice": invoice}


def _square_signature(body: bytes) -> str:
    value = f"{PUBLIC_BASE_URL}/webhooks/square".encode() + body
    digest = hmac.new(SQUARE_WEBHOOK_SIGNATURE_KEY.encode(), value, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


async def _post_square_event(invoice_id: str, event_type: str = "invoice.payment_made") -> None:
    payload = {
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "created_at": datetime.now(UTC).isoformat(),
        "data": {"object": {"invoice": {"id": invoice_id}}},
    }
    body = _json_bytes(payload)
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            f"{ORCHESTRATOR_URL}/webhooks/square",
            content=body,
            headers={"x-square-hmacsha256-signature": _square_signature(body), "content-type": "application/json"},
        )


@app.get("/pay/{invoice_id}", response_class=HTMLResponse)
def square_payment_page(invoice_id: str) -> HTMLResponse:
    invoice = state.square_invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(404, "invoice not found")
    _refresh_square_invoice(invoice)
    remaining = int((invoice.get("next_payment_amount_money") or {}).get("amount") or 0)
    return HTMLResponse(
        f"<!doctype html><html><body><h1>Square Local Sandbox</h1>"
        f"<p>Invoice <b>{html.escape(str(invoice.get('invoice_number') or invoice_id))}</b></p>"
        f"<p>Remaining: <b>${remaining/100:,.2f}</b></p>"
        f"<form method='post' action='/lab/invoices/{invoice_id}/pay'><button>Pay remaining balance</button></form>"
        f"<p><a href='/app'>Return to Floodman Office</a></p></body></html>"
    )


@app.post("/lab/invoices/{invoice_id}/pay")
async def lab_pay_invoice(invoice_id: str, amount_cents: int | None = Form(default=None)) -> RedirectResponse:
    invoice = state.square_invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(404, "invoice not found")
    _refresh_square_invoice(invoice)
    remaining = int((invoice.get("next_payment_amount_money") or {}).get("amount") or 0)
    amount = remaining if amount_cents is None else max(0, min(int(amount_cents), remaining))
    pending = amount
    for request in invoice.get("payment_requests") or []:
        computed = int((request.get("computed_amount_money") or {}).get("amount") or 0)
        completed = int((request.get("total_completed_amount_money") or {}).get("amount") or 0)
        available = max(0, computed - completed)
        applied = min(available, pending)
        request["total_completed_amount_money"]["amount"] = completed + applied
        pending -= applied
        if pending <= 0:
            break
    invoice["version"] = int(invoice.get("version", 0)) + 1
    invoice["updated_at"] = datetime.now(UTC).isoformat()
    _refresh_square_invoice(invoice)
    state.last_action = f"Paid ${amount/100:,.2f} on {invoice_id}"
    await _post_square_event(invoice_id)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Documenso-compatible mock
# ---------------------------------------------------------------------------
@app.post("/documenso/envelope/create")
async def documenso_create(payload: str = Form(...), files: UploadFile = File(...)) -> dict[str, Any]:
    spec = json.loads(payload)
    envelope_id = state.next_id("envelope")
    item_id = state.next_id("item")
    raw_pdf = await files.read()
    recipient = (spec.get("recipients") or [{}])[0]
    envelope = {
        "id": envelope_id,
        "externalId": spec.get("externalId"),
        "title": spec.get("title"),
        "status": "DRAFT",
        "recipients": [{**recipient, "signingUrl": f"{LAB_PUBLIC_URL}/sign/{envelope_id}"}],
        "items": [{"id": item_id, "name": files.filename or "document.pdf"}],
        "createdAt": datetime.now(UTC).isoformat(),
    }
    state.envelopes[envelope_id] = envelope
    state.items[item_id] = {"id": item_id, "envelope_id": envelope_id, "pdf": raw_pdf}
    return {"id": envelope_id, "envelope": envelope}


@app.post("/documenso/envelope/{envelope_id}/distribute")
def documenso_distribute(envelope_id: str) -> dict[str, Any]:
    envelope = state.envelopes.get(envelope_id)
    if not envelope:
        raise HTTPException(404, "envelope not found")
    envelope["status"] = "PENDING"
    return envelope


@app.get("/documenso/envelope/{envelope_id}")
def documenso_get(envelope_id: str) -> dict[str, Any]:
    envelope = state.envelopes.get(envelope_id)
    if not envelope:
        raise HTTPException(404, "envelope not found")
    return envelope


@app.get("/documenso/envelope/item/{item_id}/download")
def documenso_download(item_id: str) -> Response:
    item = state.items.get(item_id)
    if not item:
        raise HTTPException(404, "item not found")
    pdf = bytes(item["pdf"])
    if not pdf.startswith(b"%PDF-"):
        pdf = make_pdf("Signed local document", "Completed in the Floodman local test lab.")
    return Response(pdf + b"\n% Locally completed by Floodman Windows Lab\n", media_type="application/pdf")


@app.get("/sign/{envelope_id}", response_class=HTMLResponse)
def documenso_sign_page(envelope_id: str) -> HTMLResponse:
    envelope = state.envelopes.get(envelope_id)
    if not envelope:
        raise HTTPException(404, "envelope not found")
    return HTMLResponse(
        f"<!doctype html><html><body><h1>Documenso Local Sandbox</h1>"
        f"<p>{html.escape(str(envelope.get('title') or envelope_id))}</p>"
        f"<form method='post' action='/lab/envelopes/{envelope_id}/complete'><button>Complete signature</button></form>"
        f"<p><a href='/app'>Return to Floodman Office</a></p></body></html>"
    )


@app.post("/lab/envelopes/{envelope_id}/complete")
async def lab_complete_envelope(envelope_id: str) -> RedirectResponse:
    envelope = state.envelopes.get(envelope_id)
    if not envelope:
        raise HTTPException(404, "envelope not found")
    envelope["status"] = "COMPLETED"
    envelope["completedAt"] = datetime.now(UTC).isoformat()
    payload = {
        "event_id": str(uuid.uuid4()),
        "event": "envelope.completed",
        "envelope": {"id": envelope_id},
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{ORCHESTRATOR_URL}/webhooks/documenso",
            json=payload,
            headers={"x-documenso-secret": DOCUMENSO_WEBHOOK_SECRET},
        )
    if response.is_error:
        raise HTTPException(502, f"Documenso callback failed: {response.text[:500]}")
    state.last_action = f"Completed envelope {envelope_id}"
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Twilio-compatible mock and inbound simulator
# ---------------------------------------------------------------------------
def _twilio_signature(url: str, params: dict[str, Any]) -> str:
    return twilio_signature(TWILIO_AUTH_TOKEN, url, params)


@app.get("/twilio/2010-04-01/Accounts/{account}.json")
def twilio_account(account: str) -> dict[str, Any]:
    return {"sid": account, "status": "active", "friendly_name": "Floodman Engineering Sandbox"}


async def _post_twilio_status(params: dict[str, Any]) -> None:
    url = f"{PUBLIC_BASE_URL}/webhooks/twilio/status"
    await asyncio.sleep(0.2)
    async with httpx.AsyncClient(timeout=15.0) as client:
        await client.post(
            f"{ORCHESTRATOR_URL}/webhooks/twilio/status",
            data=params,
            headers={"x-twilio-signature": _twilio_signature(url, params)},
        )


@app.post("/twilio/2010-04-01/Accounts/{account}/Messages.json")
async def twilio_send(account: str, request: Request) -> dict[str, Any]:
    raw = await request.body()
    parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
    params = {key: values[0] if values else "" for key, values in parsed.items()}
    sid = state.next_id("SMLOCAL")
    message = {
        "sid": sid,
        "account_sid": account,
        "to": params.get("To"),
        "from": params.get("From") or TWILIO_FROM_NUMBER,
        "body": params.get("Body"),
        "status": "queued",
        "created_at": datetime.now(UTC).isoformat(),
    }
    state.sms_messages.insert(0, message)
    state.sms_messages[:] = state.sms_messages[:100]
    asyncio.create_task(
        _post_twilio_status({"MessageSid": sid, "MessageStatus": "delivered", "To": message["to"] or "", "From": message["from"] or ""})
    )
    return message


@app.post("/lab/sms/inbound")
async def lab_inbound_sms(body: str = Form(...), from_phone: str = Form(default="+13135550199")) -> RedirectResponse:
    params = {
        "MessageSid": state.next_id("SMINBOUND"),
        "From": from_phone,
        "To": TWILIO_FROM_NUMBER,
        "Body": body,
        "NumMedia": "0",
    }
    url = f"{PUBLIC_BASE_URL}/webhooks/twilio/inbound"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{ORCHESTRATOR_URL}/webhooks/twilio/inbound",
            data=params,
            headers={"x-twilio-signature": _twilio_signature(url, params)},
        )
    state.last_action = f"Inbound SMS: {body} ({response.status_code})"
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Controlled test workflow controls
# ---------------------------------------------------------------------------
def _demo_payload() -> dict[str, Any]:
    today = date.today()
    return {
        "idempotency_key": f"windows-lab-demo-{today.isoformat()}-r1",
        "organization_id": "floodman-local",
        "roomflow_job_id": "windows-lab-job-001",
        "roomflow_estimate_id": "windows-lab-estimate-001",
        "revision": 1,
        "invoice_number": 260001,
        "currency": "USD",
        "customer": {
            "first_name": "Jane",
            "last_name": "LocalTest",
            "email": "jane.local@example.com",
            "phone": "+13135550199",
            "timezone": "America/Detroit",
            "sms_consent": "OPTED_IN",
            "sms_consent_captured_at": datetime.now(UTC).isoformat(),
            "sms_consent_source": "WINDOWS_LOCAL_LAB",
            "sms_consent_disclosure_version": "local-test-only-v1",
            "sms_consent_disclosure_text": "Local test consent only. No production customer communication.",
            "sms_consent_evidence_id": "windows-lab-consent-001",
        },
        "property": {
            "service_address": {
                "street": "100 Local Test Street",
                "city": "Detroit",
                "state": "MI",
                "postal_code": "48201",
                "country": "US",
            },
            "property_type": "Residential basement",
        },
        "lines": [
            {
                "line_id": "line-1",
                "name": "Local test service",
                "description": "End-to-end Windows lab workflow",
                "quantity": "1",
                "unit_price_cents": 100000,
                "line_total_cents": 100000,
                "taxable": False,
            }
        ],
        "tax_cents": 0,
        "discount_cents": 0,
        "total_cents": 100000,
        "terms": "Local test only. Replace with attorney-approved production terms.",
        "internal_note": "Created by Floodman Engineering Sandbox",
        "authorization": {
            "pdf_url": f"{LAB_INTERNAL_URL}/files/work-authorization.pdf",
            "title": "Floodman Local Work Authorization",
            "fields": [
                {"field_type": "SIGNATURE", "page": 1, "position_x": 10, "position_y": 75, "width": 40, "height": 10, "required": True}
            ],
        },
        "payment_schedule": {
            "deposit_percent": "30",
            "deposit_due_date": today.isoformat(),
            "balance_due_date": today.isoformat(),
        },
    }


@app.post("/lab/demo/create")
async def create_demo_job() -> RedirectResponse:
    try:
        result = await call_orchestrator("POST", "/internal/v1/jobs/sync-estimate", _demo_payload())
        state.demo_job_id = str(result["job_id"])
        state.demo_portal_url = str(result.get("portal_url") or "") or None
        state.last_action = f"Created test job {state.demo_job_id}"
    except Exception as exc:
        state.last_action = f"Create failed: {exc}"
    return RedirectResponse("/", status_code=303)


@app.post("/lab/demo/start")
async def start_demo_job() -> RedirectResponse:
    if not state.demo_job_id:
        state.last_action = "Create the test job first"
        return RedirectResponse("/", status_code=303)

    try:
        # Square accepts the mock webhook immediately, while the outbox worker updates the
        # workflow a moment later. Retry the idempotent Start request while the API reports
        # an expected 409 payment-reconciliation conflict. The API can also repair a lagging
        # DEPOSIT_PUBLISHED state once the payment ledger is authoritative.
        deadline = time.monotonic() + 20.0
        observed_state = "UNKNOWN"
        last_conflict = ""
        while True:
            current = await call_orchestrator("GET", f"/internal/v1/jobs/{state.demo_job_id}")
            observed_state = str(current.get("state") or "UNKNOWN")
            disposition = classify_start_state(observed_state)
            if disposition == "BLOCKED":
                raise RuntimeError(
                    f"Job cannot start while its state is {observed_state}. "
                    "Complete the Work Authorization and pay the deposit first."
                )

            try:
                result = await call_orchestrator(
                    "POST",
                    f"/internal/v1/jobs/{state.demo_job_id}/start",
                    {"idempotency_key": f"windows-lab-start-{state.demo_job_id}"},
                )
                state.last_action = f"Start work: {result}"
                break
            except RuntimeError as exc:
                last_conflict = str(exc)
                if "failed: 409 " not in last_conflict:
                    raise

            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Deposit reconciliation is still pending while the job is {observed_state}. "
                    f"Last API response: {last_conflict}"
                )
            await asyncio.sleep(0.5)
    except Exception as exc:
        state.last_action = f"Start failed: {exc}"
    return RedirectResponse("/", status_code=303)


@app.post("/lab/demo/completion")
async def complete_demo_job() -> RedirectResponse:
    if not state.demo_job_id:
        state.last_action = "Create the test job first"
    else:
        payload = {
            "idempotency_key": f"windows-lab-completion-{state.demo_job_id}",
            "revision": 1,
            "document": {
                "pdf_url": f"{LAB_INTERNAL_URL}/files/completion-of-service.pdf",
                "title": "Floodman Local Completion of Service",
                "fields": [
                    {"field_type": "SIGNATURE", "page": 1, "position_x": 10, "position_y": 75, "width": 40, "height": 10, "required": True}
                ],
            },
            "completed_on": date.today().isoformat(),
            "notes": "Completed through Floodman Engineering Sandbox",
        }
        try:
            result = await call_orchestrator(
                "POST", f"/internal/v1/jobs/{state.demo_job_id}/completion", payload
            )
            state.last_action = f"Completion sent: {result}"
        except Exception as exc:
            state.last_action = f"Completion failed: {exc}"
    return RedirectResponse("/", status_code=303)




@app.post("/lab/reminders/force")
async def force_past_due_reminder(age_days: int = Form(default=2)) -> RedirectResponse:
    """Move open local A/R cases into the past and queue the next reminder immediately."""
    age_days = max(0, min(int(age_days), 365))
    try:
        result = await call_orchestrator(
            "POST",
            "/internal/v1/lab/force-reminders",
            {"age_days": age_days},
        )
        state.last_action = (
            f"Queued {int(result.get('count') or 0)} past-due reminder(s) as if sent {age_days} day(s) ago. "
            "The scheduler normally sends them within 10 seconds."
        )
    except Exception as exc:
        state.last_action = f"Could not force reminder: {exc}"
    return RedirectResponse("/", status_code=303)


@app.post("/lab/reset-mocks")
def reset_mocks() -> RedirectResponse:
    state.reset()
    return RedirectResponse("/", status_code=303)


async def _current_staff_alerts() -> dict[str, Any]:
    try:
        return await call_orchestrator("GET", "/internal/v1/staff-alerts?alert_status=OPEN&limit=25")
    except Exception as exc:
        return {"error": str(exc), "items": []}


async def _current_ar_cases() -> dict[str, Any]:
    try:
        return await call_orchestrator("GET", "/internal/v1/ar/cases?limit=25")
    except Exception as exc:
        return {"error": str(exc), "items": []}


async def _current_job() -> dict[str, Any] | None:
    if not state.demo_job_id:
        return None
    try:
        return await call_orchestrator("GET", f"/internal/v1/jobs/{state.demo_job_id}")
    except Exception as exc:
        return {"error": str(exc), "job_id": state.demo_job_id}


def _pretty(value: Any) -> str:
    return html.escape(json.dumps(value, indent=2, default=str))


@app.post("/api/office/import/direct")
def office_direct_import(payload: dict[str, Any]) -> dict[str, Any]:
    if FLOODMAN_ENV not in {"development", "test", "local"}:
        raise HTTPException(404, "Not found")
    return apply_historical_import(state, payload)


@app.post("/api/office/state/restore")
def office_restore_state(payload: dict[str, Any]) -> dict[str, Any]:
    if FLOODMAN_ENV not in {"development", "test", "local"}:
        raise HTTPException(404, "Not found")
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else payload
    has_state = any((state.contacts, state.gauzy_invoices, state.square_invoices, state.envelopes))
    if has_state and not bool(payload.get("force")):
        raise HTTPException(409, "The local provider already contains state. Use force only during the controlled upgrade script.")
    state.restore_api_snapshot(snapshot)
    return {
        "restored": True,
        "test_job_id": state.demo_job_id,
        "demo_job_id": state.demo_job_id,
        "contacts": len(state.contacts),
        "properties": len(state.properties),
        "invoices": len(state.gauzy_invoices),
        "square_invoices": len(state.square_invoices),
        "documents": len(state.envelopes) + len(state.imported_documents),
        "messages": len(state.sms_messages) + len(state.emails),
    }


@app.get("/api/state")
async def api_state() -> dict[str, Any]:
    return {
        "test_job_id": state.demo_job_id,
        "demo_job_id": state.demo_job_id,
        "job": await _current_job(),
        "ar_cases": await _current_ar_cases(),
        "staff_alerts": await _current_staff_alerts(),
        "envelopes": list(state.envelopes.values()),
        "documenso_items": list(state.items.values()),
        "square_orders": list(state.square_orders.values()),
        "square_invoices": list(state.square_invoices.values()),
        "gauzy_contacts": list(state.contacts.values()),
        "properties": list(state.properties.values()),
        "gauzy_invoices": list(state.gauzy_invoices.values()),
        "gauzy_payments": list(state.gauzy_payments.values()),
        "imported_documents": list(state.imported_documents.values()),
        "notes": list(state.notes.values()),
        "legacy_mappings": state.legacy_mappings,
        "import_runs": state.import_runs,
        "sms_messages": state.sms_messages,
        "emails": state.emails,
        "last_action": state.last_action,
        "setup": state.setup,
        "import_history": state.import_history,
        "imported_records": state.imported_records,
    }


@app.get("/api/mail")
def api_mail() -> dict[str, Any]:
    return {"items": state.emails, "total": len(state.emails)}


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse("/lab", status_code=307)


@app.get("/lab", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    job = await _current_job()
    ar_cases = await _current_ar_cases()
    staff_alerts = await _current_staff_alerts()
    envelopes = "".join(
        f"<tr><td>{html.escape(eid)}</td><td>{html.escape(str(item.get('title') or ''))}</td>"
        f"<td>{html.escape(str(item.get('status')))}</td><td>"
        + (f"<form method='post' action='/lab/envelopes/{eid}/complete'><button>Complete signature</button></form>" if item.get("status") != "COMPLETED" else "Completed")
        + "</td></tr>"
        for eid, item in state.envelopes.items()
    ) or "<tr><td colspan='4'>No documents yet</td></tr>"
    invoices = "".join(
        f"<tr><td>{html.escape(iid)}</td><td>{html.escape(str(item.get('invoice_number') or ''))}</td>"
        f"<td>{html.escape(str(item.get('status')))}</td>"
        f"<td>${int((item.get('next_payment_amount_money') or {}).get('amount') or 0)/100:,.2f}</td>"
        f"<td><form method='post' action='/lab/invoices/{iid}/pay'><button>Pay remaining</button></form></td></tr>"
        for iid, item in state.square_invoices.items()
    ) or "<tr><td colspan='5'>No Square invoices yet</td></tr>"
    mails = "".join(
        f"<details><summary>{html.escape(m.get('subject','(no subject)'))} → {html.escape(', '.join(m.get('to') or []))}</summary>"
        f"<pre>{html.escape(m.get('text') or m.get('html') or '')}</pre></details>"
        for m in state.emails[:20]
    ) or "<p>No email yet.</p>"
    sms = "".join(
        f"<details><summary>{html.escape(str(m.get('status')))} → {html.escape(str(m.get('to')))}</summary>"
        f"<pre>{html.escape(str(m.get('body') or ''))}</pre></details>"
        for m in state.sms_messages[:20]
    ) or "<p>No SMS yet.</p>"
    return HTMLResponse(f"""
<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
<title>Floodman Workflow Test Harness</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#0b1220;color:#e8eef8}}main{{max-width:1180px;margin:auto;padding:24px}}
.card{{background:#141f33;border:1px solid #293a57;border-radius:14px;padding:18px;margin:14px 0;box-shadow:0 8px 30px #0005}}
button{{background:#21a0ff;color:#04111f;border:0;border-radius:8px;padding:10px 14px;font-weight:700;cursor:pointer}}button:hover{{filter:brightness(1.1)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}}table{{width:100%;border-collapse:collapse}}td,th{{border-bottom:1px solid #293a57;padding:9px;text-align:left}}pre{{white-space:pre-wrap;word-break:break-word;background:#09101c;padding:12px;border-radius:8px;max-height:380px;overflow:auto}}a{{color:#68c4ff}}input{{padding:9px;border-radius:8px;border:1px solid #50617c;min-width:280px}}.status{{background:#072e22;border-color:#176b52}}
</style></head><body><main>
<h1>Floodman Workflow Test Harness 🧪</h1><p><a href="{html.escape(os.getenv('OFFICE_CONSOLE_PUBLIC_URL', PUBLIC_BASE_URL).rstrip('/'))}/office">Open Floodman Office</a> · <a href="{html.escape(os.getenv('OFFICE_CONSOLE_PUBLIC_URL', PUBLIC_BASE_URL))}/setup">Guided setup</a></p>
<div class='card status'><b>Last action:</b> {html.escape(state.last_action)}<br><b>Orchestrator:</b> <a href='{html.escape(PUBLIC_BASE_URL)}/health/ready'>{html.escape(PUBLIC_BASE_URL)}/health/ready</a></div>
<div class='card'><h2>Controlled test workflow</h2><div class='grid'>
<form method='post' action='/lab/demo/create'><button>1. Create test estimate</button></form>
<form method='post' action='/lab/demo/start'><button>3. Start work</button></form>
<form method='post' action='/lab/demo/completion'><button>4. Mark job complete</button></form>
<form method='get' action='/lab'><button>Refresh</button></form>
</div><p>After step 1, complete the Work Authorization below, pay the deposit, then start work. The Start action now waits for the asynchronous payment ledger instead of racing the worker. After step 4, complete the Completion of Service. Leave the final invoice unpaid to test A/R reminders.</p></div>
<div class='card'><h2>Past-due reminder test</h2><form method='post' action='/lab/reminders/force'><label>Simulated age in days <input type='number' name='age_days' value='2' min='0' max='365' style='min-width:90px'></label> <button>Queue reminder now</button></form><p>This changes only local test data. The scheduler normally sends the email and consented SMS within 10 seconds.</p><pre>{_pretty(ar_cases)}</pre></div>
<div class='card'><h2>Current job</h2><pre>{_pretty(job or {'status':'No test job created'})}</pre></div>
<div class='card'><h2>Signing documents</h2><table><tr><th>ID</th><th>Title</th><th>Status</th><th>Action</th></tr>{envelopes}</table></div>
<div class='card'><h2>Square invoices</h2><table><tr><th>ID</th><th>Number</th><th>Status</th><th>Remaining</th><th>Action</th></tr>{invoices}</table></div>
<div class='card'><h2>Simulate customer text</h2><form method='post' action='/lab/sms/inbound'><input name='body' value='What is my balance?' required><button>Send inbound SMS</button></form></div>
<div class='card'><h2>Open staff alerts</h2><pre>{_pretty(staff_alerts)}</pre></div>
<div class='card'><h2>Outbound SMS</h2>{sms}</div>
<div class='card'><h2>Captured email</h2>{mails}</div>
<div class='card'><h2>Raw state</h2><p><a href='/api/state'>JSON state</a> · <a href='/docs'>Sandbox provider API docs</a></p></div>
<div class='card'><form method='post' action='/lab/reset-mocks'><button>Reset sandbox providers only</button></form><p>For a complete database reset, use <code>.\\windows\\Reset-FloodmanLab.ps1</code>.</p></div>
</main></body></html>
""")
