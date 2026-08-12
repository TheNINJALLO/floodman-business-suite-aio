from __future__ import annotations

import base64
import os
import tempfile
import sys
import types
from pathlib import Path

os.environ.setdefault("INTERNAL_HMAC_KEYS", "v1:" + base64.b64encode(b"u" * 32).decode())
os.environ.setdefault("LAB_STATE_DIR", tempfile.mkdtemp(prefix="floodman-state-upgrade-module-"))

# The unit test only exercises state conversion; SMTP startup belongs to the Docker integration lane.
fake_aiosmtpd = types.ModuleType("aiosmtpd")
fake_controller = types.ModuleType("aiosmtpd.controller")
class _Controller:
    def __init__(self, *args, **kwargs):
        pass
    def start(self):
        pass
    def stop(self):
        pass
fake_controller.Controller = _Controller
fake_aiosmtpd.controller = fake_controller
sys.modules.setdefault("aiosmtpd", fake_aiosmtpd)
sys.modules.setdefault("aiosmtpd.controller", fake_controller)

from app.main import LabState
from app.persistence import JsonStateFile


def test_v115_public_state_restores_into_persistent_v120_store(tmp_path: Path) -> None:
    state = LabState()
    state.store = JsonStateFile(str(tmp_path))
    state._initialize_empty()

    snapshot = {
        "demo_job_id": "ca607b5c-c6a2-400e-99f2-cdda3b3055f3",
        "gauzy_contacts": [{"id": "contact_0001", "name": "Jane Local"}],
        "gauzy_invoices": [{"id": "ginvoice_0001", "invoiceNumber": "FM-1001", "totalValue": 1000}],
        "gauzy_payments": [{"id": "gpayment_0001", "invoiceId": "ginvoice_0001", "amount": 300}],
        "square_invoices": [{
            "id": "sinvoice_0001",
            "invoice_number": "FM-1001",
            "status": "UNPAID",
            "next_payment_amount_money": {"amount": 70000, "currency": "USD"},
            "payment_requests": [{"computed_amount_money": {"amount": 70000, "currency": "USD"}}],
        }],
        "envelopes": [{
            "id": "envelope_0001",
            "title": "Completion of Service",
            "status": "PENDING",
            "items": [{"id": "item_0001"}],
        }],
        "sms_messages": [{"id": "SM1", "body": "Invoice ready"}],
        "emails": [{"id": "mail_0001", "subject": "Invoice ready"}],
        "last_action": "Existing v1.1.5 job",
    }

    state.restore_api_snapshot(snapshot)

    assert state.demo_job_id == snapshot["demo_job_id"]
    assert state.contacts["contact_0001"]["name"] == "Jane Local"
    assert state.gauzy_invoices["ginvoice_0001"]["invoiceNumber"] == "FM-1001"
    assert state.square_invoices["sinvoice_0001"]["order_id"] in state.square_orders
    assert state.items["item_0001"]["pdf"].startswith(b"%PDF-1.4")
    assert state.sms_messages[0]["id"] == "SM1"
    assert state.emails[0]["id"] == "mail_0001"

    persisted = JsonStateFile(str(tmp_path)).load()
    assert persisted is not None
    assert persisted["demo_job_id"] == snapshot["demo_job_id"]
    assert persisted["items"]["item_0001"]["pdf"].startswith(b"%PDF-1.4")
