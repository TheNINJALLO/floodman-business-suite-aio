from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from .pdf_documents import build_estimate_pdf, build_invoice_pdf, calculate_deposit
from .project_plans import merge_project_plan, project_plan, project_plan_options
from .roomflow_assets import enrich_estimate_with_roomflow


def _now() -> datetime:
    return datetime.now(UTC)


def _now_iso() -> str:
    return _now().isoformat()


def _text(value: Any, limit: int = 12_000) -> str:
    return str(value or "").strip()[:limit]


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_public(record: dict[str, Any]) -> dict[str, Any]:
    blocked = {"provider_response", "password_hash", "source_id", "card_token", "access_token"}
    return {k: v for k, v in record.items() if k not in blocked}


class LineInput(BaseModel):
    id: str | None = None
    section_id: str | None = None
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


class SectionInput(BaseModel):
    id: str | None = None
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=4_000)
    lines: list[LineInput] = Field(default_factory=list, max_length=500)


class EstimateUpdateRequest(BaseModel):
    estimate_number: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=240)
    project_category: str | None = Field(default=None, max_length=160)
    project_summary: str | None = Field(default=None, max_length=12_000)
    recommended_project_title: str | None = Field(default=None, max_length=300)
    estimated_duration: str | None = Field(default=None, max_length=160)
    project_outcomes: list[dict[str, Any]] | None = None
    assumptions: str | None = Field(default=None, max_length=12_000)
    exclusions: str | None = Field(default=None, max_length=12_000)
    protections: list[str] | None = None
    optional_upgrades: list[str] | None = None
    customer_notes: str | None = Field(default=None, max_length=12_000)
    terms: str | None = Field(default=None, max_length=12_000)
    expiration_days: int | None = None
    deposit_type: str | None = None
    deposit_percent: float | None = None
    deposit_fixed_cents: int | None = None
    deposit_due_stage: str | None = None
    sections: list[SectionInput] | None = None


class DocumentActionRequest(BaseModel):
    action: str = Field(min_length=1, max_length=80)
    message: str = Field(default="", max_length=5_000)
    force: bool = False


class InvoiceCreateRequest(BaseModel):
    contact_id: str
    property_id: str
    estimate_id: str | None = None
    invoice_number: str = Field(default="", max_length=120)
    title: str = Field(min_length=1, max_length=240)
    terms: str = Field(default="Payment is due upon receipt.", max_length=12_000)
    customer_notes: str = Field(default="", max_length=12_000)
    sections: list[SectionInput] = Field(default_factory=list, min_length=1, max_length=80)
    allow_partial_payments: bool = True
    allow_customer_to_save_card: bool = True


class InvoiceUpdateRequest(BaseModel):
    invoice_number: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=240)
    terms: str | None = Field(default=None, max_length=12_000)
    customer_notes: str | None = Field(default=None, max_length=12_000)
    sections: list[SectionInput] | None = None
    allow_partial_payments: bool | None = None
    allow_customer_to_save_card: bool | None = None


class AppointmentRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    appointment_type: str = Field(default="JOB", max_length=80)
    status: str = Field(default="SCHEDULED", max_length=80)
    start_at: str
    end_at: str
    contact_id: str | None = None
    property_id: str | None = None
    estimate_id: str | None = None
    invoice_id: str | None = None
    roomflow_job_id: str | None = None
    assigned_user_ids: list[str] = Field(default_factory=list, max_length=100)
    lead_user_id: str | None = None
    internal_notes: str = Field(default="", max_length=10_000)
    customer_notes: str = Field(default="", max_length=10_000)
    location: str = Field(default="", max_length=500)
    override_conflicts: bool = False


class TaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    description: str = Field(default="", max_length=10_000)
    status: str = Field(default="OPEN", max_length=80)
    priority: str = Field(default="NORMAL", max_length=80)
    due_at: str | None = None
    assigned_user_id: str | None = None
    appointment_id: str | None = None
    contact_id: str | None = None
    property_id: str | None = None


