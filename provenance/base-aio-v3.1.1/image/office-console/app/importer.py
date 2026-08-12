from __future__ import annotations

import csv
import hashlib
import io
import re
import zipfile
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any

from email_validator import EmailNotValidError, validate_email


CSV_SPECS: dict[str, dict[str, Any]] = {
    "contacts.csv": {
        "key": "contacts",
        "id": "legacy_contact_id",
        "required_file": True,
        "required": ("legacy_contact_id", "first_name", "last_name", "email", "phone"),
        "headers": (
            "legacy_contact_id", "first_name", "last_name", "email", "phone", "billing_street",
            "billing_city", "billing_state", "billing_postal_code", "created_at",
        ),
    },
    "properties.csv": {
        "key": "properties",
        "id": "legacy_property_id",
        "required_file": True,
        "required": (
            "legacy_property_id", "legacy_contact_id", "service_street", "service_city",
            "service_state", "service_postal_code",
        ),
        "headers": (
            "legacy_property_id", "legacy_contact_id", "property_name", "service_street", "service_city",
            "service_state", "service_postal_code", "property_type", "claim_number", "insurer", "created_at",
        ),
    },
    "estimates.csv": {
        "key": "estimates",
        "id": "legacy_estimate_id",
        "required_file": True,
        "required": ("legacy_estimate_id", "legacy_contact_id", "estimate_number", "total_cents"),
        "headers": (
            "legacy_estimate_id", "legacy_contact_id", "legacy_property_id", "estimate_number", "revision",
            "status", "total_cents", "currency", "created_at", "accepted_at", "pdf_path",
        ),
    },
    "estimate_lines.csv": {
        "key": "estimate_lines",
        "id": "legacy_line_id",
        "required_file": True,
        "required": (
            "legacy_line_id", "legacy_estimate_id", "name", "quantity", "unit_price_cents", "line_total_cents",
        ),
        "headers": (
            "legacy_line_id", "legacy_estimate_id", "name", "description", "quantity", "unit_price_cents",
            "line_total_cents", "taxable",
        ),
    },
    "invoices.csv": {
        "key": "invoices",
        "id": "legacy_invoice_id",
        "required_file": True,
        "required": ("legacy_invoice_id", "legacy_contact_id", "invoice_number", "total_cents"),
        "headers": (
            "legacy_invoice_id", "legacy_estimate_id", "legacy_contact_id", "legacy_property_id", "invoice_number",
            "status", "total_cents", "currency", "issued_at", "due_at", "pdf_path",
        ),
    },
    "payments.csv": {
        "key": "payments",
        "id": "legacy_payment_id",
        "required_file": True,
        "required": ("legacy_payment_id", "legacy_invoice_id", "amount_cents"),
        "headers": (
            "legacy_payment_id", "legacy_invoice_id", "amount_cents", "currency", "status", "payment_method",
            "paid_at", "provider_reference",
        ),
    },
    "documents.csv": {
        "key": "documents",
        "id": "legacy_document_id",
        "required_file": False,
        "required": ("legacy_document_id", "document_type", "file_path"),
        "headers": (
            "legacy_document_id", "legacy_contact_id", "legacy_property_id", "legacy_estimate_id", "legacy_invoice_id",
            "document_type", "file_path", "signed_at", "sha256",
        ),
    },
    "notes.csv": {
        "key": "notes",
        "id": "legacy_note_id",
        "required_file": False,
        "required": ("legacy_note_id", "entity_type", "entity_id", "note"),
        "headers": ("legacy_note_id", "entity_type", "entity_id", "note", "created_at"),
    },
}

REQUIRED_FILES = tuple(name for name, spec in CSV_SPECS.items() if spec["required_file"])
ALLOWED_ATTACHMENT_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".txt", ".csv", ".doc", ".docx", ".rtf",
}
MAX_BUNDLE_BYTES = 250 * 1024 * 1024
MAX_ENTRY_BYTES = 50 * 1024 * 1024
MAX_ROWS_PER_FILE = 100_000


