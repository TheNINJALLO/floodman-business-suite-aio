from __future__ import annotations

import os
import asyncio
import json
import re
import shutil
import socket
import tempfile
import threading
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

REQUIRED_VIEWPORTS = [
    (320, 568), (360, 640), (375, 667), (390, 844), (412, 915), (430, 932),
    (540, 720), (667, 375), (844, 390), (768, 1024), (820, 1180),
    (1024, 768), (1024, 1366), (1280, 720), (1366, 768), (1440, 900),
    (1536, 864), (1920, 1080), (2560, 1440),
]
TRANSITION_VIEWPORTS = [(719, 900), (720, 900), (721, 900), (1099, 900), (1100, 900), (1101, 900)]


class FakeProviders:
    def __init__(self) -> None:
        self.sent_emails: list[dict[str, Any]] = []
        self.sent_sms: list[dict[str, str]] = []

    async def lab_state(self) -> dict[str, Any]:
        return {
            "demo_job_id": "ui-smoke-job",
            "job": {},
            "gauzy_contacts": {"items": []},
            "properties": [],
            "gauzy_invoices": {"items": []},
            "gauzy_payments": {"items": []},
            "square_invoices": [],
            "envelopes": [],
            "staff_alerts": [],
            "ar_cases": [],
            "sms_messages": [],
            "messages": [],
            "message_threads": [],
            "emails": [],
            "imported_documents": [],
            "notes": [],
        }

    async def competitor_targets(self) -> list[dict[str, Any]]:
        return []

    async def competitor_reports(self) -> list[dict[str, Any]]:
        return []

    async def gauzy_context(self) -> dict[str, Any]:
        return {
            "tenant_id": "ui-smoke-tenant",
            "organization_id": "ui-smoke-organization",
            "from_organization_id": "ui-smoke-organization",
            "sync_enabled": False,
        }

    def square_payment_configuration(self) -> dict[str, Any]:
        return {
            "environment": "local",
            "application_id": "",
            "location_id": "local-square-location",
            "sdk_url": "",
            "live": False,
            "local_mock": True,
        }

    async def send_email(self, **message: Any) -> dict[str, Any]:
        self.sent_emails.append(dict(message))
        return {"status": "SENT", "to": message.get("to"), "subject": message.get("subject")}

    async def send_sms(self, phone: str, body: str) -> dict[str, Any]:
        self.sent_sms.append({"phone": phone, "body": body})
        return {"status": "SENT", "to": phone}

    async def record_payment(self, _payment: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    async def ensure_square_customer(self, _contact: dict[str, Any]) -> dict[str, Any]:
        return {"id": "ui-smoke-square-customer"}

    async def create_square_payment(self, **values: Any) -> dict[str, Any]:
        return {
            "id": f"ui-smoke-square-{values['source_id']}",
            "status": "COMPLETED",
            "receipt_url": "https://example.test/receipt",
            "card_details": {
                "entry_method": "KEYED",
                "card": {"card_brand": "VISA", "last_4": "1111", "exp_month": 12, "exp_year": 2030},
            },
        }


def seed(main: Any) -> dict[str, Any]:
    owner = main.store.create_owner("UI Smoke Owner", "owner@example.test", "Floodman-Test-2026!")
    owner = main.store.update_user(owner["id"], phone="+12315550199")
    workspace = main.ensure_roomflow_workspaces(main.store, actor_id=str(owner["id"]))[0]
    contact = main.store.create_record(
        "contacts",
        {
            "workspace_id": workspace["id"],
            "name": "Alex Carter",
            "first_name": "Alex",
            "last_name": "Carter",
            "email": "alex@example.test",
            "phone": "2315550148",
            "status": "ACTIVE_CUSTOMER",
            "street": "1847 Pine Ridge Lane",
            "city": "Traverse City",
            "state": "MI",
            "postal_code": "49686",
        },
        actor_id=owner["id"],
    )
    property_record = main.store.create_record(
        "properties",
        {
            "workspace_id": workspace["id"],
            "contact_id": contact["id"],
            "name": "Carter Residence",
            "property_name": "Carter Residence",
            "property_type": "Residential",
            "service_street": "1847 Pine Ridge Lane",
            "service_city": "Traverse City",
            "service_state": "MI",
            "service_postal_code": "49686",
        },
        actor_id=owner["id"],
    )
    other_contact = main.store.create_record(
        "contacts",
        {
            "workspace_id": workspace["id"],
            "name": "Morgan Vale",
            "first_name": "Morgan",
            "last_name": "Vale",
            "email": "morgan@example.test",
            "phone": "2315550199",
            "status": "ACTIVE_CUSTOMER",
        },
        actor_id=owner["id"],
    )
    other_property = main.store.create_record(
        "properties",
        {
            "workspace_id": workspace["id"],
            "contact_id": other_contact["id"],
            "name": "Vale Warehouse",
            "property_name": "Vale Warehouse",
            "property_type": "Commercial",
            "service_street": "900 Hidden Road",
            "service_city": "Traverse City",
            "service_state": "MI",
            "service_postal_code": "49684",
        },
        actor_id=owner["id"],
    )
    section = {"id": "section-1", "name": "Waterproofing", "description": "", "sort_order": 0}
    line = {
        "id": "line-1",
        "section_id": "section-1",
        "section_name": "Waterproofing",
        "name": "Interior perimeter drainage",
        "description": "Install a customer-approved drainage system.",
        "quantity": 10,
        "unit": "LF",
        "unit_price_cents": 4500,
        "line_total_cents": 45000,
        "selected": True,
        "sort_order": 0,
    }
    common = {
        "contact_id": contact["id"],
        "property_id": property_record["id"],
        "title": "Carter basement waterproofing",
        "currency": "USD",
        "sections": [section],
        "line_items": [line],
        "total_cents": 45000,
        "terms": "Payment is due according to the signed agreement.",
    }
    estimate = main.store.create_record(
        "estimates",
        {
            **common,
            "estimate_number": "EST-UI-001",
            "status": "ACCEPTED",
            "deposit_type": "PERCENT",
            "deposit_percent": 30,
            "deposit_due_stage": "IMMEDIATELY",
            "deposit_payable": True,
        },
        actor_id=owner["id"],
    )
    invoice = main.store.create_record(
        "invoices",
        {
            **common,
            "invoice_number": "INV-UI-001",
            "status": "PARTIALLY_PAID",
            "balance_cents": 30000,
            "paid_cents": 15000,
            "collection_mode": "PAYMENT_PAGE",
        },
        actor_id=owner["id"],
    )
    payment = main.store.create_record(
        "payments",
        {
            "invoice_id": invoice["id"],
            "contact_id": contact["id"],
            "amount_cents": 15000,
            "currency": "USD",
            "status": "COMPLETED",
            "method": "CARD",
            "payment_date": "2026-08-12",
            "processor_payment_id": "ui-smoke-payment",
            "card_brand": "VISA",
            "last_4": "1111",
        },
        actor_id=owner["id"],
    )
    estimate = main._ensure_public_document("estimate", estimate, actor_id=owner["id"])
    invoice = main._ensure_public_document("invoice", invoice, actor_id=owner["id"])
    roomflow_job = main.store.create_record(
        "roomflow_jobs",
        {
            "id": "browser-capture-job",
            "roomflow_job_id": "browser-upstream-job",
            "workspace_id": workspace["id"],
            "contact_id": contact["id"],
            "property_id": property_record["id"],
            "estimate_id": estimate["id"],
            "job_name": "Browser Capture Job",
            "snapshot": {"rooms": [], "costing": {"customItems": []}},
            "source": "TEST_FIXTURE",
        },
        actor_id=owner["id"],
    )
    call_intake = main.store.project_call_intake({
        "intake_id": "ui-call-intake",
        "organization_id": "ui-smoke-organization",
        "workspace_id": workspace["id"],
        "provider": "deterministic",
        "provider_call_id": "ui-call-provider-id",
        "event_type": "caller-identified",
        "event_sequence": 1,
        "status": "ACTIVE",
        "occurred_at": "2026-09-08T20:20:00+00:00",
        "started_at": "2026-09-08T20:19:55+00:00",
        "ended_at": None,
        "caller": {"name": "Alex Carter", "first_name": "Alex", "last_name": "Carter", "email": "alex@example.test", "phone": "+12315550148", "phone_e164": "+12315550148", "phone_verified": True, "company": ""},
        "property": {"name": "Carter Residence", "property_type": "Residential", "street": "1847 Pine Ridge Lane", "city": "Traverse City", "state": "MI", "postal_code": "49686", "country": "US", "insurer": "", "claim_number": ""},
        "service_reason": "Basement waterproofing inspection",
        "summary": "Alex reports water near the basement wall and requests an inspection.",
        "requested_services": ["Inspection"],
        "urgency": "PRIORITY",
        "appointment": {"requested": True, "requested_window": "weekday afternoon", "confirmed": False, "appointment_id": ""},
        "consent": {"sms_status": "UNKNOWN", "email_status": "UNKNOWN", "disclosure_version": "", "evidence_id": ""},
        "transcript_available": True,
        "transcript_reference": "lab://ui-smoke/transcript",
        "failure_reason": "",
        "review_reasons": [],
        "proposed_ids": {"customer_id": "ui-call-customer", "property_id": "ui-call-property", "job_id": "ui-call-job", "roomflow_job_id": "ui-call-roomflow-job", "estimate_id": "ui-call-estimate", "note_id": "ui-call-note", "task_id": "ui-call-task", "appointment_id": "ui-call-appointment"},
    })
    return {"owner": owner, "contact": contact, "property": property_record, "other_contact": other_contact, "other_property": other_property, "estimate": estimate, "invoice": invoice, "payment": payment, "workspace": workspace, "roomflow_job": roomflow_job, "call_intake": call_intake}


def route_smoke(main: Any, records: dict[str, Any]) -> None:
    from fastapi.testclient import TestClient
    from app.security import SignedClient, canonical_json, parse_first_key

    client = TestClient(main.app, follow_redirects=False)
    login = client.post(
        "/login",
        data={"email": "owner@example.test", "password": "Floodman-Test-2026!", "next": "/office/desktop"},
    )
    assert login.status_code == 303
    assert "floodman_session" in client.cookies

    intake = records["call_intake"]
    internal_payload = {
        key: intake.get(key)
        for key in (
            "intake_id", "organization_id", "workspace_id", "provider", "provider_call_id", "status",
            "started_at", "ended_at", "caller", "property", "service_reason", "summary", "requested_services",
            "urgency", "appointment", "consent", "transcript_available", "transcript_reference", "failure_reason",
            "review_reasons", "proposed_ids",
        )
    }
    internal_payload.update({
        "event_type": "transcript-updated",
        "event_sequence": 2,
        "occurred_at": "2026-09-08T20:20:10+00:00",
    })
    signed_body = canonical_json(internal_payload)
    key_id, secret = parse_first_key(main.settings.internal_hmac_keys)
    signer = SignedClient("http://office.invalid", key_id, secret)
    invalid = client.post(
        "/internal/v1/call-intakes/project",
        content=signed_body,
        headers={**signer.headers(signed_body), "x-floodman-signature": "invalid"},
    )
    assert invalid.status_code == 401
    accepted = client.post(
        "/internal/v1/call-intakes/project",
        content=signed_body,
        headers=signer.headers(signed_body),
    )
    assert accepted.status_code == 200, accepted.text
    assert main.providers.sent_emails, "eligible staff did not receive the call-intake email notification"
    assert main.providers.sent_sms, "eligible staff did not receive the call-intake SMS notification"
    notification = next(
        value for value in main.store.records("notifications")
        if str(value.get("reference_id") or "") == str(intake["id"])
    )
    assert notification["email_status"] == "SENT"
    assert notification["sms_status"] == "SENT"
    projected_intake = main.store.record("call_intakes", str(intake["id"]))
    call_estimate_id = str(projected_intake["estimate_id"])
    call_card = client.get(f"/office/api/call-intakes/item/{intake['id']}")
    assert call_card.status_code == 200
    roomflow_link = call_card.json()["links"]["roomflow"]
    assert roomflow_link.endswith(f"job_id={projected_intake['roomflow_job_id']}")
    selected_roomflow = client.get(roomflow_link)
    assert selected_roomflow.status_code == 200
    assert f"embedded=1&amp;job_id={projected_intake['roomflow_job_id']}" in selected_roomflow.text
    email_count = len(main.providers.sent_emails)
    assert client.post(f"/office/estimates/{call_estimate_id}/send").status_code == 303
    assert client.post(f"/office/estimates/{call_estimate_id}/accept").status_code == 303
    assert client.post(f"/office/estimates/{call_estimate_id}/convert").status_code == 303
    protected_draft = main.store.record("estimates", call_estimate_id)
    assert protected_draft["status"] == "DRAFT" and protected_draft["total_cents"] == 0
    assert len(main.providers.sent_emails) == email_count, "unpriced call draft sent customer email"
    assert not any(str(value.get("estimate_id") or "") == call_estimate_id for value in main.store.records("invoices"))

    pages = [
        "/setup", "/office", "/office/desktop", "/office/mobile?mobile=1", "/office/apps", "/office/settings",
        "/office/linking", "/office/imports", "/office/contacts", "/office/properties",
        "/office/catalog", "/office/estimates", "/office/estimates/new", "/office/invoices",
        "/office/payments", "/office/payment-settings", "/office/documents", "/office/tasks",
        "/office/notes", "/office/time", "/office/members", "/office/messages", "/office/calls",
        "/office/receivables", "/office/intelligence", "/office/alerts", "/office/platform",
        "/office/signing", "/office/roomflow", "/office/roomflow/import",
        f"/office/contacts/{records['contact']['id']}",
        f"/office/contacts/{records['contact']['id']}/edit",
        f"/office/properties/{records['property']['id']}",
        f"/office/properties/{records['property']['id']}/edit",
        f"/office/estimates/{records['estimate']['id']}",
        f"/office/estimates/{records['estimate']['id']}/edit",
        f"/office/estimates/{records['estimate']['id']}/take-payment",
        f"/office/calls/{records['call_intake']['id']}",
        f"/office/invoices/{records['invoice']['id']}",
        f"/office/invoices/{records['invoice']['id']}/edit",
        f"/office/invoices/{records['invoice']['id']}/take-payment",
    ]
    for path in pages:
        response = client.get(path)
        if path == "/office/payment-settings":
            assert response.status_code == 303 and response.headers["location"] == "/office/service-setup#square"
            response = client.get("/office/service-setup")
        assert response.status_code == 200, f"{path} returned {response.status_code}: {response.text[:300]}"
        assert "Floodman" in response.text, f"{path} did not render a Floodman page"

    unselected_properties = client.get("/office/properties")
    assert "Select a customer" in unselected_properties.text
    assert "Carter Residence" not in unselected_properties.text
    assert "Vale Warehouse" not in unselected_properties.text
    selected_properties = client.get(f"/office/properties?contact_id={records['contact']['id']}")
    assert "Carter Residence" in selected_properties.text
    assert "Vale Warehouse" not in selected_properties.text
    other_properties = client.get(f"/office/properties?contact_id={records['other_contact']['id']}")
    assert "Vale Warehouse" in other_properties.text
    assert "Carter Residence" not in other_properties.text
    contact_file = client.get(f"/office/contacts/{records['contact']['id']}")
    assert "Carter Residence" in contact_file.text
    assert "Vale Warehouse" not in contact_file.text
    edit_property = client.get(f"/office/properties/{records['property']['id']}/edit")
    assert "Customer ID" not in edit_property.text
    assert "Search customer" in edit_property.text
    invalid_customer = client.get("/office/properties?contact_id=missing-customer")
    assert invalid_customer.status_code == 404

    settings_page = client.get("/office/settings")
    assert "OWNER START HERE" in settings_page.text
    assert "Everyday setup" in settings_page.text and "Advanced connections" in settings_page.text
    setup_page = client.get("/setup")
    assert "Eastern Time (Detroit)" in setup_page.text
    assert "name='timezone'" in setup_page.text and "name='timezone' value=" not in setup_page.text
    original_profile = main.store.profile()
    rejected_timezone = client.post(
        "/setup/profile",
        data={"company_name": "UI Smoke", "timezone": "UTC", "state": "MI"},
    )
    assert rejected_timezone.status_code == 303
    assert main.store.profile() == original_profile, "invalid time zone changed the company profile"
    invites_before = len(main.store.list_invites())
    rejected_owner = client.post(
        "/office/members/invite",
        data={"name": "Unsafe Owner", "email": "unsafe-owner@example.test", "role": "OWNER"},
    )
    assert rejected_owner.status_code == 303
    assert len(main.store.list_invites()) == invites_before, "a second owner invitation was accepted"
    workspaces_before = len(main.store.records("roomflow_workspaces"))
    rejected_workspace = client.post(
        "/office/api/roomflow/workspaces",
        json={"name": "Wrong Time Company", "timezone": "UTC"},
    )
    assert rejected_workspace.status_code == 422
    assert len(main.store.records("roomflow_workspaces")) == workspaces_before
    original_import = main.import_roomflow_supabase
    captured_import: dict[str, str] = {}
    try:
        def fake_import(_store: Any, *, email: str, password: str, actor_id: str, **_kwargs: Any) -> dict[str, Any]:
            captured_import.update(email=email, password=password, actor_id=actor_id)
            return {"counts": {"jobs": 2}, "workspaces": [{"id": "workspace-test"}]}

        main.import_roomflow_supabase = fake_import
        imported = client.post(
            "/office/roomflow/import",
            data={"email": "old-roomflow@example.test", "password": "Temporary-RoomFlow-Password"},
        )
        assert imported.status_code == 303
        assert captured_import["email"] == "old-roomflow@example.test"
        assert "Temporary-RoomFlow-Password" not in str(main.store.snapshot())
    finally:
        main.import_roomflow_supabase = original_import

    for kind in ("estimate", "invoice"):
        record = records[kind]
        token = record["public_token"]
        public_page = client.get(f"/customer/{kind}/{token}")
        assert public_page.status_code == 200
        assert "Created by Josh Aldrich" not in public_page.text or "Floodman" in public_page.text
        pdf = client.get(f"/customer/{kind}/{token}/pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF-")

    invoice_token = records["invoice"]["public_token"]
    portal = client.get(f"/customer/invoice/{invoice_token}")
    assert "Message the Floodman team" in portal.text
    portal_message = "Could you confirm the installation date? <script>alert(1)</script>"
    first_message = client.post(
        f"/customer/invoice/{invoice_token}/messages",
        data={"body": portal_message, "request_id": "ui-smoke-customer-message-001", "website": ""},
    )
    assert first_message.status_code == 303 and first_message.headers["location"].endswith("#messages")
    thread_id = main._customer_thread_id(
        records["contact"]["id"], records["property"]["id"], records["invoice"]["id"]
    )
    customer_messages = main._customer_thread_messages(thread_id)
    assert len(customer_messages) == 1 and customer_messages[0]["sender_kind"] == "CUSTOMER"
    message_alerts = [item for item in main.store.records("notifications") if item.get("kind") == "CUSTOMER_MESSAGE"]
    assert len(message_alerts) == 1 and message_alerts[0]["status"] == "UNREAD"
    assert message_alerts[0]["email_status"] == "SENT"
    staff_alert_email = next(item for item in main.providers.sent_emails if str(item.get("subject") or "").startswith("Floodman customer message"))
    assert portal_message not in str(staff_alert_email.get("text") or ""), "customer message text leaked into an alert email"
    duplicate_message = client.post(
        f"/customer/invoice/{invoice_token}/messages",
        data={"body": portal_message, "request_id": "ui-smoke-customer-message-001", "website": ""},
    )
    assert duplicate_message.status_code == 303
    assert len(main._customer_thread_messages(thread_id)) == 1, "portal retry created a duplicate message"
    oversized_message = client.post(
        f"/customer/invoice/{invoice_token}/messages",
        data={"body": "x" * 3001, "request_id": "ui-smoke-customer-message-002", "website": ""},
    )
    assert oversized_message.status_code == 422
    assert len(main._customer_thread_messages(thread_id)) == 1, "an invalid portal message was stored"

    other_property = main.store.create_record(
        "properties",
        {
            "contact_id": records["contact"]["id"],
            "name": "Carter Rental",
            "service_street": "100 Fictional Avenue",
            "service_city": "Traverse City",
            "service_state": "MI",
            "service_postal_code": "49686",
        },
        actor_id=records["owner"]["id"],
    )
    other_invoice = main.store.create_record(
        "invoices",
        {
            "contact_id": records["contact"]["id"],
            "property_id": other_property["id"],
            "invoice_number": "INV-UI-ISOLATED",
            "title": "Separate fictional property",
            "status": "SENT",
            "currency": "USD",
            "sections": [],
            "line_items": [],
            "total_cents": 10000,
            "paid_cents": 0,
            "balance_cents": 10000,
        },
        actor_id=records["owner"]["id"],
    )
    other_invoice = main._ensure_public_document("invoice", other_invoice, actor_id=records["owner"]["id"])
    isolated_portal = client.get(f"/customer/invoice/{other_invoice['public_token']}")
    assert isolated_portal.status_code == 200
    assert "Could you confirm the installation date?" not in isolated_portal.text, "a different property link exposed the conversation"

    staff_view = client.get(f"/office/messages?thread={thread_id}")
    assert staff_view.status_code == 200 and "Could you confirm the installation date?" in staff_view.text
    assert "<script>alert(1)</script>" not in staff_view.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in staff_view.text
    assert main.store.record("notifications", message_alerts[0]["id"])["status"] == "READ"
    reply = client.post(
        f"/office/messages/{thread_id}/reply",
        data={"body": "Yes. Your installation is scheduled for Tuesday morning.", "request_id": "ui-smoke-staff-reply-001"},
    )
    assert reply.status_code == 303
    customer_email = next(item for item in main.providers.sent_emails if item.get("to") == "alex@example.test")
    assert "replied to your secure message" in str(customer_email.get("subject") or "").lower()
    customer_email_count = len([item for item in main.providers.sent_emails if item.get("to") == "alex@example.test"])
    duplicate_reply = client.post(
        f"/office/messages/{thread_id}/reply",
        data={"body": "Yes. Your installation is scheduled for Tuesday morning.", "request_id": "ui-smoke-staff-reply-001"},
    )
    assert duplicate_reply.status_code == 303
    assert len([item for item in main.providers.sent_emails if item.get("to") == "alex@example.test"]) == customer_email_count
    replied_portal = client.get(f"/customer/invoice/{invoice_token}")
    assert "Tuesday morning" in replied_portal.text and "1 new reply" in replied_portal.text
    assert "<script>alert(1)</script>" not in replied_portal.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in replied_portal.text
    marked_read = client.post(f"/customer/invoice/{invoice_token}/messages/read")
    assert marked_read.status_code == 303
    assert all(item.get("customer_read_at") for item in main._customer_thread_messages(thread_id) if item.get("sender_kind") == "STAFF")

    payment_response = client.post(
        f"/office/invoices/{records['invoice']['id']}/payment",
        data={"amount": "10.00", "method": "CHECK", "reference": "UI-SMOKE-CHECK", "note": "Fictional test payment"},
    )
    assert payment_response.status_code == 303
    payment_alerts = [item for item in main.store.records("notifications") if item.get("kind") == "PAYMENT_RECEIVED"]
    assert len(payment_alerts) == 1 and payment_alerts[0]["status"] == "UNREAD"
    assert payment_alerts[0]["email_status"] == "SENT"
    payment = next(item for item in main.store.records("payments") if item.get("reference") == "UI-SMOKE-CHECK")
    before_retry = len(payment_alerts)
    asyncio.run(main._notify_payment_admins("invoice", main.store.record("invoices", records["invoice"]["id"]), payment))
    assert len([item for item in main.store.records("notifications") if item.get("kind") == "PAYMENT_RECEIVED"]) == before_retry
    alerts_page = client.get("/office/alerts")
    assert "Payment received" in alerts_page.text and "Customer Message" in alerts_page.text
    opened_alert = client.get(f"/office/alerts/{payment_alerts[0]['id']}/open")
    assert opened_alert.status_code == 303 and f"/office/invoices/{records['invoice']['id']}" in opened_alert.headers["location"]
    assert main.store.record("notifications", payment_alerts[0]["id"])["status"] == "READ"
    assert client.post("/office/alerts/read-all").status_code == 303
    owner_alerts = [item for item in main.store.records("notifications") if item.get("user_id") == records["owner"]["id"]]
    assert owner_alerts and all(item.get("status") == "READ" for item in owner_alerts)

    pay = client.get(f"/customer/pay/{records['invoice']['public_token']}")
    assert pay.status_code == 200 and "secure payment" in pay.text.lower()
    card_payment = client.post(
        f"/customer/pay/{records['invoice']['public_token']}/process",
        json={"source_id": "one-time-token-001", "amount_cents": 500, "save_card": False},
    )
    assert card_payment.status_code == 200 and card_payment.json()["processor_status"] == "COMPLETED"
    payment_admin_email_count = len([item for item in main.providers.sent_emails if str(item.get("subject") or "").startswith("Floodman payment received")])
    card_payment_retry = client.post(
        f"/customer/pay/{records['invoice']['public_token']}/process",
        json={"source_id": "one-time-token-001", "amount_cents": 500, "save_card": False},
    )
    assert card_payment_retry.status_code == 200
    processor_payments = [item for item in main.store.records("payments") if item.get("processor_payment_id") == "ui-smoke-square-one-time-token-001"]
    assert len(processor_payments) == 1, "processor retry created a duplicate payment"
    card_alerts = [item for item in main.store.records("notifications") if item.get("kind") == "PAYMENT_RECEIVED"]
    assert len(card_alerts) == 2, "processor retry duplicated or omitted the administrator alert"
    assert len([item for item in main.providers.sent_emails if str(item.get("subject") or "").startswith("Floodman payment received")]) == payment_admin_email_count
    receipt = client.get(
        f"/customer/receipt/{records['invoice']['public_token']}?payment={records['payment']['id']}"
    )
    assert receipt.status_code == 200 and "PAYMENT RECEIPT" in receipt.text
    legacy = client.get("/office/gauzy")
    assert legacy.status_code in {302, 303, 307, 308}


def static_overlay_contracts() -> None:
    sources = {
        "pwa_js": (ROOT / "pwa" / "floodman-pwa.js").read_text(encoding="utf-8"),
        "pwa_css": (ROOT / "pwa" / "floodman-pwa.css").read_text(encoding="utf-8"),
        "pwa_sw": (ROOT / "pwa" / "floodman-sw.js").read_text(encoding="utf-8"),
        "panel_js": (ROOT / "roomflow" / "floodman-panel.js").read_text(encoding="utf-8"),
        "panel_css": (ROOT / "roomflow" / "floodman-panel.css").read_text(encoding="utf-8"),
        "capture_js": (ROOT / "roomflow" / "capture" / "roomflow-capture.js").read_text(encoding="utf-8"),
        "capture_css": (ROOT / "roomflow" / "capture" / "roomflow-capture.css").read_text(encoding="utf-8"),
        "legacy_js": (ROOT / "roomflow" / "floodman-roomflow.js").read_text(encoding="utf-8"),
        "legacy_css": (ROOT / "roomflow" / "floodman-roomflow.css").read_text(encoding="utf-8"),
        "hub_js": (ROOT / "hub" / "hub.js").read_text(encoding="utf-8"),
        "launcher": (REPO / "launcher" / "mobile-start.sh").read_text(encoding="utf-8"),
        "deployment": (REPO / "deployment" / "releases" / "mobile-start-v4.7.3.sh").read_text(encoding="utf-8"),
        "nginx": (ROOT / "aio" / "nginx.conf.template").read_text(encoding="utf-8"),
        "office": (ROOT / "office-console" / "app" / "main.py").read_text(encoding="utf-8"),
    }
    assert "fm-pwa-toast-dismiss" in sources["pwa_js"] and "Dismiss notification" in sources["pwa_js"]
    assert ".fm-pwa-toast-dismiss" in sources["pwa_css"]
    pwa_precache = sources["pwa_sw"].split("const PRECACHE = [", 1)[1].split("];", 1)[0]
    assert "'/workspace'" not in pwa_precache and "'/full-erp'" not in pwa_precache
    assert "Customer, document, API, Office, signing, and ERP responses remain network-only" in sources["pwa_sw"]
    assert "fm-rf-panel-dismissed" in sources["panel_js"]
    assert "floodman_roomflow_quick_start_dismissed_v1" in sources["panel_js"]
    assert "params.get('job_id')" in sources["panel_js"] and "loadServerJob(requestedJobId)" in sources["panel_js"]
    assert "Dismiss quick start" in sources["panel_js"] and "Dismiss message" in sources["panel_js"]
    assert "params.get('catalog_sync') === '1'" in sources["panel_js"]
    assert "event.key === 'Escape'" in sources["panel_js"]
    assert "No separate RoomFlow account is required" in sources["panel_js"]
    assert "authOverlay.style.display = 'none'" in sources["panel_js"]
    assert "btn-more-create-company" in sources["panel_js"] and "changeWorkspace" in sources["panel_js"]
    assert "/office/api/roomflow/workspaces" in sources["office"]
    assert ":not(.fm-rf-panel-dismissed)" in sources["panel_css"]
    assert "RoomFlowCaptureBridgeV2" in sources["capture_js"] and "version: 2, sessionId, type, requestId" in sources["capture_js"]
    assert "encoded.count <= 256 * 1024" not in sources["capture_js"] and "serialized.length > 262144" in sources["capture_js"]
    assert "Start from a room template" in sources["capture_js"] and "Compare captured plan" in sources["capture_js"]
    assert "data-plan-vertex" in sources["capture_js"] and "data-lock-wall" in sources["capture_js"]
    assert "Camera-derived dimensions are estimates" in sources["capture_js"]
    assert "dialog.addEventListener('cancel'" in sources["capture_js"] and "closeDialog" in sources["capture_js"]
    assert "@media (max-width: 720px)" in sources["capture_css"] and "100dvh" in sources["capture_css"]
    assert "fmrf-close-icon" in sources["legacy_js"] and "aria-label','Close save dialog" in sources["legacy_js"]
    assert "e.key === 'Escape'" in sources["legacy_js"] and "fmrf-modal-open" in sources["legacy_css"]
    assert "aria-modal" in sources["hub_js"] and "Back to Floodman" in sources["hub_js"]
    assert "location = /api/auth/login" in sources["nginx"]
    assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in sources["nginx"]
    assert "error_page 401 =302 /login?next=/roomflow/" in sources["nginx"]
    assert "floodmanLoginNext" in sources["office"] and "/login/erp-session" in sources["office"]
    for key in ("launcher", "deployment"):
        assert "floodman-dismiss-recovery" in sources[key]
        assert "event.key === 'Escape'" in sources[key]
        assert "Created by Josh Aldrich" in sources[key]
        assert "const pendingLoginKey = 'floodmanLoginNext'" in sources[key]
        assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in sources[key]


def browser_executable() -> str | None:
    candidates = [
        shutil.which("msedge"), shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    return next((str(candidate) for candidate in candidates if candidate and Path(candidate).is_file()), None)


def build_browser_app(main: Any) -> Any:
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

    app = FastAPI()

    files = {
        "/workspace": ROOT / "pwa" / "workspace.html",
        "/full-erp": ROOT / "pwa" / "erp.html",
        "/floodman-pwa.css": ROOT / "pwa" / "floodman-pwa.css",
        "/floodman-pwa.js": ROOT / "pwa" / "floodman-pwa.js",
        "/floodman-sw.js": ROOT / "pwa" / "floodman-sw.js",
        "/floodman-workspace.css": ROOT / "pwa" / "workspace-mode.css",
        "/floodman-offline.html": ROOT / "pwa" / "offline.html",
        "/floodman-starting.html": ROOT / "hub" / "starting.html",
        "/install-app": ROOT / "pwa" / "install.html",
        "/manifest.webmanifest": ROOT / "pwa" / "manifest.webmanifest",
        "/hub.css": ROOT / "hub" / "hub.css",
        "/hub.js": ROOT / "hub" / "hub.js",
        "/roomflow/floodman-panel.css": ROOT / "roomflow" / "floodman-panel.css",
        "/roomflow/floodman-panel.js": ROOT / "roomflow" / "floodman-panel.js",
        "/roomflow/roomflow-capture.css": ROOT / "roomflow" / "capture" / "roomflow-capture.css",
        "/roomflow/roomflow-capture-geometry.js": ROOT / "roomflow" / "capture" / "roomflow-capture-geometry.js",
        "/roomflow/roomflow-capture.js": ROOT / "roomflow" / "capture" / "roomflow-capture.js",
        "/legacy-roomflow.css": ROOT / "roomflow" / "floodman-roomflow.css",
        "/legacy-roomflow.js": ROOT / "roomflow" / "floodman-roomflow.js",
    }
    for route, path in files.items():
        app.add_api_route(route, lambda path=path: FileResponse(path), methods=["GET"])

    @app.get("/floodman-brand/{name}")
    def brand(name: str) -> FileResponse:
        assert name in {"floodman-mark.svg", "floodman-wordmark.svg"}
        return FileResponse(ROOT / "hub" / "brand" / name)

    @app.get("/floodman-pwa-icons/{name}")
    def pwa_icon(name: str) -> FileResponse:
        path = ROOT / "pwa" / "icons" / name
        return FileResponse(path)

    @app.get("/office-health/live")
    def office_health() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": "4.7.3"})

    @app.get("/hub-fixture")
    def hub_fixture() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/hub.css'></head><body><main><h1>Floodman ERP fixture</h1></main><script>window.FLOODMAN_HUB_CONFIG={officeUrl:location.origin,competitorUrl:location.origin+'/office/intelligence'};</script><script src='/hub.js'></script></body></html>""")

    @app.get("/roomflow/")
    def roomflow_fixture() -> HTMLResponse:
        workspace = main.store.records("roomflow_workspaces")[0]
        fixture_state = json.dumps({"currentJobName": "UI Fixture", "jobId": "browser-upstream-job", "floodmanRoomFlowJobId": "browser-capture-job", "workspaceId": workspace["id"], "organizationId": workspace["id"], "currentLevelId": "basement", "costing": {"customItems": []}})
        return HTMLResponse(f"""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/roomflow/floodman-panel.css'><link rel='stylesheet' href='/roomflow/roomflow-capture.css'></head><body><main><h1>RoomFlow fixture</h1><canvas id='sketch-canvas' width='320' height='240'></canvas><div class='checklist-room-card'><h3>Active Workspaces</h3><p>Legacy account controls</p><select id='more-company-switcher'><option value=''>Select...</option></select><input id='more-new-company-name'><button id='btn-more-create-company'>Create</button><button onclick='RoomFlowAuth.signOut()'>Log Out from Account</button></div><button id='btn-refresh-shared-jobs'>Refresh Shared Jobs</button></main><div id='auth-overlay' class='hidden' style='display:none'>Separate RoomFlow account required</div><script>window.state={fixture_state};window.switchTab=function(){{}};window.RoomFlowAuth={{signOut:function(){{}}}};window.__legacyAccountPrompted=false;window.autosaveJob=function(){{}};window.draw=function(){{}};document.addEventListener('DOMContentLoaded',function(){{document.getElementById('btn-more-create-company').addEventListener('click',function(){{window.__legacyAccountPrompted=true;document.getElementById('auth-overlay').style.display='flex';}});}});</script><script src='/roomflow/floodman-panel.js'></script><script src='/roomflow/roomflow-capture-geometry.js'></script><script src='/roomflow/roomflow-capture.js'></script></body></html>""")

    @app.get("/legacy-roomflow")
    def legacy_roomflow_fixture() -> HTMLResponse:
        return HTMLResponse("""<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1'><link rel='stylesheet' href='/legacy-roomflow.css'></head><body><main><h1>Legacy RoomFlow fixture</h1></main><script>window.state={currentJobName:'Legacy Fixture',costing:{customItems:[]}};</script><script src='/legacy-roomflow.js'></script></body></html>""")

    app.mount("/", main.app)
    return app


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def authenticate_browser_page(page: Any, base: str) -> None:
    page.goto(base + "/login/local?next=/office/desktop", wait_until="domcontentloaded")
    form = page.locator("form[action='/login']")
    form.locator("input[name='email']").fill("owner@example.test")
    form.locator("input[name='password']").fill("Floodman-Test-2026!")
    form.locator("button").click()
    page.wait_for_url(re.compile(r"/office(?:/desktop|/mobile)?(?:[?#]|$)"))


def assert_layout_contract(page: Any, label: str, *, office_shell: bool = False) -> None:
    contract_script = """() => {
      const root = document.documentElement;
      const viewportWidth = root.clientWidth;
      const hiddenFocusable = Array.from(document.querySelectorAll('[aria-hidden="true"]')).flatMap(container =>
        Array.from(container.querySelectorAll('a[href],button,input,select,textarea,[tabindex]'))
          .filter(node => !node.disabled && node.tabIndex >= 0 && !node.closest('[inert]'))
          .map(node => ({tag: node.tagName, id: node.id, text: (node.textContent || '').trim().slice(0, 60)}))
      ).slice(0, 10);
      const fixedOutside = Array.from(document.querySelectorAll('body *')).filter(node => {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || Number(style.opacity) === 0) return false;
        if (node.getAttribute('aria-hidden') === 'true' || node.closest('[aria-hidden="true"],[inert]')) return false;
        if (style.position !== 'fixed' && style.position !== 'sticky') return false;
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && (rect.left < -2 || rect.right > viewportWidth + 2);
      }).slice(0, 10).map(node => ({tag: node.tagName, id: node.id, className: String(node.className).slice(0, 80)}));
      const uncloseableDialogs = Array.from(document.querySelectorAll('[role="dialog"]')).filter(dialog => {
        const style = getComputedStyle(dialog);
        if (style.display === 'none' || style.visibility === 'hidden' || dialog.closest('[aria-hidden="true"]')) return false;
        return !Array.from(dialog.querySelectorAll('button,[role="button"]')).some(button =>
          /close|cancel|done|dismiss/i.test(`${button.getAttribute('aria-label') || ''} ${button.textContent || ''}`)
        );
      }).map(node => node.id || node.className || node.tagName);
      const oversizedShellIcons = Array.from(document.querySelectorAll(
        '.mobile-topbar svg,.mobile-bottom-nav svg,.sidebar-mobile-head svg'
      )).filter(node => {
        const style = getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden' || node.closest('[hidden],[inert]')) return false;
        const rect = node.getBoundingClientRect();
        return rect.width > 48 || rect.height > 48;
      }).map(node => {
        const rect = node.getBoundingClientRect();
        return {className: String(node.parentElement?.className || ''), width: rect.width, height: rect.height};
      });
      return {
        rootOverflow: root.scrollWidth - viewportWidth,
        hiddenFocusable,
        fixedOutside,
        uncloseableDialogs,
        oversizedShellIcons,
        skipLinks: document.querySelectorAll('a.skip-link[href="#fm-main-content"]').length,
        mainTargets: document.querySelectorAll('main#fm-main-content').length,
      };
    }"""
    try:
        result = page.evaluate(contract_script)
    except Exception as error:
        if "Execution context was destroyed" not in str(error):
            raise
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(100)
        result = page.evaluate(contract_script)
    assert result["rootOverflow"] <= 2, f"root horizontal overflow ({label}): {result}"
    assert not result["hiddenFocusable"], f"hidden controls remain keyboard-focusable ({label}): {result}"
    assert not result["fixedOutside"], f"fixed or sticky surface is clipped ({label}): {result}"
    assert not result["uncloseableDialogs"], f"visible dialog has no close path ({label}): {result}"
    assert not result["oversizedShellIcons"], f"shell icon exceeded its visual bounds ({label}): {result}"
    if office_shell:
        assert result["skipLinks"] == 1 and result["mainTargets"] == 1, f"Office landmarks missing ({label}): {result}"


def layout_browser_matrix(playwright: Any, base: str, portal_token: str) -> None:
    representative_routes = [
        ("/office/desktop?desktop=1", True),
        ("/office/mobile?mobile=1", True),
        ("/office/settings", True),
        ("/office/contacts", True),
        ("/office/calls", True),
        ("/office/photo-portal", True),
        ("/office/estimates/new", True),
        ("/office/roomflow", True),
        ("/office/roomflow/import", True),
        (f"/customer/invoice/{portal_token}#messages", False),
        ("/roomflow/", False),
        ("/hub-fixture", False),
        ("/office/settings?desktop=1", True),
    ]
    browser_matrix = [
        ("chromium", playwright.chromium, REQUIRED_VIEWPORTS),
        ("firefox", playwright.firefox, [(320, 568), (390, 844), (844, 390), (1024, 768), (1440, 900)]),
        ("webkit", playwright.webkit, [(320, 568), (390, 844), (844, 390), (1024, 768), (1440, 900)]),
    ]
    evidence_root = os.environ.get("FLOODMAN_UI_EVIDENCE_DIR", "").strip()
    evidence_path = Path(evidence_root) if evidence_root else None
    if evidence_path:
        evidence_path.mkdir(parents=True, exist_ok=True)

    for browser_name, browser_type, viewports in browser_matrix:
        browser = browser_type.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
        page = context.new_page()
        page_errors: list[str] = []
        console_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        authenticate_browser_page(page, base)
        for width, height in viewports:
            page.set_viewport_size({"width": width, "height": height})
            for path, office_shell in representative_routes:
                response = page.goto(base + path, wait_until="domcontentloaded")
                assert response is None or response.status == 200, f"{browser_name} route failed at {width}x{height}: {path}"
                # Adaptive mode may navigate again after DOMContentLoaded.
                # Wait for the final Office document rather than measuring an
                # empty intermediate document during Firefox's redirect.
                if office_shell:
                    page.wait_for_load_state("networkidle")
                    page.locator('main#fm-main-content').wait_for(state='visible')
                else:
                    page.wait_for_timeout(40)
                assert_layout_contract(page, f"{browser_name} {width}x{height} {path}", office_shell=office_shell)
                assert not page_errors, f"{browser_name} page errors at {width}x{height} {path}: {page_errors}"
                assert not console_errors, f"{browser_name} console errors at {width}x{height} {path}: {console_errors}"
                if evidence_path and browser_name == "chromium" and (width, height, path) in {
                    (320, 568, "/office/mobile?mobile=1"),
                    (390, 844, "/office/roomflow"),
                    (1024, 768, "/office/desktop?desktop=1"),
                    (1440, 900, "/office/settings"),
                    (1440, 900, "/office/settings?desktop=1"),
                }:
                    slug = re.sub(r"[^a-z0-9]+", "-", path.lower()).strip("-") or "root"
                    page.screenshot(path=evidence_path / f"{browser_name}-{width}x{height}-{slug}.png", full_page=True, animations="disabled")

        context.close()
        browser.close()

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(viewport={"width": 1024, "height": 768}, service_workers="block")
    page = context.new_page()
    authenticate_browser_page(page, base)
    page.goto(base + "/office/desktop?desktop=1", wait_until="domcontentloaded")
    for width, height in TRANSITION_VIEWPORTS:
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_timeout(40)
        assert_layout_contract(page, f"chromium transition {width}x{height}", office_shell=True)
        menu_visible = page.locator(".mobile-topbar").is_visible()
        sidebar_hidden = page.locator("#fm-office-sidebar").get_attribute("aria-hidden") == "true"
        assert menu_visible == (width <= 1100), f"navigation transition mismatch at {width}px"
        assert sidebar_hidden == (width <= 1100), f"sidebar accessibility transition mismatch at {width}px"

    page.set_viewport_size({"width": 1024, "height": 768})
    trigger = page.locator(".mobile-topbar [data-mobile-menu]")
    trigger.click()
    assert page.locator("#fm-office-sidebar").get_attribute("aria-hidden") == "false"
    assert page.locator("#fm-office-sidebar").get_attribute("inert") is None
    page.keyboard.press("Escape")
    assert trigger.evaluate("node => node === document.activeElement"), "Office drawer did not restore trigger focus"

    context.close()
    context = browser.new_context(viewport={"width": 1024, "height": 768})
    page = context.new_page()
    authenticate_browser_page(page, base)
    page.goto(base + "/office/desktop?desktop=1", wait_until="domcontentloaded")
    page.evaluate("navigator.serviceWorker.ready")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_function("Boolean(navigator.serviceWorker.controller)")
    cached_paths = page.evaluate("""async () => (await Promise.all((await caches.keys()).map(async name =>
      (await (await caches.open(name)).keys()).map(request => new URL(request.url).pathname)
    ))).flat()""")
    assert "/workspace" not in cached_paths and "/full-erp" not in cached_paths
    assert not any(path.startswith("/office/") for path in cached_paths), f"private Office page entered PWA cache: {cached_paths}"
    workers = context.service_workers
    assert workers, "PWA service worker did not start"
    offline_cache = workers[0].evaluate("""async () => { const response = await caches.match('/floodman-offline.html'); return response ? {status: response.status, text: await response.text()} : null; }""")
    assert offline_cache and offline_cache["status"] == 200 and "Floodman is offline" in offline_cache["text"], f"offline cache missing: caches={cached_paths} response={offline_cache}"
    context.set_offline(True)
    page.goto(base + "/office/settings", wait_until="domcontentloaded")
    assert page.get_by_role("heading", name="Floodman is offline").is_visible()
    context.set_offline(False)
    page.goto(base + "/floodman-offline.html", wait_until="domcontentloaded")
    assert page.get_by_role("heading", name="Floodman is offline").is_visible()

    standalone = browser.new_context(viewport={"width": 390, "height": 844})
    standalone.add_init_script("""(() => { const original = window.matchMedia.bind(window); window.matchMedia = query => query === '(display-mode: standalone)' ? {matches:true,media:query,onchange:null,addListener(){},removeListener(){},addEventListener(){},removeEventListener(){},dispatchEvent(){return true}} : original(query); })();""")
    standalone_page = standalone.new_page()
    authenticate_browser_page(standalone_page, base)
    standalone_page.goto(base + "/office/mobile?mobile=1", wait_until="domcontentloaded")
    assert standalone_page.locator("html.fm-pwa-standalone").count() == 1
    assert_layout_contract(standalone_page, "chromium PWA standalone 390x844", office_shell=True)
    standalone.close()

    reflow = browser.new_context(viewport={"width": 640, "height": 450}, device_scale_factor=2, service_workers="block")
    reflow_page = reflow.new_page()
    authenticate_browser_page(reflow_page, base)
    for path in ("/office/settings?desktop=1", "/office/estimates/new?desktop=1", "/office/roomflow?desktop=1"):
        reflow_page.goto(base + path, wait_until="domcontentloaded")
        assert_layout_contract(reflow_page, f"chromium 200-percent reflow proxy {path}", office_shell=True)
    reflow_page.goto(base + "/office/settings?mobile=1", wait_until="domcontentloaded")
    reflow_page.locator(".card").first.evaluate("node => node.prepend('L' .repeat(512))")
    assert_layout_contract(reflow_page, "chromium long unbroken content", office_shell=True)
    reflow.close()

    keyboard = browser.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
    keyboard_page = keyboard.new_page()
    authenticate_browser_page(keyboard_page, base)
    keyboard_page.goto(base + "/office/estimates/new?mobile=1", wait_until="domcontentloaded")
    keyboard_page.set_viewport_size({"width": 390, "height": 480})
    keyboard_field = keyboard_page.locator("input:not([type='hidden']),textarea").last
    keyboard_field.evaluate("node => { node.focus(); node.scrollIntoView({block:'nearest'}); }")
    keyboard_page.wait_for_timeout(100)
    keyboard_bounds = keyboard_field.evaluate("""node => {
      const rect = node.getBoundingClientRect();
      const nav = document.querySelector('.mobile-bottom-nav');
      const navRect = nav && getComputedStyle(nav).display !== 'none' ? nav.getBoundingClientRect() : null;
      return {top: rect.top, bottom: rect.bottom, viewport: innerHeight, navTop: navRect ? navRect.top : innerHeight};
    }""")
    assert keyboard_bounds["top"] >= 0 and keyboard_bounds["bottom"] <= keyboard_bounds["navTop"] + 1, f"focused field is obscured by virtual-keyboard layout: {keyboard_bounds}"
    assert_layout_contract(keyboard_page, "chromium virtual keyboard 390x480", office_shell=True)
    keyboard.close()

    accessibility = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
    accessibility_page = accessibility.new_page()
    authenticate_browser_page(accessibility_page, base)
    accessibility_page.goto(base + "/office/settings?desktop=1", wait_until="domcontentloaded")
    accessibility_page.evaluate("document.activeElement?.blur()")
    accessibility_page.keyboard.press("Tab")
    assert accessibility_page.locator("a.skip-link").evaluate("node => node === document.activeElement"), "skip link is not the first keyboard stop"
    accessibility_page.keyboard.press("Enter")
    assert accessibility_page.locator("#fm-main-content").evaluate("node => node === document.activeElement"), "skip link did not move focus to main content"
    accessibility_page.emulate_media(reduced_motion="reduce", forced_colors="active")
    accessibility_page.reload(wait_until="domcontentloaded")
    assert_layout_contract(accessibility_page, "chromium reduced motion and forced colors", office_shell=True)
    accessibility.close()
    context.close()
    browser.close()


def browser_smoke(main: Any) -> None:
    executable = browser_executable()
    if not executable:
        print("Browser UI smoke skipped: no local Chromium-family executable")
        return

    import uvicorn
    from playwright.sync_api import sync_playwright

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(build_browser_app(main), host="127.0.0.1", port=port, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "Browser fixture server did not start"
    base = f"http://127.0.0.1:{port}"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=executable, headless=True)
            desktop = browser.new_context(viewport={"width": 1440, "height": 900})
            page = desktop.new_page()
            page.goto(base + "/login/local?next=/office/desktop")
            form = page.locator("form[action='/login']")
            form.locator("input[name='email']").fill("owner@example.test")
            form.locator("input[name='password']").fill("Floodman-Test-2026!")
            form.locator("button").click()
            page.wait_for_url(re.compile(r"/office/desktop"))
            call_drawer = page.locator("#fm-call-intake-drawer")
            call_drawer.wait_for(state="visible", timeout=5_000)
            assert call_drawer.get_by_text("Alex Carter").is_visible()
            call_drawer.locator("[data-call-intake-dismiss]").click()
            assert call_drawer.is_hidden(), "dismissible call card stayed open"
            queue_response = page.goto(base + "/office/calls", wait_until="domcontentloaded")
            assert queue_response and queue_response.status == 200
            assert page.get_by_text("Alex Carter").first.is_visible(), "dismissed call disappeared from its durable queue"

            desktop_pages = [
                "/setup", "/office/desktop?desktop=1", "/office/apps", "/office/settings", "/office/linking", "/office/imports",
                "/office/contacts", "/office/properties", "/office/catalog", "/office/estimates",
                "/office/estimates/new", "/office/invoices", "/office/payments", "/office/payment-settings",
                "/office/documents", "/office/tasks", "/office/notes", "/office/time", "/office/members", "/office/calls",
                "/office/messages", "/office/receivables", "/office/intelligence", "/office/alerts",
                "/office/platform", "/office/signing", "/office/roomflow", "/office/roomflow/import",
            ]
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            for path in desktop_pages:
                response = page.goto(base + path, wait_until="domcontentloaded")
                assert response and response.status == 200, f"desktop browser route failed: {path}"
                assert not page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"), f"desktop horizontal overflow: {path}"

            page.goto(base + "/office/properties", wait_until="domcontentloaded")
            assert page.get_by_role("heading", name="Choose a customer to begin").is_visible()
            assert page.get_by_text("Carter Residence").count() == 0
            assert page.get_by_text("Vale Warehouse").count() == 0
            alex_contact = next(item for item in main.store.records("contacts") if item.get("name") == "Alex Carter")
            page.goto(base + f"/office/properties?contact_id={alex_contact['id']}", wait_until="domcontentloaded")
            assert page.get_by_text("Carter Residence").is_visible()
            assert page.get_by_text("Vale Warehouse").count() == 0
            page.goto(base + "/office/desktop?desktop=1", wait_until="domcontentloaded")
            assert page.locator(".sidebar-more:not([open])").count() == 1

            page.goto(base + "/office/desktop?desktop=1", wait_until="domcontentloaded")
            page.evaluate("window.dispatchEvent(new Event('appinstalled'))")
            toast = page.locator("#fm-pwa-toast")
            toast.wait_for(state="visible")
            toast.locator(".fm-pwa-toast-dismiss").click()
            assert not toast.evaluate("node => node.classList.contains('is-visible')")

            hub_response = page.goto(base + "/hub-fixture", wait_until="domcontentloaded")
            page.wait_for_timeout(250)
            assert hub_response and hub_response.status == 200
            assert page.locator(".fm-hub-trigger").count() == 1, f"hub shell did not load: {errors}; {page.content()[:500]}"
            page.locator(".fm-hub-trigger").click()
            assert page.locator(".fm-hub-drawer").get_attribute("aria-hidden") == "false"
            page.keyboard.press("Escape")
            assert page.locator(".fm-hub-drawer").get_attribute("aria-hidden") == "true"
            page.locator(".fm-hub-trigger").click()
            page.get_by_role("button", name=re.compile("Floodman RoomFlow Estimator")).click()
            assert page.locator(".fm-hub-overlay").get_attribute("aria-hidden") == "false"
            page.locator(".fm-hub-overlay-close").click()
            assert page.locator(".fm-hub-overlay").get_attribute("aria-hidden") == "true"

            page.goto(base + "/roomflow/", wait_until="domcontentloaded")
            panel = page.locator("#fm-roomflow-panel")
            panel.wait_for(state="visible")
            capture_launch = page.locator("#fm-capture-launch")
            capture_launch.wait_for(state="visible")
            capture_launch.click()
            capture_dialog = page.locator("#fm-capture-dialog")
            capture_dialog.wait_for(state="visible")
            page.get_by_role("button", name="Enter room manually").click()
            page.locator("#fm-capture-manual-form input[name='name']").fill("Basement Recreation Room")
            page.locator("#fm-capture-next").click()
            assert "120 sq ft" in capture_dialog.inner_text()
            assert "44 ft" in capture_dialog.inner_text()
            first_wall = page.locator("[data-wall-length='0']")
            first_wall.fill("11")
            first_wall.press("Tab")
            page.get_by_role("button", name="Undo").click()
            assert "120 sq ft" in capture_dialog.inner_text()
            page.get_by_role("button", name="Redo").click()
            page.locator("#fm-capture-opening-form button[type='submit']").click()
            assert "door · wall 1" in capture_dialog.inner_text().lower()
            page.locator("#fm-capture-opening-form select[name='type']").select_option("window")
            page.locator("#fm-capture-opening-form input[name='width']").fill("2")
            page.locator("#fm-capture-opening-form input[name='openingHeight']").fill("2")
            page.locator("#fm-capture-opening-form input[name='sillHeight']").fill("3")
            page.locator("#fm-capture-opening-form button[type='submit']").click()
            assert "window · wall 1" in capture_dialog.inner_text().lower()
            page.locator("#fm-capture-next").click()
            page.locator("#fm-capture-affected-form input[name='floor']").check()
            page.locator("#fm-capture-affected-form input[name='wall']").first.check()
            quantities = page.evaluate("window.RoomFlowCapture.estimateQuantities(window.RoomFlowCapture.state.room)")
            assert quantities["floorSquareFeet"] > 0 and quantities["wallSquareFeet"] > 0
            cost = page.evaluate("window.RoomFlowCapture.calculateCost(window.RoomFlowCapture.state.room,{floorPerSquareFoot:2.5,wallPerSquareFoot:1.25})")
            assert cost["total"] > 0 and cost["lines"][0]["unit"] == "SF"
            page.locator("#fm-capture-next").click()
            page.wait_for_timeout(750)
            assert page.get_by_text("is saved.").is_visible(), f"capture save did not complete: {capture_dialog.inner_text()}; browser errors: {errors}"
            page.get_by_role("button", name="Done").click()
            assert capture_dialog.is_hidden()

            page.reload(wait_until="domcontentloaded")
            page.locator("#fm-capture-launch").wait_for(state="visible")
            page.locator("#fm-capture-launch").click()
            page.get_by_text("Basement Recreation Room").wait_for(state="visible")
            page.locator("#fm-capture-close").click()

            page.evaluate("""window.__captureBridgeMessages=[]; window.RoomFlowNativeBridge={postMessage(message){const envelope=typeof message==='string'?JSON.parse(message):message; window.__captureBridgeMessages.push(envelope); let payload={}; let type='sessionCompleted'; if(envelope.type==='capabilitiesRequested'){type='capabilitiesReported';payload={supported:true,modes:['android-arcore-guided','manual'],preferredMode:'android-arcore-guided',depthSupported:false,provider:'test'};} if(envelope.type==='captureRoomsRequested'){type='captureRoomsReported';payload={items:[]};} if(envelope.type==='captureOutboxReplayRequested'){type='captureOutboxReplayed';payload={complete:true,results:[]};} if(envelope.type==='roomCaptureStarted'){type='roomCaptureCompleted';payload={schemaVersion:2,sessionId:envelope.sessionId,jobId:envelope.payload.jobId,workspaceId:envelope.payload.workspaceId,levelId:envelope.payload.levelId,roomId:'bridge-room',name:envelope.payload.name,roomType:envelope.payload.roomType,units:'ft',height:8,vertices:[{id:'1',x:0,y:0,confidence:.8,depthValidated:false,source:'android-arcore-guided'},{id:'2',x:8,y:0,confidence:.8,depthValidated:false,source:'android-arcore-guided'},{id:'3',x:8,y:5,confidence:.8,depthValidated:false,source:'android-arcore-guided'},{id:'4',x:0,y:5,confidence:.8,depthValidated:false,source:'android-arcore-guided'}],openings:[],affectedAreas:[],scanMetadata:{captureMode:'android-arcore-guided',platform:'android',pointCount:4,averageConfidence:.8,depthValidatedPointCount:0,automaticCorrectionCount:0,manualCorrectionCount:0,verificationRequired:true,rawCaptureRetained:false}};} setTimeout(()=>window.RoomFlowCaptureBridgeV2.receive({version:2,sessionId:envelope.sessionId,type,requestId:envelope.requestId,ok:true,payload}),0);}}""")
            page.locator("#fm-capture-launch").click()
            page.get_by_role("button", name="Scan room with this device").wait_for(state="visible")
            page.get_by_role("button", name="Scan room with this device").click()
            page.locator("#fm-capture-prescan-form input[name='name']").fill("Bridge Capture Room")
            page.get_by_role("button", name="Start scanner").click()
            page.get_by_text("40 sq ft").first.wait_for(state="visible")
            bridge_envelope = page.evaluate("window.__captureBridgeMessages.find(value=>value.type==='roomCaptureStarted')")
            assert bridge_envelope["version"] == 2 and bridge_envelope["sessionId"] and bridge_envelope["payload"]["jobId"] == "browser-capture-job"
            page.locator("#fm-capture-close").click()
            page.evaluate("delete window.RoomFlowNativeBridge; localStorage.removeItem('floodman_roomflow_capture_draft_v2')")

            page.locator("#fm-capture-launch").click()
            page.evaluate("""window.RoomFlowCapture.acceptNativeResult({captureMode:'simulated-native',room:{units:'ft',roomId:'simulated-native-room',name:'Simulated Native Room',roomType:'bedroom',levelId:'main',height:8,vertices:[{x:0,y:0,confidence:.9},{x:6,y:0,confidence:.9},{x:6,y:6,confidence:.9},{x:0,y:6,confidence:.9}],openings:[],affectedAreas:[],scanMetadata:{captureMode:'simulated-native',platform:'android',pointCount:4,averageConfidence:.9,depthValidatedPointCount:0,automaticCorrectionCount:0,manualCorrectionCount:0,verificationRequired:true,rawCaptureRetained:false}}})""")
            page.get_by_text("36 sq ft").first.wait_for(state="visible")
            page.get_by_role("button", name="Compare captured plan").click()
            assert page.locator(".fm-capture-plan polygon.original").count() == 1
            page.locator("[data-lock-wall='0']").check()
            assert page.locator("[data-wall-length='0']").is_disabled()
            page.locator("[data-lock-wall='0']").uncheck()
            page.locator("[data-add-vertex='0']").click()
            assert page.locator("[data-plan-vertex]").count() == 5
            page.get_by_role("button", name="Undo").click()
            assert page.locator("[data-plan-vertex]").count() == 4
            page.locator("#fm-capture-close").click()

            page.locator("#fm-capture-launch").click()
            page.get_by_text("Recovered an unsaved room from this device").wait_for(state="visible")
            page.locator("#fm-capture-close").click()
            page.evaluate("localStorage.removeItem('floodman_roomflow_capture_draft_v2')")
            page.locator("#fm-capture-launch").click()
            page.get_by_role("button", name="Enter room manually").click()
            page.locator("#fm-capture-shape").select_option("l-shape")
            page.locator("#fm-capture-manual-form input[name='length']").fill("10")
            page.locator("#fm-capture-next").click()
            page.get_by_text("75 sq ft").first.wait_for(state="visible")
            page.locator("#fm-capture-close").click()

            page.locator("#more-new-company-name").fill("Browser RoomFlow Company")
            page.locator("#btn-more-create-company").click()
            page.wait_for_function("document.querySelector('#more-company-switcher')?.value && document.querySelector('#more-company-switcher')?.selectedOptions[0]?.textContent === 'Browser RoomFlow Company'")
            assert page.evaluate("window.__legacyAccountPrompted") is False
            assert page.locator("#auth-overlay").evaluate("node => getComputedStyle(node).display") == "none"
            assert "No separate RoomFlow account is needed" in page.locator("#more-company-switcher").locator("xpath=ancestor::*[contains(@class,'checklist-room-card')][1]").inner_text()
            guide = page.locator("#fm-rf-quick-start")
            assert guide.is_visible()
            page.locator("#fm-rf-guide-close").click()
            assert guide.is_hidden()
            page.locator("#fm-rf-help").click()
            assert guide.is_visible()
            assert page.locator(".fm-rf-details:not([open])").count() >= 3
            page.locator("#fm-rf-close-panel").click()
            assert page.locator("html").evaluate("node => node.classList.contains('fm-rf-panel-dismissed')")
            assert panel.get_attribute("aria-hidden") == "true"
            page.locator("#fm-rf-open-panel").click()
            assert panel.get_attribute("aria-hidden") == "false"
            page.keyboard.press("Escape")
            assert panel.get_attribute("aria-hidden") == "true"

            page.goto(base + "/legacy-roomflow?floodmanPanel=1", wait_until="domcontentloaded")
            page.locator("#fmrf-open").click()
            modal = page.locator("#fmrf-modal")
            modal.wait_for(state="visible")
            page.keyboard.press("Escape")
            assert modal.get_attribute("aria-hidden") == "true"
            page.locator("#fmrf-open").click()
            page.locator("#fmrf-close-icon").click()
            assert modal.get_attribute("aria-hidden") == "true"

            mobile_page = desktop.new_page()
            mobile_page.set_viewport_size({"width": 390, "height": 844})
            mobile_page.goto(base + "/office/mobile?mobile=1", wait_until="domcontentloaded")
            mobile_page.locator("[data-mobile-menu]").first.click()
            sidebar = mobile_page.locator("#fm-office-sidebar")
            assert sidebar.get_attribute("aria-hidden") == "false"
            mobile_page.keyboard.press("Escape")
            assert sidebar.get_attribute("aria-hidden") == "true"
            for path in ["/office/mobile?mobile=1", "/office/settings", "/office/contacts", "/office/properties", "/office/estimates", "/office/invoices", "/office/roomflow", "/office/roomflow/import"]:
                response = mobile_page.goto(base + path, wait_until="domcontentloaded")
                assert response and response.status == 200, f"mobile browser route failed: {path}"
                assert not mobile_page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"), f"mobile horizontal overflow: {path}"

            mobile_page.goto(base + "/roomflow/", wait_until="domcontentloaded")
            mobile_page.locator("#fm-rf-help").click()
            assert mobile_page.locator("#fm-roomflow-panel").get_attribute("aria-hidden") == "false"
            assert mobile_page.locator("#fm-rf-quick-start").is_visible()
            assert not mobile_page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"), "mobile RoomFlow horizontal overflow"
            mobile_page.locator("#fm-rf-close-panel").click()
            assert mobile_page.locator("#fm-roomflow-panel").get_attribute("aria-hidden") == "true"

            for width in (320, 360, 390, 430):
                mobile_page.set_viewport_size({"width": width, "height": 844})
                mobile_page.goto(base + "/roomflow/", wait_until="domcontentloaded")
                mobile_page.locator("#fm-capture-launch").wait_for(state="visible")
                mobile_page.locator("#fm-capture-launch").click()
                mobile_dialog = mobile_page.locator("#fm-capture-dialog")
                mobile_dialog.wait_for(state="visible")
                assert mobile_page.locator("#fm-capture-close").is_visible(), f"capture close is hidden at {width}px"
                assert mobile_dialog.evaluate("node => node.scrollWidth <= node.clientWidth + 2"), f"capture dialog overflow at {width}px"
                mobile_page.keyboard.press("Escape")
                assert mobile_dialog.is_hidden(), f"capture dialog did not close at {width}px"

            portal_invoice = next(item for item in main.store.records("invoices") if item.get("invoice_number") == "INV-UI-001")
            for width in (320, 390):
                mobile_page.set_viewport_size({"width": width, "height": 844})
                portal_response = mobile_page.goto(
                    base + f"/customer/invoice/{portal_invoice['public_token']}#messages",
                    wait_until="domcontentloaded",
                )
                assert portal_response is None or portal_response.status == 200, f"customer portal returned {portal_response.status} at {width}px: {mobile_page.content()[:300]}"
                assert mobile_page.get_by_role("heading", name="Message the Floodman team").is_visible()
                assert mobile_page.locator("#portal-message-body").is_visible()
                overflow = mobile_page.evaluate("""Array.from(document.querySelectorAll('body *')).filter(node=>{const r=node.getBoundingClientRect();return r.right>document.documentElement.clientWidth+2||r.left<-2}).slice(0,12).map(node=>({tag:node.tagName,className:node.className,text:(node.textContent||'').trim().slice(0,80),left:node.getBoundingClientRect().left,right:node.getBoundingClientRect().right,scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}))""")
                assert not overflow, f"customer portal horizontal overflow at {width}px: {overflow}"

            layout_browser_matrix(playwright, base, portal_invoice["public_token"])
            mobile_page.close()
            desktop.close()
            browser.close()
            assert not errors, f"browser page errors: {errors}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def run() -> None:
    static_overlay_contracts()
    with tempfile.TemporaryDirectory() as temp:
        os.environ["OFFICE_CONSOLE_DATA_DIR"] = str(Path(temp) / "office")
        os.environ["DOCUMENTS_PATH"] = str(Path(temp) / "documents")
        os.environ["OFFICE_CONSOLE_PUBLIC_URL"] = "http://127.0.0.1"
        os.environ["FLOODMAN_CUSTOMER_PUBLIC_URL"] = "http://127.0.0.1/customer"
        os.environ["OFFICE_SESSION_COOKIE_SECURE"] = "false"
        os.environ["INTERNAL_HMAC_KEYS"] = "v1:MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE="
        os.environ["AI_HMAC_KEYS"] = "ai-v1:MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjI="
        from app import main

        main.providers = FakeProviders()
        records = seed(main)
        route_smoke(main, records)
        browser_smoke(main)
    print("Floodman web routes, responsive layouts, and dismissible overlay smoke test passed")


if __name__ == "__main__":
    run()
