from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import quote

from fastapi import HTTPException


CATEGORIES = (
    "contacts",
    "properties",
    "estimates",
    "estimate_lines",
    "invoices",
    "payments",
    "documents",
    "notes",
)


class ImportState(Protocol):
    lock: Any
    contacts: dict[str, dict[str, Any]]
    properties: dict[str, dict[str, Any]]
    gauzy_invoices: dict[str, dict[str, Any]]
    gauzy_payments: dict[str, dict[str, Any]]
    imported_documents: dict[str, dict[str, Any]]
    notes: dict[str, dict[str, Any]]
    legacy_mappings: dict[str, dict[str, str]]
    import_runs: list[dict[str, Any]]
    import_history: list[dict[str, Any]]
    last_action: str

    def next_id(self, prefix: str) -> str: ...
    def save(self) -> None: ...


def _text(value: Any) -> str:
    return str(value or "").strip()


def _required(row: dict[str, Any], field: str, category: str) -> str:
    value = _text(row.get(field))
    if not value:
        raise HTTPException(422, f"{category} record is missing {field}")
    return value


def _integer(value: Any, field: str) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, f"{field} must be an integer") from exc


def _archive_url(base_url: str, run_id: str, path_value: Any) -> str | None:
    raw = _text(path_value).replace("\\", "/")
    if not raw or not base_url or not run_id:
        return None
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts:
        return None
    base = base_url.rstrip("/")
    if not (base.startswith("http://localhost:") or base.startswith("http://127.0.0.1:")):
        return None
    return f"{base}/office/imports/{quote(run_id, safe='')}/files/{quote(path.as_posix(), safe='/')}"


def _mapping(state: ImportState, category: str, legacy_id: Any) -> str | None:
    return state.legacy_mappings.get(category, {}).get(_text(legacy_id))


def _ensure_rows(records: dict[str, Any]) -> None:
    for category in CATEGORIES:
        value = records.get(category, [])
        if value is None:
            records[category] = []
            continue
        if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
            raise HTTPException(422, f"{category} must be a list of objects")