class ImportValidationError(ValueError):
    pass


def _safe_zip_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ImportValidationError(f"Unsafe ZIP entry: {name}")
    return path.as_posix()


def unpack_zip(data: bytes) -> dict[str, bytes]:
    if len(data) > MAX_BUNDLE_BYTES:
        raise ImportValidationError("The import ZIP exceeds the 250 MB local-lab limit.")
    values: dict[str, bytes] = {}
    total = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportValidationError("The uploaded file is not a valid ZIP archive.") from exc
    with archive:
        if len(archive.infolist()) > 2_000:
            raise ImportValidationError("The import ZIP contains too many files.")
        for info in archive.infolist():
            if info.is_dir():
                continue
            safe = _safe_zip_name(info.filename)
            if info.file_size > MAX_ENTRY_BYTES:
                raise ImportValidationError(f"{safe} exceeds the 50 MB per-file limit.")
            total += info.file_size
            if total > MAX_BUNDLE_BYTES:
                raise ImportValidationError("The expanded ZIP exceeds the 250 MB limit.")
            if safe.lower() in {name.lower() for name in values}:
                raise ImportValidationError(f"The ZIP contains duplicate path {safe!r}.")
            values[safe] = archive.read(info)
    return values


def bundle_files(bundle_name: str | None, bundle_data: bytes | None, individual: dict[str, bytes]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    if bundle_data:
        if not (bundle_name or "").lower().endswith(".zip"):
            raise ImportValidationError("The bundle upload must be a .zip file.")
        files.update(unpack_zip(bundle_data))
    for name, content in individual.items():
        if content:
            files[_safe_zip_name(name)] = content

    canonical: dict[str, bytes] = {}
    csv_seen: set[str] = set()
    for path, content in files.items():
        base = Path(path).name.lower()
        if base in CSV_SPECS:
            if base in csv_seen:
                raise ImportValidationError(f"The bundle contains more than one {base}.")
            canonical[base] = content
            csv_seen.add(base)
            continue
        if base == "readme.txt":
            continue
        suffix = Path(path).suffix.lower()
        if suffix in ALLOWED_ATTACHMENT_EXTENSIONS and base not in CSV_SPECS:
            canonical[path] = content
    return canonical


def _read_csv(name: str, data: bytes, errors: list[str]) -> list[dict[str, str]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        errors.append(f"{name} must be UTF-8 encoded.")
        return []
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = [str(value or "").strip() for value in (reader.fieldnames or [])]
    missing = sorted(set(CSV_SPECS[name]["required"]) - set(fields))
    if missing:
        errors.append(f"{name} is missing columns: {', '.join(missing)}")
        return []
    rows: list[dict[str, str]] = []
    for index, raw in enumerate(reader, start=2):
        if index > MAX_ROWS_PER_FILE + 1:
            errors.append(f"{name} exceeds {MAX_ROWS_PER_FILE:,} rows.")
            break
        row = {str(key or "").strip(): str(value or "").strip() for key, value in raw.items()}
        row["_row"] = str(index)
        rows.append(row)
    return rows


def _integer(value: str, source: str, row_number: str, errors: list[str], *, allow_negative: bool = False) -> int:
    try:
        amount = int(value)
    except (TypeError, ValueError):
        errors.append(f"{source}:{row_number} must use an integer, not {value!r}.")
        return 0
    if not allow_negative and amount < 0:
        errors.append(f"{source}:{row_number} cannot be negative.")
        return 0
    return amount


def _decimal(value: str, source: str, row_number: str, errors: list[str]) -> Decimal:
    try:
        amount = Decimal(value)
    except (TypeError, InvalidOperation):
        errors.append(f"{source}:{row_number} must be numeric, not {value!r}.")
        return Decimal(0)
    if amount <= 0:
        errors.append(f"{source}:{row_number} must be greater than zero.")
        return Decimal(0)
    return amount


def _date_warning(value: str, field: str, source: str, row_number: str, warnings: list[str]) -> None:
    if not value:
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        warnings.append(f"{source}:{row_number} {field} is not ISO-8601 and should be reviewed: {value!r}.")


def _unique(rows: list[dict[str, str]], key: str, source: str, errors: list[str]) -> set[str]:
    seen: set[str] = set()
    for row in rows:
        value = row.get(key, "").strip()
        if not value:
            errors.append(f"{source}:{row['_row']} has an empty {key}.")
        elif value in seen:
            errors.append(f"{source}:{row['_row']} duplicates {key}={value!r}.")
        seen.add(value)
    return seen


def _attachment_lookup(files: dict[str, bytes]) -> tuple[dict[str, str], dict[str, list[str]]]:
    exact: dict[str, str] = {}
    basenames: dict[str, list[str]] = defaultdict(list)
    for path in files:
        base = Path(path).name.lower()
        if base in CSV_SPECS or base == "readme.txt":
            continue
        normalized = _safe_zip_name(path).lower()
        exact[normalized] = path
        basenames[Path(normalized).name].append(path)
    return exact, basenames


def _resolve_attachment(reference: str, exact: dict[str, str], basenames: dict[str, list[str]]) -> str | None:
    if not reference:
        return None
    normalized = _safe_zip_name(reference).lower()
    if normalized in exact:
        return exact[normalized]
    candidates = basenames.get(Path(normalized).name, [])
    return candidates[0] if len(candidates) == 1 else None


def validate(files: dict[str, bytes]) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    for name in REQUIRED_FILES:
        if name not in files:
            errors.append(f"Missing required file: {name}")

    rows: dict[str, list[dict[str, str]]] = {
        spec["key"]: _read_csv(name, files[name], errors) if name in files else []
        for name, spec in CSV_SPECS.items()
    }
    contacts = rows["contacts"]
    properties = rows["properties"]
    estimates = rows["estimates"]
    estimate_lines = rows["estimate_lines"]
    invoices = rows["invoices"]
    payments = rows["payments"]
    documents = rows["documents"]
    notes = rows["notes"]

    ids = {
        spec["key"]: _unique(rows[spec["key"]], spec["id"], name, errors)
        for name, spec in CSV_SPECS.items()
    }

    for row in contacts:
        email = row.get("email", "")
        if email:
            try:
                row["email"] = validate_email(email, check_deliverability=False).normalized
            except EmailNotValidError as exc:
                errors.append(f"contacts.csv:{row['_row']} invalid email {email!r}: {exc}")
        phone = re.sub(r"[^0-9+]", "", row.get("phone", ""))
        if phone and len(re.sub(r"\D", "", phone)) < 10:
            warnings.append(f"contacts.csv:{row['_row']} phone number looks incomplete: {row.get('phone')!r}.")
        _date_warning(row.get("created_at", ""), "created_at", "contacts.csv", row["_row"], warnings)

    for row in properties:
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"properties.csv:{row['_row']} references unknown contact {row.get('legacy_contact_id')!r}.")
        _date_warning(row.get("created_at", ""), "created_at", "properties.csv", row["_row"], warnings)

    estimate_total = 0
    for row in estimates:
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"estimates.csv:{row['_row']} references unknown contact {row.get('legacy_contact_id')!r}.")
        property_id = row.get("legacy_property_id", "")
        if property_id and property_id not in ids["properties"]:
            errors.append(f"estimates.csv:{row['_row']} references unknown property {property_id!r}.")
        amount = _integer(row.get("total_cents", ""), "estimates.csv total_cents", row["_row"], errors)
        row["_total_cents"] = str(amount)
        estimate_total += amount
        _date_warning(row.get("created_at", ""), "created_at", "estimates.csv", row["_row"], warnings)
        _date_warning(row.get("accepted_at", ""), "accepted_at", "estimates.csv", row["_row"], warnings)

    line_total = 0
    lines_by_estimate: dict[str, int] = defaultdict(int)
    for row in estimate_lines:
        estimate_id = row.get("legacy_estimate_id", "")
        if estimate_id not in ids["estimates"]:
            errors.append(f"estimate_lines.csv:{row['_row']} references unknown estimate {estimate_id!r}.")
        quantity = _decimal(row.get("quantity", ""), "estimate_lines.csv quantity", row["_row"], errors)
        unit = _integer(row.get("unit_price_cents", ""), "estimate_lines.csv unit_price_cents", row["_row"], errors)
        total = _integer(row.get("line_total_cents", ""), "estimate_lines.csv line_total_cents", row["_row"], errors)
        expected = int((quantity * unit).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if quantity > 0 and total != expected:
            errors.append(
                f"estimate_lines.csv:{row['_row']} line_total_cents={total} does not equal quantity × unit price ({expected})."
            )
        row["_unit_price_cents"] = str(unit)
        row["_line_total_cents"] = str(total)
        row["_quantity"] = str(quantity)
        line_total += total
        lines_by_estimate[estimate_id] += total
    for row in estimates:
        estimate_id = row.get("legacy_estimate_id", "")
        if estimate_id in lines_by_estimate and lines_by_estimate[estimate_id] != int(row.get("_total_cents") or 0):
            errors.append(
                f"Estimate {estimate_id} line total is {lines_by_estimate[estimate_id]} cents but estimate total is {row.get('_total_cents')} cents."
            )

    invoice_total = 0
    invoice_amounts: dict[str, int] = {}
    for row in invoices:
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"invoices.csv:{row['_row']} references unknown contact {row.get('legacy_contact_id')!r}.")
        estimate_id = row.get("legacy_estimate_id", "")
        if estimate_id and estimate_id not in ids["estimates"]:
            warnings.append(f"invoices.csv:{row['_row']} references estimate {estimate_id!r}, which is not in estimates.csv.")
        property_id = row.get("legacy_property_id", "")
        if property_id and property_id not in ids["properties"]:
            errors.append(f"invoices.csv:{row['_row']} references unknown property {property_id!r}.")
        amount = _integer(row.get("total_cents", ""), "invoices.csv total_cents", row["_row"], errors)
        row["_total_cents"] = str(amount)
        invoice_total += amount
        invoice_amounts[row.get("legacy_invoice_id", "")] = amount
        _date_warning(row.get("issued_at", ""), "issued_at", "invoices.csv", row["_row"], warnings)
        _date_warning(row.get("due_at", ""), "due_at", "invoices.csv", row["_row"], warnings)
        if row.get("issued_at") and row.get("due_at") and row["issued_at"] != row["due_at"]:
            warnings.append(
                f"invoices.csv:{row['_row']} preserves a historical due date different from issued_at. New Floodman invoices are due upon sending."
            )

    payment_total = 0
    paid_by_invoice: dict[str, int] = defaultdict(int)
    for row in payments:
        invoice_id = row.get("legacy_invoice_id", "")
        if invoice_id not in ids["invoices"]:
            errors.append(f"payments.csv:{row['_row']} references unknown invoice {invoice_id!r}.")
        amount = _integer(row.get("amount_cents", ""), "payments.csv amount_cents", row["_row"], errors)
        row["_amount_cents"] = str(amount)
        payment_total += amount
        if str(row.get("status", "")).upper() not in {"FAILED", "CANCELLED", "VOID", "REFUNDED"}:
            paid_by_invoice[invoice_id] += amount
        _date_warning(row.get("paid_at", ""), "paid_at", "payments.csv", row["_row"], warnings)

    attachment_exact, attachment_basenames = _attachment_lookup(files)
    for row in estimates + invoices:
        reference = row.get("pdf_path", "")
        if reference:
            resolved = _resolve_attachment(reference, attachment_exact, attachment_basenames)
            if not resolved:
                warnings.append(f"Referenced PDF {reference!r} is not present or is ambiguous in the import ZIP.")
            else:
                row["_stored_file_path"] = resolved

    for row in documents:
        for field, id_key in (
            ("legacy_contact_id", "contacts"), ("legacy_property_id", "properties"),
            ("legacy_estimate_id", "estimates"), ("legacy_invoice_id", "invoices"),
        ):
            value = row.get(field, "")
            if value and value not in ids[id_key]:
                errors.append(f"documents.csv:{row['_row']} references unknown {field}={value!r}.")
        reference = row.get("file_path", "")
        resolved = _resolve_attachment(reference, attachment_exact, attachment_basenames)
        if not resolved:
            errors.append(f"documents.csv:{row['_row']} file {reference!r} is not present or is ambiguous in the ZIP.")
            continue
        row["_stored_file_path"] = resolved
        expected_hash = row.get("sha256", "").lower()
        actual_hash = hashlib.sha256(files[resolved]).hexdigest()
        row["_sha256"] = actual_hash
        if expected_hash and expected_hash != actual_hash:
            errors.append(f"documents.csv:{row['_row']} SHA-256 does not match {reference!r}.")
        _date_warning(row.get("signed_at", ""), "signed_at", "documents.csv", row["_row"], warnings)

    entity_sets = {
        "CONTACT": ids["contacts"], "PROPERTY": ids["properties"], "ESTIMATE": ids["estimates"],
        "INVOICE": ids["invoices"], "PAYMENT": ids["payments"], "DOCUMENT": ids["documents"],
    }
    for row in notes:
        entity_type = row.get("entity_type", "").upper()
        row["entity_type"] = entity_type
        if entity_type not in entity_sets:
            errors.append(f"notes.csv:{row['_row']} uses unsupported entity_type {entity_type!r}.")
        elif row.get("entity_id", "") not in entity_sets[entity_type]:
            errors.append(
                f"notes.csv:{row['_row']} references unknown {entity_type.lower()} {row.get('entity_id')!r}."
            )
        _date_warning(row.get("created_at", ""), "created_at", "notes.csv", row["_row"], warnings)

    outstanding_total = 0
    overpaid_total = 0
    for invoice_id, amount in invoice_amounts.items():
        paid = paid_by_invoice.get(invoice_id, 0)
        if paid > amount:
            overpaid_total += paid - amount
            warnings.append(f"Invoice {invoice_id} appears overpaid by ${(paid - amount) / 100:,.2f}.")
        outstanding_total += max(0, amount - paid)

    canonical = hashlib.sha256()
    for name in sorted(files):
        canonical.update(name.encode("utf-8"))
        canonical.update(b"\0")
        canonical.update(files[name])
        canonical.update(b"\0")

    normalized = {key: rows[key] for key in rows}
    counts = {key: len(rows[key]) for key in rows}
    counts["attachments"] = len(attachment_exact)
    summary = {
        "bundle_sha256": canonical.hexdigest(),
        "counts": counts,
        "totals": {
            "estimate_cents": estimate_total,
            "estimate_line_cents": line_total,
            "invoice_cents": invoice_total,
            "payment_cents": payment_total,
            "outstanding_cents": outstanding_total,
            "overpaid_cents": overpaid_total,
        },
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
        "included_files": sorted(files),
    }
    return summary, normalized