class AnnouncementRequest(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    body: str = Field(min_length=1, max_length=20_000)
    severity: str = Field(default="INFO", max_length=80)
    expires_at: str | None = None


class PushTokenRequest(BaseModel):
    provider: str = Field(default="FCM", max_length=40)
    token: str = Field(min_length=20, max_length=2_000)
    app_version: str = Field(default="", max_length=80)


def build_operations_router(
    store: Any,
    providers: Any,
    settings: Any,
    *,
    require_mobile_user: Callable[..., dict[str, Any]],
    permission: Callable[[str], Any],
    audit: Callable[..., None],
) -> APIRouter:
    router = APIRouter()
    tz = ZoneInfo(settings.ar_timezone or "America/Detroit")

    def contact(record: dict[str, Any]) -> dict[str, Any]:
        return _safe_public(record or {})

    def property_record(record: dict[str, Any]) -> dict[str, Any]:
        return _safe_public(record or {})

    def document(record: dict[str, Any]) -> dict[str, Any]:
        return _safe_public(record or {})

    def ensure_document(kind: str, record_id: str) -> dict[str, Any]:
        plural = kind + "s"
        record = store.record(plural, record_id)
        if not record:
            raise HTTPException(404, f"{kind.title()} not found")
        return record

    def ensure_public(kind: str, record: dict[str, Any], actor_id: str) -> dict[str, Any]:
        token = _text(record.get("public_token"), 500) or secrets.token_urlsafe(32)
        public_url = f"{settings.customer_public_url}/{kind}/{token}"
        values = {
            "public_token": token,
            "public_url": public_url,
            "public_pay_url": f"{settings.customer_public_url}/pay/{token}",
            "public_pdf_url": f"{settings.customer_public_url}/{kind}/{token}/pdf",
            "public_enabled": True,
            "public_created_at": record.get("public_created_at") or _now_iso(),
        }
        return store.update_record(kind + "s", str(record["id"]), values, actor_id=actor_id)

    def payment_values(estimate: dict[str, Any]) -> dict[str, Any]:
        amount, label = calculate_deposit(estimate)
        paid = _int(estimate.get("deposit_paid_cents"))
        due = max(0, amount - paid)
        stage = str(estimate.get("deposit_due_stage") or "AFTER_AUTHORIZATION").upper()
        payable = bool(estimate.get("deposit_payable")) or stage == "IMMEDIATELY" or str(estimate.get("status") or "").upper() in {"ACCEPTED", "APPROVED", "DEPOSIT_DUE", "DEPOSIT_PAID"}
        return {"deposit_cents": amount, "deposit_label": label, "paid_cents": paid, "due_cents": due, "payable": payable and amount > 0}

    def pdf_bytes(kind: str, record: dict[str, Any]) -> bytes:
        customer_record = store.record("contacts", str(record.get("contact_id") or "")) or {}
        prop = store.record("properties", str(record.get("property_id") or "")) or {}
        if kind == "estimate":
            enriched = merge_project_plan(enrich_estimate_with_roomflow(store, record))
            payments = [p for p in store.records("payments") if str(p.get("estimate_id") or "") == str(record.get("id") or "")]
            return build_estimate_pdf(enriched, customer_record, prop, store.profile(), public_url=str(record.get("public_url") or ""), payments=payments)
        payments = [p for p in store.records("payments") if str(p.get("invoice_id") or "") == str(record.get("id") or "")]
        docs = [d for d in store.records("documents") if str(d.get("invoice_id") or d.get("floodman_invoice_id") or "") == str(record.get("id") or "")]
        return build_invoice_pdf(record, customer_record, prop, store.profile(), payments=payments, documents=docs, public_url=str(record.get("public_url") or ""))

    def grouped_payload(sections: list[SectionInput], actor_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
        section_records: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        total = 0
        for s_index, section in enumerate(sections):
            sid = _text(section.id, 100) or str(uuid.uuid4())
            subtotal = 0
            section_record = {
                "id": sid,
                "title": _text(section.title, 240),
                "description": _text(section.description, 4_000),
                "sort_order": s_index,
            }
            for l_index, line in enumerate(section.lines):
                quantity = max(0.0, _float(line.quantity))
                unit_price = max(0, _int(line.unit_price_cents))
                line_total = int(round(quantity * unit_price))
                catalog_id = _text(line.catalog_item_id, 100) or None
                if line.save_to_catalog and not catalog_id:
                    saved = store.create_record(
                        "catalog_items",
                        {
                            "name": _text(line.name, 300),
                            "description": _text(line.description, 8_000),
                            "category": _text(line.category, 160) or "General Services",
                            "unit": _text(line.unit, 80) or "each",
                            "unit_price_cents": unit_price,
                            "unit_price": unit_price / 100,
                            "taxable": bool(line.taxable),
                            "active": True,
                            "source_provider": "FLOODMAN_MOBILE",
                            "external_key": f"mobile-{uuid.uuid4()}",
                        },
                        actor_id=actor_id,
                    )
                    catalog_id = str(saved["id"])
                item = {
                    "id": _text(line.id, 100) or str(uuid.uuid4()),
                    "section_id": sid,
                    "section_name": section_record["title"],
                    "catalog_item_id": catalog_id,
                    "name": _text(line.name, 300),
                    "description": _text(line.description, 8_000),
                    "category": _text(line.category, 160) or "General Services",
                    "unit": _text(line.unit, 80) or "each",
                    "quantity": quantity,
                    "unit_price_cents": unit_price,
                    "unit_price": unit_price / 100,
                    "line_total_cents": line_total,
                    "taxable": bool(line.taxable),
                    "optional": bool(line.optional),
                    "sort_order": l_index,
                }
                lines.append(item)
                if not line.optional:
                    subtotal += line_total
            section_record["subtotal_cents"] = subtotal
            section_records.append(section_record)
            total += subtotal
        if not lines:
            raise HTTPException(422, "Add at least one estimate or invoice line item")
        return section_records, lines, total

    def estimate_actions(record: dict[str, Any]) -> list[str]:
        status = str(record.get("status") or "DRAFT").upper()
        actions = ["view_pdf", "open_customer_view"]
        if status in {"DRAFT", "SENT", "VIEWED", "READY_FOR_REVIEW"}:
            actions += ["edit", "send", "resend", "send_work_authorization", "mark_accepted"]
        if _int(payment_values(record)["deposit_cents"]) > 0 and not payment_values(record)["payable"]:
            actions.append("activate_deposit")
        if _int(payment_values(record)["due_cents"]) > 0:
            actions += ["take_payment", "open_payment_link"]
        if status in {"ACCEPTED", "APPROVED", "DEPOSIT_DUE", "DEPOSIT_PAID", "SENT", "VIEWED"} and not record.get("converted_invoice_id"):
            actions.append("convert_to_invoice")
        if status in {"DRAFT", "SENT", "VIEWED"} and not record.get("converted_invoice_id"):
            actions.append("delete")
        return list(dict.fromkeys(actions))

    def invoice_actions(record: dict[str, Any]) -> list[str]:
        status = str(record.get("status") or "DRAFT").upper()
        actions = ["view_pdf", "open_customer_view"]
        if status == "DRAFT":
            actions += ["edit", "send", "delete"]
        elif status not in {"PAID", "VOID", "CANCELED"}:
            actions += ["resend", "void"]
        if _int(record.get("balance_cents")) > 0 and status not in {"VOID", "CANCELED"}:
            actions += ["take_payment", "open_payment_link"]
        return actions

    async def send_document(kind: str, record: dict[str, Any], actor_id: str) -> tuple[dict[str, Any], str]:
        record = ensure_public(kind, record, actor_id)
        customer_record = store.record("contacts", str(record.get("contact_id") or "")) or {}
        email = _text(customer_record.get("email") or customer_record.get("primaryEmail"), 320)
        if not email:
            raise HTTPException(422, "The customer file needs an email address before sending")
        number = _text(record.get("estimate_number") if kind == "estimate" else record.get("invoice_number"), 120) or str(record["id"])
        summary = f"Estimate {number} is ready for review." if kind == "estimate" else f"Invoice {number} is due upon receipt."
        label = "Review estimate" if kind == "estimate" else "View invoice and pay"
        url = str(record.get("public_url") or "")
        html = f"<div style='font-family:Arial,sans-serif;max-width:640px;margin:auto'><h1>FLOODMAN</h1><h2>{summary}</h2><p><a href='{url}' style='display:inline-block;padding:12px 18px;background:#12354a;color:white;text-decoration:none;border-radius:8px'>{label}</a></p><p>Floodman, LLC · (231) 935-4921</p></div>"
        await providers.send_email(
            to=email,
            subject=f"Floodman {number}",
            text=f"{summary}\n\nOpen securely: {url}\n\nFloodman, LLC | (231) 935-4921",
            html=html,
            attachments=[(f"{number}.pdf", pdf_bytes(kind, record), "application/pdf")],
        )
        now = _now_iso()
        updates: dict[str, Any] = {"status": "SENT", "sent_at": now, "last_sent_to": email, "delivery_mode": "FLOODMAN_EMAIL"}
        if kind == "invoice":
            updates.update({"issued_at": now, "due_at": now})
        else:
            updates["issued_at"] = record.get("issued_at") or now
            if str(record.get("deposit_due_stage") or "").upper() == "IMMEDIATELY":
                updates["deposit_payable"] = True
        return store.update_record(kind + "s", str(record["id"]), updates, actor_id=actor_id), email

    def next_invoice_number() -> str:
        year = _now().year
        values: list[int] = []
        for record in store.records("invoices"):
            digits = "".join(ch for ch in str(record.get("invoice_number") or "").split("-")[-1] if ch.isdigit())
            if digits:
                values.append(int(digits))
        return f"INV-{year}-{max(values, default=1000)+1:04d}"

    def parse_time(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(422, f"Invalid date/time: {value}") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(UTC)

    def appointment_conflicts(start: datetime, end: datetime, assigned: list[str], ignore_id: str = "") -> list[dict[str, Any]]:
        conflicts: list[dict[str, Any]] = []
        assigned_set = {str(v) for v in assigned if str(v)}
        if not assigned_set:
            return conflicts
        for item in store.records("appointments"):
            if str(item.get("id") or "") == ignore_id or str(item.get("status") or "").upper() in {"CANCELED", "CANCELLED"}:
                continue
            other_assigned = {str(v) for v in item.get("assigned_user_ids") or []}
            if not assigned_set.intersection(other_assigned):
                continue
            try:
                other_start = parse_time(str(item.get("start_at") or ""))
                other_end = parse_time(str(item.get("end_at") or ""))
            except HTTPException:
                continue
            if start < other_end and end > other_start:
                conflicts.append(document(item))
        return conflicts

    def notify(user_ids: list[str], title: str, body: str, *, kind: str = "GENERAL", reference_id: str | None = None) -> None:
        for user_id in {str(v) for v in user_ids if str(v)}:
            store.create_record(
                "notifications",
                {"user_id": user_id, "title": title, "body": body, "kind": kind, "reference_id": reference_id, "status": "UNREAD", "created_at": _now_iso()},
                actor_id="floodman-system",
            )

    # Project-plan catalog -------------------------------------------------
    @router.get("/project-plans")
    def plans(user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        return {"items": project_plan_options()}

    @router.get("/project-plans/{category}")
    def plan(category: str, user: dict[str, Any] = permission("estimates.view")) -> dict[str, Any]:
        return project_plan(category)

    # Estimate lifecycle --------------------------------------------------
    @router.patch("/estimates/{estimate_id}")
    def update_estimate(estimate_id: str, payload: EstimateUpdateRequest, user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        current = ensure_document("estimate", estimate_id)
        status = str(current.get("status") or "DRAFT").upper()
        if status in {"ACCEPTED", "CONVERTED", "VOID", "CANCELED"} and not payload.model_fields_set.issubset({"customer_notes"}):
            raise HTTPException(409, "Accepted or converted estimates require a revision or change order")
        values = payload.model_dump(exclude_unset=True)
        sections = values.pop("sections", None)
        if sections is not None:
            section_records, lines, total = grouped_payload([SectionInput.model_validate(item) for item in sections], str(user["id"]))
            values.update({"sections": section_records, "line_items": lines, "total_cents": total})
        category = values.get("project_category")
        if category:
            merged = merge_project_plan({**current, **values})
            for key in ("project_category", "recommended_project_title", "project_summary", "summary", "estimated_duration", "project_outcomes", "assumptions", "exclusions", "protections", "optional_upgrades"):
                if key not in values and merged.get(key) is not None:
                    values[key] = merged[key]
        if "project_summary" in values:
            values["summary"] = values["project_summary"]
        if "deposit_type" in values:
            values["deposit_type"] = str(values["deposit_type"]).upper()
        if "deposit_due_stage" in values:
            values["deposit_due_stage"] = str(values["deposit_due_stage"]).upper()
        updated = store.update_record("estimates", estimate_id, values, actor_id=str(user["id"]))
        amount, _ = calculate_deposit(updated)
        paid = _int(updated.get("deposit_paid_cents"))
        updated = store.update_record("estimates", estimate_id, {"deposit_cents": amount, "deposit_balance_cents": max(0, amount-paid)}, actor_id=str(user["id"]))
        audit("ESTIMATE_UPDATED", user_id=str(user["id"]), device_id=str(user.get("mobile_device_id") or ""), detail={"estimate_id": estimate_id})
        return document(updated)

    @router.get("/estimates/{estimate_id}/pdf")
    def estimate_pdf(estimate_id: str, user: dict[str, Any] = permission("estimates.view")) -> Response:
        record = ensure_public("estimate", ensure_document("estimate", estimate_id), str(user["id"]))
        number = _text(record.get("estimate_number"), 120) or estimate_id
        return Response(pdf_bytes("estimate", record), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{number}.pdf"', "Cache-Control": "no-store"})

    @router.post("/estimates/{estimate_id}/action")
    async def estimate_action(estimate_id: str, payload: DocumentActionRequest, request: Request, user: dict[str, Any] = permission("estimates.manage")) -> dict[str, Any]:
        record = ensure_document("estimate", estimate_id)
        action = payload.action.strip().lower().replace("-", "_")
        actor_id = str(user["id"])
        if action in {"ensure_public", "view_pdf", "open_customer_view", "open_payment_link"}:
            updated = ensure_public("estimate", record, actor_id)
            result: dict[str, Any] = {"estimate": document(updated)}
        elif action in {"send", "resend"}:
            updated, recipient = await send_document("estimate", record, actor_id)
            result = {"estimate": document(updated), "recipient": recipient}
        elif action in {"mark_accepted", "accept"}:
            updated = store.update_record("estimates", estimate_id, {"status": "ACCEPTED", "accepted_at": _now_iso(), "deposit_payable": True}, actor_id=actor_id)
            result = {"estimate": document(updated)}
        elif action in {"activate_deposit", "activate"}:
            values = payment_values(record)
            if not values["deposit_cents"]:
                raise HTTPException(409, "This estimate does not require a deposit")
            updated = store.update_record("estimates", estimate_id, {"deposit_payable": True, "deposit_status": "DUE" if values["due_cents"] else "PAID"}, actor_id=actor_id)
            result = {"estimate": document(updated)}
        elif action in {"send_work_authorization", "work_authorization"}:
            customer_record = store.record("contacts", str(record.get("contact_id") or "")) or {}
            email = _text(customer_record.get("email"), 320)
            if not email:
                raise HTTPException(422, "Customer email is required for electronic signature")
            record = ensure_public("estimate", record, actor_id)
            number = _text(record.get("estimate_number"), 120) or estimate_id
            envelope = await providers.create_signing_document(
                filename=f"{number}-Work-Authorization.pdf",
                content=pdf_bytes("estimate", record),
                title=f"Floodman Work Authorization · {number}",
                external_id=f"work-authorization:{estimate_id}:{uuid.uuid4()}",
                recipient_name=_text(customer_record.get("name") or f"{customer_record.get('first_name','')} {customer_record.get('last_name','')}", 240) or "Customer",
                recipient_email=email,
            )
            envelope_id = _text(envelope.get("id") or envelope.get("envelope_id") or (envelope.get("envelope") or {}).get("id"), 200)
            sign_url = _text(envelope.get("signing_url") or envelope.get("url") or envelope.get("public_url") or (envelope.get("envelope") or {}).get("signing_url"), 2_000)
            doc = store.create_record("documents", {
                "contact_id": record.get("contact_id"), "property_id": record.get("property_id"), "estimate_id": estimate_id,
                "kind": "WORK_AUTHORIZATION", "title": f"Work Authorization · {number}", "status": "SENT",
                "provider_envelope_id": envelope_id, "signing_url": sign_url, "provider_response": envelope,
                "source": "FLOODMAN_MOBILE", "created_by_name": user.get("name"),
            }, actor_id=actor_id)
            result = {"estimate": document(record), "document": document(doc), "signing_url": sign_url}
        elif action in {"convert_to_invoice", "convert"}:
            existing_id = _text(record.get("converted_invoice_id"), 100)
            if existing_id:
                invoice = ensure_document("invoice", existing_id)
            else:
                deposit_paid = _int(record.get("deposit_paid_cents"))
                total = _int(record.get("total_cents"))
                invoice = store.create_record("invoices", {
                    "invoice_number": next_invoice_number(), "contact_id": record.get("contact_id"), "property_id": record.get("property_id"),
                    "estimate_id": estimate_id, "title": record.get("title") or "Floodman project invoice", "status": "DRAFT", "currency": record.get("currency") or "USD",
                    "sections": record.get("sections") or [], "line_items": record.get("line_items") or [], "total_cents": total,
                    "paid_cents": deposit_paid, "balance_cents": max(0, total-deposit_paid), "terms": "Payment is due upon receipt.",
                    "customer_notes": record.get("customer_notes") or "", "source": "FLOODMAN_MOBILE", "due_at": None,
                }, actor_id=actor_id)
                store.update_record("estimates", estimate_id, {"status": "CONVERTED", "converted_invoice_id": invoice["id"], "converted_at": _now_iso()}, actor_id=actor_id)
            result = {"estimate": document(store.record("estimates", estimate_id) or record), "invoice": document(invoice)}
        elif action == "delete":
            if str(record.get("status") or "DRAFT").upper() not in {"DRAFT", "SENT", "VIEWED"} or record.get("converted_invoice_id"):
                raise HTTPException(409, "Only unconverted draft, sent, or viewed estimates can be deleted")
            store.delete_record("estimates", estimate_id)
            result = {"ok": True, "deleted_id": estimate_id}
        else:
            raise HTTPException(422, f"Unsupported estimate action: {payload.action}")
        audit("ESTIMATE_ACTION", user_id=actor_id, device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"estimate_id": estimate_id, "action": action})
        return result

    # Invoice lifecycle ---------------------------------------------------
    @router.post("/invoices")
    def create_invoice(payload: InvoiceCreateRequest, user: dict[str, Any] = permission("invoices.manage")) -> dict[str, Any]:
        customer_record = store.record("contacts", payload.contact_id)
        prop = store.record("properties", payload.property_id)
        if not customer_record or not prop or str(prop.get("contact_id") or "") != payload.contact_id:
            raise HTTPException(422, "Choose a valid customer and matching service property")
        sections, lines, total = grouped_payload(payload.sections, str(user["id"]))
        paid = 0
        if payload.estimate_id:
            estimate = store.record("estimates", payload.estimate_id)
            if not estimate:
                raise HTTPException(422, "Estimate not found")
            paid = _int(estimate.get("deposit_paid_cents"))
        invoice = store.create_record("invoices", {
            "invoice_number": payload.invoice_number.strip() or next_invoice_number(), "contact_id": payload.contact_id, "property_id": payload.property_id,
            "estimate_id": payload.estimate_id, "title": payload.title.strip(), "status": "DRAFT", "currency": "USD",
            "sections": sections, "line_items": lines, "total_cents": total, "paid_cents": paid, "balance_cents": max(0, total-paid),
            "terms": payload.terms.strip(), "customer_notes": payload.customer_notes.strip(), "allow_partial_payments": payload.allow_partial_payments,
            "allow_customer_to_save_card": payload.allow_customer_to_save_card, "source": "FLOODMAN_MOBILE",
        }, actor_id=str(user["id"]))
        return document(invoice)

    @router.patch("/invoices/{invoice_id}")
    def update_invoice(invoice_id: str, payload: InvoiceUpdateRequest, user: dict[str, Any] = permission("invoices.manage")) -> dict[str, Any]:
        current = ensure_document("invoice", invoice_id)
        if str(current.get("status") or "DRAFT").upper() != "DRAFT":
            raise HTTPException(409, "Only draft invoices can be edited")
        values = payload.model_dump(exclude_unset=True)
        sections = values.pop("sections", None)
        if sections is not None:
            section_records, lines, total = grouped_payload([SectionInput.model_validate(item) for item in sections], str(user["id"]))
            values.update({"sections": section_records, "line_items": lines, "total_cents": total, "balance_cents": max(0, total-_int(current.get("paid_cents")))})
        return document(store.update_record("invoices", invoice_id, values, actor_id=str(user["id"])))

    @router.get("/invoices/{invoice_id}/pdf")
    def invoice_pdf(invoice_id: str, user: dict[str, Any] = permission("invoices.view")) -> Response:
        record = ensure_public("invoice", ensure_document("invoice", invoice_id), str(user["id"]))
        number = _text(record.get("invoice_number"), 120) or invoice_id
        return Response(pdf_bytes("invoice", record), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{number}.pdf"', "Cache-Control": "no-store"})

    @router.post("/invoices/{invoice_id}/action")
    async def invoice_action(invoice_id: str, payload: DocumentActionRequest, request: Request, user: dict[str, Any] = permission("invoices.manage")) -> dict[str, Any]:
        record = ensure_document("invoice", invoice_id)
        action = payload.action.strip().lower().replace("-", "_")
        actor_id = str(user["id"])
        if action in {"ensure_public", "view_pdf", "open_customer_view", "open_payment_link"}:
            updated = ensure_public("invoice", record, actor_id)
            result: dict[str, Any] = {"invoice": document(updated)}
        elif action in {"send", "resend"}:
            updated, recipient = await send_document("invoice", record, actor_id)
            result = {"invoice": document(updated), "recipient": recipient}
        elif action == "void":
            updated = store.update_record("invoices", invoice_id, {"status": "VOID", "voided_at": _now_iso()}, actor_id=actor_id)
            result = {"invoice": document(updated)}
        elif action == "delete":
            if str(record.get("status") or "DRAFT").upper() != "DRAFT" or _int(record.get("paid_cents")) > 0:
                raise HTTPException(409, "Only unpaid draft invoices can be deleted")
            store.delete_record("invoices", invoice_id)
            result = {"ok": True, "deleted_id": invoice_id}
        else:
            raise HTTPException(422, f"Unsupported invoice action: {payload.action}")
        audit("INVOICE_ACTION", user_id=actor_id, device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"invoice_id": invoice_id, "action": action})
        return result

    # Employees and scheduling -------------------------------------------
    @router.get("/employees")
    def employees(q: str = "", user: dict[str, Any] = permission("calendar.view")) -> dict[str, Any]:
        query = q.strip().casefold()
        items = []
        for member in store.list_users():
            if str(member.get("status") or "ACTIVE").upper() != "ACTIVE":
                continue
            haystack = f"{member.get('name','')} {member.get('email','')} {member.get('role','')}".casefold()
            if query and query not in haystack:
                continue
            items.append({k: member.get(k) for k in ("id", "name", "email", "role", "status")})
        return {"items": items}

    @router.get("/calendar")
    def calendar(start: str = "", end: str = "", employee_id: str = "", user: dict[str, Any] = permission("calendar.view")) -> dict[str, Any]:
        start_dt = parse_time(start) if start else _now()-timedelta(days=31)
        end_dt = parse_time(end) if end else _now()+timedelta(days=120)
        items = []
        for record in store.records("appointments"):
            try:
                item_start = parse_time(str(record.get("start_at") or ""))
                item_end = parse_time(str(record.get("end_at") or ""))
            except HTTPException:
                continue
            if item_end < start_dt or item_start > end_dt:
                continue
            assigned = [str(v) for v in record.get("assigned_user_ids") or []]
            if employee_id and employee_id not in assigned:
                continue
            items.append(document(record))
        items.sort(key=lambda item: str(item.get("start_at") or ""))
        return {"items": items, "time_zone": settings.ar_timezone}

    @router.post("/appointments")
    def create_appointment(payload: AppointmentRequest, request: Request, user: dict[str, Any] = permission("calendar.manage")) -> dict[str, Any]:
        start = parse_time(payload.start_at)
        end = parse_time(payload.end_at)
        if end <= start:
            raise HTTPException(422, "Appointment end must be after start")
        assigned = list(dict.fromkeys([*payload.assigned_user_ids, *([payload.lead_user_id] if payload.lead_user_id else [])]))
        conflicts = appointment_conflicts(start, end, assigned)
        if conflicts and not payload.override_conflicts:
            raise HTTPException(409, {"message": "One or more employees are already booked", "conflicts": conflicts})
        record = store.create_record("appointments", {
            **payload.model_dump(exclude={"override_conflicts"}), "assigned_user_ids": assigned,
            "appointment_type": payload.appointment_type.upper(), "status": payload.status.upper(),
            "start_at": start.isoformat(), "end_at": end.isoformat(), "time_zone": settings.ar_timezone,
            "created_by": user.get("id"), "source": "FLOODMAN_MOBILE",
        }, actor_id=str(user["id"]))
        notify(assigned, f"Assigned: {record['title']}", f"{start.astimezone(tz).strftime('%b %d, %Y %I:%M %p')} · {record.get('location') or 'See appointment'}", kind="APPOINTMENT", reference_id=str(record["id"]))
        audit("APPOINTMENT_CREATED", user_id=str(user["id"]), device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"appointment_id": record["id"]})
        return {"appointment": document(record), "conflicts_overridden": bool(conflicts)}

    @router.patch("/appointments/{appointment_id}")
    def update_appointment(appointment_id: str, payload: AppointmentRequest, request: Request, user: dict[str, Any] = permission("calendar.manage")) -> dict[str, Any]:
        current = store.record("appointments", appointment_id)
        if not current:
            raise HTTPException(404, "Appointment not found")
        start = parse_time(payload.start_at)
        end = parse_time(payload.end_at)
        if end <= start:
            raise HTTPException(422, "Appointment end must be after start")
        assigned = list(dict.fromkeys([*payload.assigned_user_ids, *([payload.lead_user_id] if payload.lead_user_id else [])]))
        conflicts = appointment_conflicts(start, end, assigned, appointment_id)
        if conflicts and not payload.override_conflicts:
            raise HTTPException(409, {"message": "One or more employees are already booked", "conflicts": conflicts})
        values = {**payload.model_dump(exclude={"override_conflicts"}), "assigned_user_ids": assigned, "appointment_type": payload.appointment_type.upper(), "status": payload.status.upper(), "start_at": start.isoformat(), "end_at": end.isoformat(), "time_zone": settings.ar_timezone}
        record = store.update_record("appointments", appointment_id, values, actor_id=str(user["id"]))
        notify(assigned, f"Updated: {record['title']}", f"{start.astimezone(tz).strftime('%b %d, %Y %I:%M %p')}", kind="APPOINTMENT", reference_id=appointment_id)
        audit("APPOINTMENT_UPDATED", user_id=str(user["id"]), device_id=str(user.get("mobile_device_id") or ""), request=request, detail={"appointment_id": appointment_id})
        return {"appointment": document(record), "conflicts_overridden": bool(conflicts)}

    @router.delete("/appointments/{appointment_id}")
    def delete_appointment(appointment_id: str, user: dict[str, Any] = permission("calendar.manage")) -> dict[str, Any]:
        if not store.record("appointments", appointment_id):
            raise HTTPException(404, "Appointment not found")
        store.delete_record("appointments", appointment_id)
        return {"ok": True}

    @router.post("/calendar/subscription")
    def create_subscription(user: dict[str, Any] = permission("calendar.view")) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        record = store.create_record("calendar_subscriptions", {"user_id": user["id"], "token": token, "status": "ACTIVE", "created_at": _now_iso()}, actor_id=str(user["id"]))
        return {"subscription": document(record), "url": f"{settings.mobile_api_public_url or settings.customer_public_url.rsplit('/customer',1)[0]}/v1/calendar/feed/{token}.ics"}

    @router.get("/calendar/feed/{token}.ics")
    def calendar_feed(token: str) -> Response:
        subscription = next((item for item in store.records("calendar_subscriptions") if secrets.compare_digest(str(item.get("token") or ""), token) and str(item.get("status") or "ACTIVE").upper() == "ACTIVE"), None)
        if not subscription:
            raise HTTPException(404, "Calendar subscription not found")
        user_id = str(subscription.get("user_id") or "")
        lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Floodman//Operations Calendar//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH"]
        for item in store.records("appointments"):
            if user_id not in [str(v) for v in item.get("assigned_user_ids") or []]:
                continue
            start = parse_time(str(item.get("start_at") or ""))
            end = parse_time(str(item.get("end_at") or ""))
            def esc(value: Any) -> str:
                return str(value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
            lines += ["BEGIN:VEVENT", f"UID:{item.get('id')}@floodman.com", f"DTSTAMP:{_now().strftime('%Y%m%dT%H%M%SZ')}", f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}", f"DTEND:{end.strftime('%Y%m%dT%H%M%SZ')}", f"SUMMARY:{esc(item.get('title'))}", f"LOCATION:{esc(item.get('location'))}", f"DESCRIPTION:{esc(item.get('customer_notes') or item.get('internal_notes'))}", "END:VEVENT"]
        lines.append("END:VCALENDAR")
        return Response("\r\n".join(lines)+"\r\n", media_type="text/calendar; charset=utf-8", headers={"Content-Disposition": "inline; filename=floodman-calendar.ics", "Cache-Control": "no-store"})

    # Tasks, announcements, notifications -------------------------------
    @router.post("/tasks")
    def create_task(payload: TaskRequest, user: dict[str, Any] = permission("tasks.manage")) -> dict[str, Any]:
        record = store.create_record("tasks", {**payload.model_dump(), "status": payload.status.upper(), "priority": payload.priority.upper(), "created_by": user.get("id"), "source": "FLOODMAN_MOBILE"}, actor_id=str(user["id"]))
        if payload.assigned_user_id:
            notify([payload.assigned_user_id], f"Task assigned: {payload.title}", payload.description, kind="TASK", reference_id=str(record["id"]))
        return document(record)

    @router.patch("/tasks/{task_id}")
    def update_task(task_id: str, payload: TaskRequest, user: dict[str, Any] = permission("tasks.manage")) -> dict[str, Any]:
        if not store.record("tasks", task_id):
            raise HTTPException(404, "Task not found")
        return document(store.update_record("tasks", task_id, {**payload.model_dump(), "status": payload.status.upper(), "priority": payload.priority.upper()}, actor_id=str(user["id"])))

    @router.post("/announcements")
    def create_announcement(payload: AnnouncementRequest, user: dict[str, Any] = permission("members.manage")) -> dict[str, Any]:
        record = store.create_record("announcements", {**payload.model_dump(), "severity": payload.severity.upper(), "created_by": user.get("id"), "created_at": _now_iso(), "status": "ACTIVE"}, actor_id=str(user["id"]))
        notify([str(member.get("id")) for member in store.list_users()], payload.title, payload.body, kind="ANNOUNCEMENT", reference_id=str(record["id"]))
        return document(record)

    @router.get("/announcements")
    def announcements(user: dict[str, Any] = permission("dashboard.view")) -> dict[str, Any]:
        now = _now()
        items = []
        for item in store.records("announcements"):
            expires = item.get("expires_at")
            if expires:
                try:
                    if parse_time(str(expires)) < now:
                        continue
                except HTTPException:
                    pass
            items.append(document(item))
        return {"items": items}

    @router.get("/notifications")
    def notifications(unread_only: bool = False, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        items = [document(item) for item in store.records("notifications") if str(item.get("user_id") or "") == str(user.get("id") or "") and (not unread_only or str(item.get("status") or "UNREAD").upper() == "UNREAD")]
        return {"items": items, "unread": len([item for item in items if str(item.get("status") or "UNREAD").upper() == "UNREAD"])}

    @router.post("/notifications/{notification_id}/read")
    def read_notification(notification_id: str, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        item = store.record("notifications", notification_id)
        if not item or str(item.get("user_id") or "") != str(user.get("id") or ""):
            raise HTTPException(404, "Notification not found")
        return document(store.update_record("notifications", notification_id, {"status": "READ", "read_at": _now_iso()}, actor_id=str(user["id"])))

    @router.post("/push-tokens")
    def register_push_token(payload: PushTokenRequest, user: dict[str, Any] = Depends(require_mobile_user)) -> dict[str, Any]:
        existing = next((item for item in store.records("push_tokens") if str(item.get("user_id") or "") == str(user.get("id") or "") and str(item.get("token") or "") == payload.token), None)
        values = {"user_id": user["id"], "device_id": user.get("mobile_device_id"), "provider": payload.provider.upper(), "token": payload.token, "app_version": payload.app_version, "status": "ACTIVE", "updated_at": _now_iso()}
        record = store.update_record("push_tokens", str(existing["id"]), values, actor_id=str(user["id"])) if existing else store.create_record("push_tokens", values, actor_id=str(user["id"]))
        return document(record)

    return router
