#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import re
import sys
from collections import defaultdict
from pathlib import Path

SPECS = {
    "contacts.csv": ("legacy_contact_id", "first_name", "last_name", "email", "phone"),
    "properties.csv": ("legacy_property_id", "legacy_contact_id", "service_street", "service_city", "service_state", "service_postal_code"),
    "estimates.csv": ("legacy_estimate_id", "legacy_contact_id", "estimate_number", "total_cents"),
    "estimate_lines.csv": ("legacy_line_id", "legacy_estimate_id", "name", "quantity", "unit_price_cents", "line_total_cents"),
    "invoices.csv": ("legacy_invoice_id", "legacy_contact_id", "invoice_number", "total_cents"),
    "payments.csv": ("legacy_payment_id", "legacy_invoice_id", "amount_cents"),
    "documents.csv": ("legacy_document_id", "document_type", "file_path"),
    "notes.csv": ("legacy_note_id", "entity_type", "entity_id", "note"),
}
REQUIRED_FILES = {"contacts.csv", "properties.csv", "estimates.csv", "estimate_lines.csv", "invoices.csv", "payments.csv"}


def load(path: Path, required: tuple[str, ...], errors: list[str]) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = set(required) - set(reader.fieldnames or [])
        if missing:
            errors.append(f"{path.name}: missing columns {', '.join(sorted(missing))}")
            return []
        return [{str(k or '').strip(): str(v or '').strip() for k, v in row.items()} for row in reader]


def integer(value: str, label: str, errors: list[str]) -> int:
    try:
        amount = int(value)
    except ValueError:
        errors.append(f"{label}: expected integer cents, got {value!r}")
        return 0
    if amount < 0:
        errors.append(f"{label}: cannot be negative")
        return 0
    return amount


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    errors: list[str] = []
    warnings: list[str] = []
    for name in sorted(REQUIRED_FILES):
        if not (root / name).exists():
            errors.append(f"Missing required file: {name}")

    rows = {name[:-4]: load(root / name, spec, errors) for name, spec in SPECS.items()}
    ids: dict[str, set[str]] = {}
    for name, spec in SPECS.items():
        key = name[:-4]
        id_field = spec[0]
        seen: set[str] = set()
        for index, row in enumerate(rows[key], start=2):
            value = row.get(id_field, "")
            if not value:
                errors.append(f"{name}:{index}: empty {id_field}")
            elif value in seen:
                errors.append(f"{name}:{index}: duplicate {id_field}={value}")
            seen.add(value)
        ids[key] = seen

    for index, row in enumerate(rows["properties"], start=2):
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"properties.csv:{index}: unknown contact {row.get('legacy_contact_id')!r}")
    for index, row in enumerate(rows["estimates"], start=2):
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"estimates.csv:{index}: unknown contact {row.get('legacy_contact_id')!r}")
        prop = row.get("legacy_property_id", "")
        if prop and prop not in ids["properties"]:
            errors.append(f"estimates.csv:{index}: unknown property {prop!r}")
    lines_by_estimate: dict[str, int] = defaultdict(int)
    for index, row in enumerate(rows["estimate_lines"], start=2):
        estimate = row.get("legacy_estimate_id", "")
        if estimate not in ids["estimates"]:
            errors.append(f"estimate_lines.csv:{index}: unknown estimate {estimate!r}")
        quantity_text = row.get("quantity", "")
        try:
            quantity = float(quantity_text)
        except ValueError:
            errors.append(f"estimate_lines.csv:{index}: invalid quantity {quantity_text!r}")
            quantity = 0
        unit = integer(row.get("unit_price_cents", ""), f"estimate_lines.csv:{index} unit_price_cents", errors)
        total = integer(row.get("line_total_cents", ""), f"estimate_lines.csv:{index} line_total_cents", errors)
        expected = round(quantity * unit)
        if total != expected:
            errors.append(f"estimate_lines.csv:{index}: line_total_cents {total} does not equal quantity × unit price {expected}")
        lines_by_estimate[estimate] += total
    for index, row in enumerate(rows["estimates"], start=2):
        total = integer(row.get("total_cents", ""), f"estimates.csv:{index} total_cents", errors)
        if lines_by_estimate.get(row.get("legacy_estimate_id", ""), 0) != total:
            errors.append(f"estimates.csv:{index}: estimate lines do not reconcile to total_cents")

    invoice_amounts: dict[str, int] = {}
    for index, row in enumerate(rows["invoices"], start=2):
        if row.get("legacy_contact_id") not in ids["contacts"]:
            errors.append(f"invoices.csv:{index}: unknown contact {row.get('legacy_contact_id')!r}")
        invoice_amounts[row.get("legacy_invoice_id", "")] = integer(row.get("total_cents", ""), f"invoices.csv:{index} total_cents", errors)
    payment_total = 0
    paid_by_invoice: dict[str, int] = defaultdict(int)
    for index, row in enumerate(rows["payments"], start=2):
        invoice = row.get("legacy_invoice_id", "")
        if invoice not in ids["invoices"]:
            errors.append(f"payments.csv:{index}: unknown invoice {invoice!r}")
        amount = integer(row.get("amount_cents", ""), f"payments.csv:{index} amount_cents", errors)
        payment_total += amount
        if row.get("status", "").upper() not in {"FAILED", "CANCELLED", "VOID", "REFUNDED"}:
            paid_by_invoice[invoice] += amount

    for index, row in enumerate(rows["documents"], start=2):
        file_path = row.get("file_path", "").replace("\\", "/")
        candidate = root / file_path
        if not candidate.exists():
            errors.append(f"documents.csv:{index}: missing file {file_path!r}")
        expected = row.get("sha256", "").lower()
        if expected and candidate.exists():
            actual = hashlib.sha256(candidate.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(f"documents.csv:{index}: SHA-256 mismatch for {file_path!r}")

    allowed_note_types = {"CONTACT", "PROPERTY", "ESTIMATE", "INVOICE", "PAYMENT", "DOCUMENT"}
    id_by_note_type = {
        "CONTACT": ids["contacts"], "PROPERTY": ids["properties"], "ESTIMATE": ids["estimates"],
        "INVOICE": ids["invoices"], "PAYMENT": ids["payments"], "DOCUMENT": ids["documents"],
    }
    for index, row in enumerate(rows["notes"], start=2):
        kind = row.get("entity_type", "").upper()
        if kind not in allowed_note_types:
            errors.append(f"notes.csv:{index}: unsupported entity_type {kind!r}")
        elif row.get("entity_id") not in id_by_note_type[kind]:
            errors.append(f"notes.csv:{index}: unknown {kind.lower()} {row.get('entity_id')!r}")

    invoice_total = sum(invoice_amounts.values())
    outstanding = sum(max(0, amount - paid_by_invoice.get(invoice, 0)) for invoice, amount in invoice_amounts.items())
    print(f"Contacts:       {len(rows['contacts']):,}")
    print(f"Properties:     {len(rows['properties']):,}")
    print(f"Estimates:      {len(rows['estimates']):,}")
    print(f"Estimate lines: {len(rows['estimate_lines']):,}")
    print(f"Invoices:       {len(rows['invoices']):,}  ${invoice_total / 100:,.2f}")
    print(f"Payments:       {len(rows['payments']):,}  ${payment_total / 100:,.2f}")
    print(f"Outstanding:    ${outstanding / 100:,.2f}")
    print(f"Documents:      {len(rows['documents']):,}")
    print(f"Notes:          {len(rows['notes']):,}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    for error in errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