def apply_historical_import(state: ImportState, payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records")
    if not isinstance(records, dict):
        raise HTTPException(422, "Import payload must include a records object")
    _ensure_rows(records)

    run_id = _text(payload.get("run_id")) or str(datetime.now(UTC).timestamp()).replace(".", "-")
    archive_base_url = _text(payload.get("archive_base_url"))
    created = {category: 0 for category in CATEGORIES}
    skipped = {category: 0 for category in CATEGORIES}

    with state.lock:
        for row in records["contacts"]:
            legacy_id = _required(row, "legacy_contact_id", "contact")
            if legacy_id in state.legacy_mappings["contacts"]:
                skipped["contacts"] += 1
                continue
            identifier = state.next_id("gcontact")
            first = _text(row.get("first_name"))
            last = _text(row.get("last_name"))
            state.contacts[identifier] = {
                "id": identifier,
                "name": " ".join(part for part in (first, last) if part) or legacy_id,
                "primaryEmail": _text(row.get("email")) or None,
                "primaryPhone": _text(row.get("phone")) or None,
                "billingAddress": {
                    "street": _text(row.get("billing_street")),
                    "city": _text(row.get("billing_city")),
                    "state": _text(row.get("billing_state")),
                    "postalCode": _text(row.get("billing_postal_code")),
                },
                "notes": f"Historical archive imported from Townsquare contact {legacy_id}.",
                "legacySource": "townsquare",
                "legacyContactId": legacy_id,
                "legacy_source": "townsquare",
                "legacy_contact_id": legacy_id,
                "importRunId": run_id,
                "importMode": "HISTORICAL_ARCHIVE",
                "createdAt": _text(row.get("created_at")) or datetime.now(UTC).isoformat(),
            }
            state.legacy_mappings["contacts"][legacy_id] = identifier
            created["contacts"] += 1

        for row in records["properties"]:
            legacy_id = _required(row, "legacy_property_id", "property")
            if legacy_id in state.legacy_mappings["properties"]:
                skipped["properties"] += 1
                continue
            contact_legacy = _required(row, "legacy_contact_id", "property")
            contact_id = _mapping(state, "contacts", contact_legacy)
            if not contact_id:
                raise HTTPException(422, f"Property {legacy_id} references unknown contact {contact_legacy}")
            identifier = state.next_id("property")
            state.properties[identifier] = {
                "id": identifier,
                "property_name": _text(row.get("property_name")) or legacy_id,
                "contact_id": contact_id,
                "legacy_contact_id": contact_legacy,
                "service_address": {
                    "street": _text(row.get("service_street")),
                    "city": _text(row.get("service_city")),
                    "state": _text(row.get("service_state")),
                    "postal_code": _text(row.get("service_postal_code")),
                },
                "property_type": _text(row.get("property_type")) or None,
                "claim_number": _text(row.get("claim_number")) or None,
                "insurer": _text(row.get("insurer")) or None,
                "legacy_source": "townsquare",
                "legacy_property_id": legacy_id,
                "import_run_id": run_id,
                "import_mode": "HISTORICAL_ARCHIVE",
                "created_at": _text(row.get("created_at")) or datetime.now(UTC).isoformat(),
            }
            state.legacy_mappings["properties"][legacy_id] = identifier
            created["properties"] += 1

        for row in records["estimates"]:
            legacy_id = _required(row, "legacy_estimate_id", "estimate")
            if legacy_id in state.legacy_mappings["estimates"]:
                skipped["estimates"] += 1
                continue
            contact_legacy = _required(row, "legacy_contact_id", "estimate")
            contact_id = _mapping(state, "contacts", contact_legacy)
            if not contact_id:
                raise HTTPException(422, f"Estimate {legacy_id} references unknown contact {contact_legacy}")
            property_legacy = _text(row.get("legacy_property_id"))
            property_id = _mapping(state, "properties", property_legacy) if property_legacy else None
            if property_legacy and not property_id:
                raise HTTPException(422, f"Estimate {legacy_id} references unknown property {property_legacy}")
            identifier = state.next_id("ginvoice")
            cents = _integer(row.get("_total_cents") or row.get("total_cents"), "estimate total_cents")
            contact = state.contacts.get(contact_id, {})
            state.gauzy_invoices[identifier] = {
                "id": identifier,
                "invoiceNumber": _text(row.get("estimate_number")) or legacy_id,
                "invoiceDate": _text(row.get("created_at")) or datetime.now(UTC).isoformat(),
                "dueDate": _text(row.get("accepted_at")) or _text(row.get("created_at")) or datetime.now(UTC).isoformat(),
                "status": _text(row.get("status")).upper() or "DRAFT",
                "totalValue": cents / 100,
                "total_cents": cents,
                "currency": _text(row.get("currency")).upper() or "USD",
                "paid": False,
                "isEstimate": True,
                "isAccepted": _text(row.get("status")).upper() == "ACCEPTED",
                "organizationContactId": contact_id,
                "organizationContactName": contact.get("name"),
                "propertyId": property_id,
                "invoiceItems": [],
                "payments": [],
                "legacySource": "townsquare",
                "legacyEstimateId": legacy_id,
                "legacy_source": "townsquare",
                "legacy_estimate_id": legacy_id,
                "legacy_contact_id": contact_legacy,
                "legacy_property_id": property_legacy or None,
                "revision": _integer(row.get("revision") or 1, "estimate revision"),
                "pdfPath": _text(row.get("pdf_path")) or None,
                "pdf_url": _archive_url(archive_base_url, run_id, row.get("_stored_file_path") or row.get("pdf_path")),
                "importRunId": run_id,
                "importMode": "HISTORICAL_ARCHIVE",
                "automaticRemindersEnabled": False,
                "token": None,
            }
            state.legacy_mappings["estimates"][legacy_id] = identifier
            created["estimates"] += 1

        for row in records["estimate_lines"]:
            legacy_id = _required(row, "legacy_line_id", "estimate line")
            if legacy_id in state.legacy_mappings["estimate_lines"]:
                skipped["estimate_lines"] += 1
                continue
            estimate_legacy = _required(row, "legacy_estimate_id", "estimate line")
            estimate_id = _mapping(state, "estimates", estimate_legacy)
            if not estimate_id or estimate_id not in state.gauzy_invoices:
                raise HTTPException(422, f"Estimate line {legacy_id} references unknown estimate {estimate_legacy}")
            identifier = state.next_id("gitem")
            quantity = float(row.get("_quantity") or row.get("quantity") or 0)
            unit_cents = _integer(row.get("_unit_price_cents") or row.get("unit_price_cents"), "unit_price_cents")
            line_cents = _integer(row.get("_line_total_cents") or row.get("line_total_cents"), "line_total_cents")
            state.gauzy_invoices[estimate_id].setdefault("invoiceItems", []).append(
                {
                    "id": identifier,
                    "invoiceId": estimate_id,
                    "name": _text(row.get("name")) or "Imported item",
                    "description": _text(row.get("description")),
                    "quantity": quantity,
                    "price": unit_cents / 100,
                    "totalValue": line_cents / 100,
                    "applyTax": _text(row.get("taxable")).lower() in {"1", "true", "yes", "y"},
                    "legacyLineId": legacy_id,
                    "legacy_line_id": legacy_id,
                    "importRunId": run_id,
                }
            )
            state.legacy_mappings["estimate_lines"][legacy_id] = identifier
            created["estimate_lines"] += 1

        for row in records["invoices"]:
            legacy_id = _required(row, "legacy_invoice_id", "invoice")
            if legacy_id in state.legacy_mappings["invoices"]:
                skipped["invoices"] += 1
                continue
            contact_legacy = _required(row, "legacy_contact_id", "invoice")
            contact_id = _mapping(state, "contacts", contact_legacy)
            if not contact_id:
                raise HTTPException(422, f"Invoice {legacy_id} references unknown contact {contact_legacy}")
            property_legacy = _text(row.get("legacy_property_id"))
            property_id = _mapping(state, "properties", property_legacy) if property_legacy else None
            estimate_legacy = _text(row.get("legacy_estimate_id"))
            estimate_id = _mapping(state, "estimates", estimate_legacy) if estimate_legacy else None
            identifier = state.next_id("ginvoice")
            cents = _integer(row.get("_total_cents") or row.get("total_cents"), "invoice total_cents")
            contact = state.contacts.get(contact_id, {})
            state.gauzy_invoices[identifier] = {
                "id": identifier,
                "invoiceNumber": _text(row.get("invoice_number")) or legacy_id,
                "invoiceDate": _text(row.get("issued_at")) or datetime.now(UTC).isoformat(),
                "dueDate": _text(row.get("due_at")) or _text(row.get("issued_at")) or datetime.now(UTC).isoformat(),
                "status": _text(row.get("status")).upper() or "SENT",
                "totalValue": cents / 100,
                "total_cents": cents,
                "currency": _text(row.get("currency")).upper() or "USD",
                "paid": False,
                "alreadyPaid": 0,
                "amountDue": cents / 100,
                "isEstimate": False,
                "organizationContactId": contact_id,
                "organizationContactName": contact.get("name"),
                "propertyId": property_id,
                "sourceEstimateId": estimate_id,
                "invoiceItems": [],
                "payments": [],
                "legacySource": "townsquare",
                "legacyInvoiceId": legacy_id,
                "legacy_source": "townsquare",
                "legacy_invoice_id": legacy_id,
                "legacy_estimate_id": estimate_legacy or None,
                "legacy_contact_id": contact_legacy,
                "legacy_property_id": property_legacy or None,
                "pdfPath": _text(row.get("pdf_path")) or None,
                "pdf_url": _archive_url(archive_base_url, run_id, row.get("_stored_file_path") or row.get("pdf_path")),
                "importRunId": run_id,
                "importMode": "HISTORICAL_ARCHIVE",
                "automaticRemindersEnabled": False,
                "token": None,
            }
            state.legacy_mappings["invoices"][legacy_id] = identifier
            created["invoices"] += 1

        for row in records["payments"]:
            legacy_id = _required(row, "legacy_payment_id", "payment")
            if legacy_id in state.legacy_mappings["payments"]:
                skipped["payments"] += 1
                continue
            invoice_legacy = _required(row, "legacy_invoice_id", "payment")
            invoice_id = _mapping(state, "invoices", invoice_legacy)
            if not invoice_id or invoice_id not in state.gauzy_invoices:
                raise HTTPException(422, f"Payment {legacy_id} references unknown invoice {invoice_legacy}")
            identifier = state.next_id("gpayment")
            cents = _integer(row.get("_amount_cents") or row.get("amount_cents"), "payment amount_cents")
            status = _text(row.get("status")).upper() or "COMPLETED"
            record = {
                "id": identifier,
                "invoiceId": invoice_id,
                "amount": cents / 100,
                "amount_cents": cents,
                "currency": _text(row.get("currency")).upper() or "USD",
                "status": status,
                "providerStatus": status,
                "paymentMethod": _text(row.get("payment_method")).upper() or "OTHER",
                "paymentDate": _text(row.get("paid_at")) or datetime.now(UTC).isoformat(),
                "providerReference": _text(row.get("provider_reference")) or None,
                "legacySource": "townsquare",
                "legacyPaymentId": legacy_id,
                "legacy_source": "townsquare",
                "legacy_payment_id": legacy_id,
                "legacy_invoice_id": invoice_legacy,
                "importRunId": run_id,
                "importMode": "HISTORICAL_ARCHIVE",
            }
            state.gauzy_payments[identifier] = record
            invoice = state.gauzy_invoices[invoice_id]
            invoice.setdefault("payments", []).append(record)
            if status not in {"FAILED", "CANCELLED", "VOID", "REFUNDED"}:
                already = int(round(float(invoice.get("alreadyPaid") or 0) * 100)) + cents
                total = int(invoice.get("total_cents") or round(float(invoice.get("totalValue") or 0) * 100))
                due = max(0, total - already)
                invoice["alreadyPaid"] = already / 100
                invoice["amountDue"] = due / 100
                invoice["paid"] = due == 0
                if due == 0:
                    invoice["status"] = "FULLY_PAID"
                elif already > 0:
                    invoice["status"] = "PARTIALLY_PAID"
            state.legacy_mappings["payments"][legacy_id] = identifier
            created["payments"] += 1

        for row in records["documents"]:
            legacy_id = _required(row, "legacy_document_id", "document")
            if legacy_id in state.legacy_mappings["documents"]:
                skipped["documents"] += 1
                continue
            identifier = state.next_id("document")
            state.imported_documents[identifier] = {
                "id": identifier,
                "document_type": _text(row.get("document_type")).upper(),
                "file_path": _text(row.get("_stored_file_path") or row.get("file_path")),
                "file_url": _archive_url(archive_base_url, run_id, row.get("_stored_file_path") or row.get("file_path")),
                "sha256": _text(row.get("_sha256") or row.get("sha256")) or None,
                "signed_at": _text(row.get("signed_at")) or None,
                "contact_id": _mapping(state, "contacts", row.get("legacy_contact_id")),
                "property_id": _mapping(state, "properties", row.get("legacy_property_id")),
                "estimate_id": _mapping(state, "estimates", row.get("legacy_estimate_id")),
                "invoice_id": _mapping(state, "invoices", row.get("legacy_invoice_id")),
                "legacy_source": "townsquare",
                "legacy_document_id": legacy_id,
                "import_run_id": run_id,
                "import_mode": "HISTORICAL_ARCHIVE",
            }
            state.legacy_mappings["documents"][legacy_id] = identifier
            created["documents"] += 1

        for row in records["notes"]:
            legacy_id = _required(row, "legacy_note_id", "note")
            if legacy_id in state.legacy_mappings["notes"]:
                skipped["notes"] += 1
                continue
            entity_type = _text(row.get("entity_type")).upper()
            category = {
                "CONTACT": "contacts",
                "PROPERTY": "properties",
                "ESTIMATE": "estimates",
                "INVOICE": "invoices",
                "PAYMENT": "payments",
                "DOCUMENT": "documents",
            }.get(entity_type)
            entity_legacy = _required(row, "entity_id", "note")
            internal_id = _mapping(state, category, entity_legacy) if category else None
            if not internal_id:
                raise HTTPException(422, f"Note {legacy_id} references unknown {entity_type} {entity_legacy}")
            identifier = state.next_id("note")
            state.notes[identifier] = {
                "id": identifier,
                "entity_type": entity_type,
                "entity_id": internal_id,
                "legacy_entity_id": entity_legacy,
                "note": _text(row.get("note")),
                "created_at": _text(row.get("created_at")) or datetime.now(UTC).isoformat(),
                "legacy_source": "townsquare",
                "legacy_note_id": legacy_id,
                "import_run_id": run_id,
                "import_mode": "HISTORICAL_ARCHIVE",
            }
            state.legacy_mappings["notes"][legacy_id] = identifier
            created["notes"] += 1

        imported_invoices = {
            _mapping(state, "invoices", row.get("legacy_invoice_id")) for row in records["invoices"]
        }
        imported_invoices.discard(None)
        invoice_total = sum(
            int(state.gauzy_invoices[item].get("total_cents") or 0)
            for item in imported_invoices
            if item in state.gauzy_invoices
        )
        imported_payments = {
            _mapping(state, "payments", row.get("legacy_payment_id")) for row in records["payments"]
        }
        imported_payments.discard(None)
        payment_total = sum(
            int(state.gauzy_payments[item].get("amount_cents") or 0)
            for item in imported_payments
            if item in state.gauzy_payments
            and _text(state.gauzy_payments[item].get("status")).upper()
            not in {"FAILED", "CANCELLED", "VOID", "REFUNDED"}
        )
        reconciliation = {
            "invoice_total_cents": invoice_total,
            "payment_total_cents": payment_total,
            "outstanding_cents": max(0, invoice_total - payment_total),
        }
        result = {
            "id": state.next_id("import"),
            "run_id": run_id,
            "status": "APPLIED",
            "created": created,
            "skipped": skipped,
            "reconciliation": reconciliation,
            "mode": "HISTORICAL_ARCHIVE",
            "automatic_reminders_enabled": False,
            "applied_at": datetime.now(UTC).isoformat(),
        }
        state.import_runs.insert(0, result)
        state.import_runs[:] = state.import_runs[:100]
        state.import_history.insert(0, result)
        state.import_history[:] = state.import_history[:100]
        state.last_action = f"Imported historical archive {run_id}"
        state.save()
        return result
