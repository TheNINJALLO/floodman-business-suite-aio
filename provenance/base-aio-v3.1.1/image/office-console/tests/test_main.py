from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

os.environ.setdefault("INTERNAL_HMAC_KEYS", "v1:" + base64.b64encode(b"i" * 32).decode())
os.environ.setdefault("AI_HMAC_KEYS", "ai-v1:" + base64.b64encode(b"a" * 32).decode())
os.environ.setdefault("OFFICE_CONSOLE_DATA_DIR", tempfile.mkdtemp(prefix="floodman-office-test-"))
os.environ.setdefault("OFFICE_AUTH_ENABLED", "true")

from fastapi.testclient import TestClient

from app import main
from app.store import OfficeStore


class FakeProviders:
    def __init__(self) -> None:
        self.contacts: list[dict[str, Any]] = []
        self.invoices: list[dict[str, Any]] = []
        self.payments: list[dict[str, Any]] = []
        self.documents: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []
        self.emails: list[dict[str, Any]] = []
        self.targets: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []

    async def lab_state(self) -> dict[str, Any]:
        return {
            "demo_job_id": "job-1",
            "job": {"id": "job-1", "state": "IN_PROGRESS"},
            "gauzy_contacts": {"items": list(self.contacts)},
            "properties": [],
            "gauzy_invoices": {"items": list(self.invoices)},
            "gauzy_payments": {"items": list(self.payments)},
            "square_invoices": [],
            "envelopes": list(self.documents),
            "staff_alerts": [],
            "ar_cases": [],
            "sms_messages": list(self.messages),
            "emails": [],
            "imported_documents": [],
            "notes": [],
        }

    async def connection_tests(self) -> dict[str, Any]:
        names = (
            "orchestrator",
            "gauzy_workflow_bridge",
            "gauzy_full_ui",
            "square",
            "documenso_workflow_bridge",
            "documenso_full_ui",
            "twilio",
            "smtp",
            "mailpit",
            "roomflow",
            "messaging_ai",
            "competitor_intelligence",
        )
        return {name: {"status": "CONNECTED", "detail": "local test"} for name in names}

    async def create_contact(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": f"contact-{len(self.contacts) + 1}", **payload}
        self.contacts.append(item)
        return item

    async def create_invoice(self, payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        item = {"id": f"invoice-{len(self.invoices) + 1}", **payload, "invoiceItems": items}
        self.invoices.append(item)
        return item

    async def update_invoice(self, invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        for item in self.invoices:
            if item.get("id") == invoice_id:
                item.update(payload)
                return item
        return {"id": invoice_id, **payload}

    async def record_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": f"payment-{len(self.payments) + 1}", **payload}
        self.payments.append(item)
        return item

    async def create_signing_document(self, **values: Any) -> dict[str, Any]:
        item = {"id": f"document-{len(self.documents) + 1}", "status": "PENDING", **values}
        self.documents.append(item)
        return item

    async def send_sms(self, phone: str, body: str) -> dict[str, Any]:
        item = {"id": f"message-{len(self.messages) + 1}", "to": phone, "body": body, "status": "SENT"}
        self.messages.append(item)
        return item

    async def send_email(self, *, to: str, subject: str, text: str) -> dict[str, Any]:
        item = {"id": f"email-{len(self.emails) + 1}", "to": to, "subject": subject, "text": text}
        self.emails.append(item)
        return item

    async def commit_import(self, normalized: dict[str, Any], run_id: str) -> dict[str, Any]:
        return {
            "created": {key: len(normalized.get(key) or []) for key in (
                "contacts", "properties", "estimates", "estimate_lines",
                "invoices", "payments", "documents", "notes",
            )},
            "archived": {key: len(normalized.get(key) or []) for key in ("properties", "estimate_lines", "documents", "notes")},
            "skipped": {},
            "mode": "HISTORICAL_ARCHIVE",
            "automatic_reminders_enabled": False,
            "run_id": run_id,
        }

    async def competitor_targets(self) -> list[dict[str, Any]]:
        return list(self.targets)

    async def competitor_reports(self) -> list[dict[str, Any]]:
        return list(self.reports)

    async def add_competitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = {"id": f"target-{len(self.targets) + 1}", "enabled": True, "last_run_at": None, "last_error": None, **payload}
        self.targets.append(item)
        return item

    async def competitor_target(self, target_id: str) -> dict[str, Any]:
        return next(item for item in self.targets if item["id"] == target_id)

    async def update_competitor(self, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        item = await self.competitor_target(target_id)
        item.update(payload)
        return item

    async def delete_competitor(self, target_id: str) -> dict[str, Any]:
        self.targets[:] = [item for item in self.targets if item["id"] != target_id]
        self.reports[:] = [item for item in self.reports if item["target_id"] != target_id]
        return {"deleted": True}

    async def competitor_report(self, report_id: str) -> dict[str, Any]:
        return next(item for item in self.reports if item["id"] == report_id)

    async def run_competitor(self, target_id: str) -> dict[str, Any]:
        target = await self.competitor_target(target_id)
        report = {
            "id": f"report-{len(self.reports) + 1}", "target_id": target_id, "target_name": target["name"],
            "status": "COMPLETED", "created_at": "2026-08-05T12:00:00Z", "evidence": [],
            "report": {"executive_summary": "Competitor scan completed.", "floodman_opportunities": ["Publish clearer service scopes."]},
            "change_summary": {"initial_snapshot": True},
        }
        self.reports.append(report)
        return {"target_id": target_id, "status": "COMPLETED", "report_id": report["id"]}

    async def gauzy_context(self) -> dict[str, Any]:
        return {"tenant_id": "tenant-1", "organization_id": "org-1", "from_organization_id": "org-1", "sync_enabled": False}

    async def authenticate_gauzy_member(self, email: str, password: str) -> dict[str, Any]:
        if password != "gauzy-password":
            raise RuntimeError("Gauzy did not accept that email and password.")
        normalized = email.strip().lower()
        is_admin = normalized == "admin@ever.co"
        return {
            "email": normalized,
            "name": "Gauzy Administrator" if is_admin else "Gauzy Employee",
            "gauzy_user_id": "gauzy-admin" if is_admin else "gauzy-user",
            "gauzy_employee_id": "" if is_admin else "gauzy-employee",
            "gauzy_role": "SUPER_ADMIN" if is_admin else "EMPLOYEE",
            "tenant_id": "tenant-1",
            "organization_id": "org-1" if not is_admin else "",
            "suggested_office_role": "ADMIN" if is_admin else "TECHNICIAN",
            "is_gauzy_admin": is_admin,
        }


def _client(tmp_path, monkeypatch) -> TestClient:
    local_store = OfficeStore(str(tmp_path))
    local_store.create_owner("Primary Owner", "owner@example.com", "OwnerPassword123!")
    monkeypatch.setattr(main, "store", local_store)
    monkeypatch.setattr(main, "providers", FakeProviders())
    client = TestClient(main.app)
    login = client.post(
        "/login",
        data={"email": "owner@example.com", "password": "OwnerPassword123!", "next": "/office"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    return client


def _finish_setup(client: TestClient) -> None:
    assert client.post(
        "/setup/profile",
        data={
            "company_name": "Floodman Local",
            "office_email": "office@example.com",
            "billing_email": "billing@example.com",
            "timezone": "America/Detroit",
        },
        follow_redirects=False,
    ).status_code == 303
    assert client.post("/setup/test-connections", follow_redirects=False).status_code == 303
    assert client.post(
        "/setup/checklist",
        data={"legal_reviewed": "true", "messaging_reviewed": "true", "import_reviewed": "true"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post("/setup/finish", follow_redirects=False).status_code == 303


def test_first_gauzy_admin_becomes_owner_and_uses_office_session(tmp_path, monkeypatch) -> None:
    local_store = OfficeStore(str(tmp_path))
    monkeypatch.setattr(main, "store", local_store)
    monkeypatch.setattr(main, "providers", FakeProviders())
    client = TestClient(main.app)

    response = client.post(
        "/login/gauzy",
        data={"email": "admin@ever.co", "password": "gauzy-password", "next": "/office"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/office"
    assert "floodman_session" in response.cookies
    owner = local_store.user_by_email("admin@ever.co")
    assert owner is not None
    assert owner["role"] == "OWNER"
    assert owner["auth_source"] == "GAUZY"
    assert owner["password_hash"] == ""

    office = client.get("/office")
    assert office.status_code == 200
    assert "Floodman Office" in office.text


def test_gauzy_employee_is_auto_provisioned_after_owner_exists(tmp_path, monkeypatch) -> None:
    local_store = OfficeStore(str(tmp_path))
    local_store.upsert_gauzy_user(
        {
            "email": "admin@ever.co",
            "name": "Gauzy Administrator",
            "gauzy_role": "SUPER_ADMIN",
            "suggested_office_role": "ADMIN",
            "is_gauzy_admin": True,
        }
    )
    monkeypatch.setattr(main, "store", local_store)
    monkeypatch.setattr(main, "providers", FakeProviders())
    client = TestClient(main.app)

    response = client.post(
        "/login/gauzy",
        data={"email": "employee@ever.co", "password": "gauzy-password", "next": "/office/time"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/office/time"
    employee = local_store.user_by_email("employee@ever.co")
    assert employee is not None
    assert employee["role"] == "TECHNICIAN"
    assert employee["gauzy_employee_id"] == "gauzy-employee"


def test_setup_wizard_and_office_pages_render(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    root = client.get("/", follow_redirects=False)
    assert root.status_code == 302
    assert root.headers["location"] == "/setup"

    assert client.get("/setup").status_code == 200
    _finish_setup(client)

    root = client.get("/", follow_redirects=False)
    assert root.headers["location"] == "/office"

    for path in (
        "/office",
        "/office/apps",
        "/office/linking",
        "/office/imports",
        "/office/contacts",
        "/office/properties",
        "/office/tasks",
        "/office/notes",
        "/office/estimates",
        "/office/invoices",
        "/office/payments",
        "/office/documents",
        "/office/time",
        "/office/members",
        "/office/messages",
        "/office/receivables",
        "/office/intelligence",
        "/office/alerts",
        "/office/gauzy",
        "/office/signing",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "Floodman Office" in response.text


def test_owner_can_create_operational_records_and_invite_member(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _finish_setup(client)

    contact = client.post(
        "/office/contacts/add",
        data={
            "first_name": "Kaitlyn",
            "last_name": "Aldrich",
            "company": "",
            "email": "kaitlyn@example.com",
            "phone": "+13135550199",
            "lead_source": "Referral",
            "notes": "Primary decision maker",
        },
        follow_redirects=False,
    )
    assert contact.status_code == 303
    contact_id = contact.headers["location"].rsplit("/", 1)[-1]

    prop = client.post(
        "/office/properties/add",
        data={
            "contact_id": contact_id,
            "name": "Aldrich Residence",
            "service_street": "123 Main Street",
            "service_city": "Detroit",
            "service_state": "MI",
            "service_postal_code": "48201",
            "property_type": "Residential",
            "notes": "Basement waterproofing",
        },
        follow_redirects=False,
    )
    assert prop.status_code == 303
    property_id = prop.headers["location"].rsplit("/", 1)[-1]

    estimate = client.post(
        "/office/estimates/add",
        data={
            "contact_id": contact_id,
            "property_id": property_id,
            "estimate_number": "EST-2026-0001",
            "title": "Basement waterproofing",
            "expiration_days": "30",
            "deposit_percent": "30",
            "status": "DRAFT",
            "terms": "Due upon receipt after completion.",
            "line_items": "Interior drain system | 80 | 45.00\nSump pump | 1 | 850.00",
        },
        follow_redirects=False,
    )
    assert estimate.status_code == 303
    estimate_id = estimate.headers["location"].rsplit("/", 1)[-1]

    invoice = client.post(f"/office/estimates/{estimate_id}/convert", follow_redirects=False)
    assert invoice.status_code == 303
    invoice_id = invoice.headers["location"].rsplit("/", 1)[-1]
    payment = client.post(
        f"/office/invoices/{invoice_id}/payment",
        data={"amount": "100.00", "method": "CASH", "reference": "DEP-1", "note": "Deposit"},
        follow_redirects=False,
    )
    assert payment.status_code == 303

    assert client.post(
        "/office/notes/add",
        data={"entity_type": "CONTACT", "entity_id": contact_id, "note": "Called customer."},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        "/office/tasks/add",
        data={"title": "Schedule crew", "assigned_to": "", "due_at": "2026-08-20T09:00", "priority": "HIGH", "description": f"Related invoice {invoice_id}"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        "/office/time/in",
        data={"job_reference": "JOB-1001", "note": "Site visit"},
        follow_redirects=False,
    ).status_code == 303
    assert client.post("/office/time/out", data={"note": "Visit complete"}, follow_redirects=False).status_code == 303

    document = client.post(
        "/office/documents/add",
        data={
            "title": "Work Authorization",
            "document_type": "WORK_AUTHORIZATION",
            "contact_id": contact_id,
            "invoice_id": invoice_id,
            "recipient_name": "Kaitlyn Aldrich",
            "recipient_email": "kaitlyn@example.com",
        },
        files={"document": ("authorization.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        follow_redirects=False,
    )
    assert document.status_code == 303

    invite = client.post(
        "/office/members/invite",
        data={"name": "Office Manager", "email": "manager@example.com", "role": "OFFICE_MANAGER"},
        follow_redirects=False,
    )
    assert invite.status_code == 200
    assert "Invitation created" in invite.text
    members = client.get("/office/members")
    assert "manager@example.com" in members.text
    assert "OFFICE_MANAGER" in members.text

    assert "Kaitlyn Aldrich" in client.get("/office/contacts").text
    assert "Aldrich Residence" in client.get("/office/properties").text
    assert "Basement waterproofing" in client.get("/office/estimates").text
    assert "Deposit" in client.get("/office/payments").text
    assert "Work Authorization" in client.get("/office/documents").text
    assert "Schedule crew" in client.get("/office/tasks").text
    assert "JOB-1001" in client.get("/office/time").text


def test_sample_import_upload_review_and_commit(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    sample = client.get("/office/imports/sample.zip")
    assert sample.status_code == 200
    assert sample.headers["content-type"].startswith("application/zip")

    upload = client.post(
        "/office/imports/upload",
        files={"bundle": ("sample.zip", sample.content, "application/zip")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    review_path = upload.headers["location"]
    assert review_path.startswith("/office/imports/")

    review = client.get(review_path)
    assert review.status_code == 200
    assert "Commit to local archive" in review.text
    assert "$700.00" in review.text

    nested_file = client.get(review_path + "/files/exports/documents/work-authorization-001.pdf")
    assert nested_file.status_code == 200
    assert nested_file.headers["content-type"].startswith("application/pdf")

    commit = client.post(review_path + "/commit", follow_redirects=False)
    assert commit.status_code == 303
    committed = client.get(review_path)
    assert "COMMITTED" in committed.text
    assert "Automatic reminders remain off" in committed.text

    contacts = client.get("/office/contacts")
    properties = client.get("/office/properties")
    estimates = client.get("/office/estimates")
    invoices = client.get("/office/invoices")
    payments = client.get("/office/payments")
    documents = client.get("/office/documents")
    notes = client.get("/office/notes")
    dashboard = client.get("/office")
    assert "Jane Sample" in contacts.text
    assert "Sample Residence" in properties.text
    assert "EST-1001" in estimates.text
    assert "Interior drain system" not in estimates.text
    assert "INV-1001" in invoices.text
    assert "exports/invoices/invoice-001.pdf" in invoices.text
    assert "$300.00" in payments.text
    assert "work-authorization-001.pdf" in documents.text
    assert "Customer prefers afternoon calls." in notes.text
    assert "Imported archive balance" in dashboard.text
    assert "$700.00" in dashboard.text


def test_competitor_monitor_full_crud(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _finish_setup(client)
    created = client.post(
        "/office/intelligence/add",
        data={"name": "Example Waterproofing", "url": "https://example.com", "category": "Waterproofing", "frequency_hours": "168", "additional_paths": "/services,/about"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    page = client.get("/office/intelligence")
    assert "Example Waterproofing" in page.text
    target_id = main.providers.targets[0]["id"]
    edit = client.post(
        f"/office/intelligence/{target_id}/edit",
        data={"name": "Example Restoration", "url": "https://example.com", "category": "Restoration", "frequency_hours": "24", "additional_paths": "/services", "enabled": "true"},
        follow_redirects=False,
    )
    assert edit.status_code == 303
    assert "Example Restoration" in client.get("/office/intelligence").text
    run = client.post(f"/office/intelligence/{target_id}/run", follow_redirects=False)
    assert run.status_code == 303
    report_id = main.providers.reports[0]["id"]
    report = client.get(f"/office/intelligence/reports/{report_id}")
    assert report.status_code == 200
    assert "Publish clearer service scopes" in report.text
    deleted = client.post(f"/office/intelligence/{target_id}/delete", follow_redirects=False)
    assert deleted.status_code == 303
    assert "Example Restoration" not in client.get("/office/intelligence").text


def test_invited_member_can_join_and_permissions_apply(tmp_path, monkeypatch) -> None:
    import re

    client = _client(tmp_path, monkeypatch)
    _finish_setup(client)
    response = client.post(
        "/office/members/invite",
        data={"name": "Estimator One", "email": "estimator@example.com", "role": "ESTIMATOR"},
    )
    assert response.status_code == 200
    match = re.search(r"/invite/(invite_[A-Za-z0-9_-]+)", response.text)
    assert match
    token = match.group(1)
    client.post("/logout", follow_redirects=False)
    accepted = client.post(
        f"/invite/{token}",
        data={"password": "EstimatorPassword123!", "confirm_password": "EstimatorPassword123!"},
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert client.get("/office").status_code == 200
    assert client.get("/office/contacts").status_code == 200
    assert client.get("/office/members").status_code == 403
    assert client.get("/setup").status_code == 403