def _csv_bytes(name: str, rows: list[dict[str, str]] | None = None) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=CSV_SPECS[name]["headers"], lineterminator="\r\n")
    writer.writeheader()
    for row in rows or []:
        writer.writerow({key: row.get(key, "") for key in CSV_SPECS[name]["headers"]})
    return stream.getvalue().encode("utf-8-sig")


def template_files() -> dict[str, bytes]:
    values = {name: _csv_bytes(name) for name in CSV_SPECS}
    values["README.txt"] = (
        "Floodman local migration templates\r\n\r\n"
        "Required: contacts.csv, properties.csv, estimates.csv, estimate_lines.csv, invoices.csv, payments.csv.\r\n"
        "Optional but supported: documents.csv, notes.csv and referenced files.\r\n"
        "Use integer cents for money. Preserve untouched source exports separately.\r\n"
        "Imported invoices are historical archive records and do not start reminders or create Square links.\r\n"
    ).encode("utf-8")
    return values


def sample_files() -> dict[str, bytes]:
    rows: dict[str, list[dict[str, str]]] = {
        "contacts.csv": [{
            "legacy_contact_id": "contact-001", "first_name": "Jane", "last_name": "Sample",
            "email": "jane.sample@example.com", "phone": "+13135550199", "billing_street": "100 Sample St",
            "billing_city": "Detroit", "billing_state": "MI", "billing_postal_code": "48201",
            "created_at": "2025-04-01T14:00:00Z",
        }],
        "properties.csv": [{
            "legacy_property_id": "property-001", "legacy_contact_id": "contact-001", "property_name": "Sample Residence",
            "service_street": "100 Sample St", "service_city": "Detroit", "service_state": "MI",
            "service_postal_code": "48201", "property_type": "Residential basement", "claim_number": "",
            "insurer": "", "created_at": "2025-04-01T14:00:00Z",
        }],
        "estimates.csv": [{
            "legacy_estimate_id": "estimate-001", "legacy_contact_id": "contact-001", "legacy_property_id": "property-001",
            "estimate_number": "EST-1001", "revision": "1", "status": "ACCEPTED", "total_cents": "100000",
            "currency": "USD", "created_at": "2025-04-02T14:00:00Z", "accepted_at": "2025-04-03T14:00:00Z",
            "pdf_path": "exports/estimates/estimate-001.pdf",
        }],
        "estimate_lines.csv": [
            {"legacy_line_id": "line-001", "legacy_estimate_id": "estimate-001", "name": "Interior drain system",
             "description": "Sample scoped item", "quantity": "1", "unit_price_cents": "70000",
             "line_total_cents": "70000", "taxable": "false"},
            {"legacy_line_id": "line-002", "legacy_estimate_id": "estimate-001", "name": "Sump pump",
             "description": "Sample pump installation", "quantity": "1", "unit_price_cents": "30000",
             "line_total_cents": "30000", "taxable": "false"},
        ],
        "invoices.csv": [{
            "legacy_invoice_id": "invoice-001", "legacy_estimate_id": "estimate-001", "legacy_contact_id": "contact-001",
            "legacy_property_id": "property-001", "invoice_number": "INV-1001", "status": "PARTIALLY_PAID",
            "total_cents": "100000", "currency": "USD", "issued_at": "2025-04-04T14:00:00Z",
            "due_at": "2025-04-04T14:00:00Z", "pdf_path": "exports/invoices/invoice-001.pdf",
        }],
        "payments.csv": [{
            "legacy_payment_id": "payment-001", "legacy_invoice_id": "invoice-001", "amount_cents": "30000",
            "currency": "USD", "status": "COMPLETED", "payment_method": "CREDIT_CARD",
            "paid_at": "2025-04-04T15:00:00Z", "provider_reference": "square-sample-001",
        }],
        "documents.csv": [{
            "legacy_document_id": "document-001", "legacy_contact_id": "contact-001", "legacy_property_id": "property-001",
            "legacy_estimate_id": "estimate-001", "legacy_invoice_id": "invoice-001",
            "document_type": "WORK_AUTHORIZATION", "file_path": "exports/documents/work-authorization-001.pdf",
            "signed_at": "2025-04-03T14:00:00Z", "sha256": "",
        }],
        "notes.csv": [{
            "legacy_note_id": "note-001", "entity_type": "CONTACT", "entity_id": "contact-001",
            "note": "Customer prefers afternoon calls.", "created_at": "2025-04-01T14:15:00Z",
        }],
    }
    values = {name: _csv_bytes(name, rows.get(name, [])) for name in CSV_SPECS}
    values["README.txt"] = template_files()["README.txt"]
    values["exports/estimates/estimate-001.pdf"] = b"%PDF-1.4\n% Floodman sample estimate placeholder\n%%EOF\n"
    values["exports/invoices/invoice-001.pdf"] = b"%PDF-1.4\n% Floodman sample invoice placeholder\n%%EOF\n"
    values["exports/documents/work-authorization-001.pdf"] = b"%PDF-1.4\n% Floodman sample authorization placeholder\n%%EOF\n"
    return values


def create_zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return output.getvalue()
