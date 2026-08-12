from __future__ import annotations

import threading
from pathlib import Path

from app.archive_import import apply_historical_import
from app.persistence import JsonStateFile


class State:
    def __init__(self, tmp_path: Path) -> None:
        self.lock = threading.RLock()
        self.contacts = {}
        self.properties = {}
        self.gauzy_invoices = {}
        self.gauzy_payments = {}
        self.imported_documents = {}
        self.notes = {}
        self.legacy_mappings = {
            key: {} for key in (
                "contacts", "properties", "estimates", "estimate_lines",
                "invoices", "payments", "documents", "notes",
            )
        }
        self.import_runs = []
        self.import_history = []
        self.last_action = ""
        self.counters = {}
        self.store = JsonStateFile(str(tmp_path))

    def next_id(self, prefix: str) -> str:
        self.counters[prefix] = self.counters.get(prefix, 0) + 1
        return f"{prefix}_{self.counters[prefix]:04d}"

    def save(self) -> None:
        self.store.save({"last_action": self.last_action})


def payload() -> dict:
    return {
        "run_id": "sample-run",
        "archive_base_url": "http://localhost:9000",
        "records": {
            "contacts": [{
                "legacy_contact_id": "c1", "first_name": "Jane", "last_name": "Sample",
                "email": "jane@example.com", "phone": "+13135550199",
            }],
            "properties": [{
                "legacy_property_id": "p1", "legacy_contact_id": "c1",
                "service_street": "1 Main", "service_city": "Detroit",
                "service_state": "MI", "service_postal_code": "48201",
            }],
            "estimates": [{
                "legacy_estimate_id": "e1", "legacy_contact_id": "c1",
                "legacy_property_id": "p1", "estimate_number": "E-1", "revision": "1",
                "status": "ACCEPTED", "total_cents": "100000", "currency": "USD",
            }],
            "estimate_lines": [{
                "legacy_line_id": "l1", "legacy_estimate_id": "e1", "name": "Drain",
                "quantity": "1", "unit_price_cents": "100000", "line_total_cents": "100000",
            }],
            "invoices": [{
                "legacy_invoice_id": "i1", "legacy_estimate_id": "e1", "legacy_contact_id": "c1",
                "legacy_property_id": "p1", "invoice_number": "I-1", "status": "PARTIALLY_PAID",
                "total_cents": "100000", "currency": "USD", "pdf_path": "exports/invoice.pdf",
            }],
            "payments": [{
                "legacy_payment_id": "pay1", "legacy_invoice_id": "i1", "amount_cents": "30000",
                "status": "COMPLETED", "payment_method": "CREDIT_CARD", "currency": "USD",
            }],
            "documents": [{
                "legacy_document_id": "d1", "legacy_contact_id": "c1", "legacy_property_id": "p1",
                "legacy_estimate_id": "e1", "legacy_invoice_id": "i1", "document_type": "WORK_AUTHORIZATION",
                "file_path": "exports/authorization.pdf",
            }],
            "notes": [{
                "legacy_note_id": "n1", "entity_type": "CONTACT", "entity_id": "c1",
                "note": "Afternoons preferred",
            }],
        },
    }


def test_historical_import_maps_every_category_and_never_creates_square(tmp_path: Path) -> None:
    state = State(tmp_path)
    result = apply_historical_import(state, payload())

    assert result["created"] == {
        "contacts": 1, "properties": 1, "estimates": 1, "estimate_lines": 1,
        "invoices": 1, "payments": 1, "documents": 1, "notes": 1,
    }
    assert result["automatic_reminders_enabled"] is False
    assert result["reconciliation"] == {
        "invoice_total_cents": 100000,
        "payment_total_cents": 30000,
        "outstanding_cents": 70000,
    }
    invoice_id = state.legacy_mappings["invoices"]["i1"]
    invoice = state.gauzy_invoices[invoice_id]
    assert invoice["amountDue"] == 700
    assert invoice["automaticRemindersEnabled"] is False
    assert invoice["pdf_url"].endswith("/office/imports/sample-run/files/exports/invoice.pdf")
    assert len(state.properties) == 1
    assert len(state.imported_documents) == 1
    assert len(state.notes) == 1


def test_historical_import_is_idempotent_by_legacy_id(tmp_path: Path) -> None:
    state = State(tmp_path)
    apply_historical_import(state, payload())
    result = apply_historical_import(state, payload())
    assert all(value == 0 for value in result["created"].values())
    assert all(value == 1 for value in result["skipped"].values())


def test_json_state_file_round_trips_binary_document_data(tmp_path: Path) -> None:
    store = JsonStateFile(str(tmp_path))
    value = {"item": {"pdf": b"%PDF-1.4\n%%EOF\n"}, "count": 1}
    store.save(value)
    assert store.load() == value
