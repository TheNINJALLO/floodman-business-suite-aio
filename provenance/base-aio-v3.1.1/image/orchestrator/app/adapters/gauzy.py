from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import httpx

from ..config import Settings
from .http import ProviderError, request_json


class GauzyClient:
    """Narrow Ever Gauzy adapter used only for contacts, estimates, invoices and payments."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.gauzy_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=settings.gauzy_verify_tls,
            headers={"accept": "application/json"},
        )
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._login_payload: dict[str, Any] = {}
        self._resolved_context: tuple[str, str, str] | None = None

    def close(self) -> None:
        self.client.close()

    def _authenticate(self) -> str:
        response = request_json(
            self.client,
            "gauzy",
            "POST",
            self.settings.gauzy_login_path,
            json={"email": self.settings.gauzy_email, "password": self.settings.gauzy_password},
        )
        token = (
            response.get("token")
            or response.get("access_token")
            or response.get("accessToken")
            or (response.get("data") or {}).get("token")
        )
        if not token:
            raise ProviderError("gauzy", "login response did not contain an access token", details=response)
        self._login_payload = dict(response)
        self._token = str(token)
        self._token_expires_at = time.time() + 15 * 60
        return self._token

    def _headers(self) -> dict[str, str]:
        token = self._token if self._token and self._token_expires_at > time.time() else self._authenticate()
        return {"authorization": f"Bearer {token}", "content-type": "application/json"}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        kwargs.setdefault("headers", self._headers())
        try:
            return request_json(self.client, "gauzy", method, path, **kwargs)
        except ProviderError as exc:
            if exc.status_code == 401:
                self._token = None
                kwargs["headers"] = self._headers()
                return request_json(self.client, "gauzy", method, path, **kwargs)
            raise

    @staticmethod
    def _items(response: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
        if isinstance(response, list):
            values = response
        else:
            values = response.get("items") or response.get("data") or []
        return [dict(value) for value in values] if isinstance(values, list) else []

    @staticmethod
    def _configured_id(value: str | None) -> str:
        candidate = str(value or "").strip()
        return "" if candidate.upper() in {"", "AUTO", "DISCOVER"} else candidate

    @staticmethod
    def _nested_id(value: Any, *paths: tuple[str, ...]) -> str:
        for path in paths:
            current = value
            for key in path:
                if not isinstance(current, dict):
                    current = None
                    break
                current = current.get(key)
            if current:
                return str(current)
        return ""

    def _context(self) -> tuple[str, str, str]:
        if self._resolved_context is not None:
            return self._resolved_context

        tenant_id = self._configured_id(self.settings.gauzy_tenant_id)
        organization_id = self._configured_id(self.settings.gauzy_organization_id)
        from_organization_id = self._configured_id(self.settings.gauzy_from_organization_id)

        if (not tenant_id or not organization_id) and not self.settings.gauzy_auto_discover_context:
            raise ProviderError(
                "gauzy",
                "tenant and organization IDs are required when GAUZY_AUTO_DISCOVER_CONTEXT is false",
            )

        # Authenticate first so the login payload can contribute tenant context.
        self._headers()
        login = self._login_payload
        user = login.get("user") or (login.get("data") or {}).get("user") or {}
        tenant_id = tenant_id or self._nested_id(
            login,
            ("tenantId",), ("tenant", "id"), ("user", "tenantId"), ("user", "tenant", "id"),
            ("data", "tenantId"), ("data", "tenant", "id"),
        )

        try:
            me = self._request(
                "GET",
                "/user/me",
                params={"relations": "employee,tenant", "includeEmployee": "true"},
            )
            user = me or user
            tenant_id = tenant_id or self._nested_id(me, ("tenantId",), ("tenant", "id"))
            employee = me.get("employee") or {} if isinstance(me, dict) else {}
            organization_id = organization_id or self._nested_id(
                me,
                ("organizationId",), ("organization", "id"), ("employee", "organizationId"),
                ("employee", "organization", "id"),
            )
            if not organization_id and isinstance(employee, dict):
                organization_id = str(employee.get("organizationId") or "")
        except ProviderError as exc:
            if exc.status_code not in {400, 403, 404}:
                raise

        if not tenant_id:
            tenant_id = self._nested_id(user, ("tenantId",), ("tenant", "id"))

        if not organization_id:
            params: dict[str, Any] = {}
            if tenant_id:
                params["tenantId"] = tenant_id
            try:
                organizations_response = self._request("GET", "/organization/", params=params)
                organizations = self._items(organizations_response)
                if organizations:
                    organization_id = str(organizations[0].get("id") or "")
                    tenant_id = tenant_id or str(organizations[0].get("tenantId") or "")
            except ProviderError as exc:
                if exc.status_code not in {400, 403, 404}:
                    raise

        if not tenant_id or not organization_id:
            raise ProviderError(
                "gauzy",
                "could not discover the Gauzy tenant and organization; open Gauzy, create/select the Floodman organization, then retry",
                details={
                    "tenant_id": tenant_id,
                    "organization_id": organization_id,
                    "login_user": user,
                },
            )

        from_organization_id = from_organization_id or organization_id
        self._resolved_context = (tenant_id, organization_id, from_organization_id)
        return self._resolved_context

    @property
    def tenant_id(self) -> str:
        return self._context()[0]

    @property
    def organization_id(self) -> str:
        return self._context()[1]

    @property
    def from_organization_id(self) -> str:
        return self._context()[2]

    def healthcheck(self) -> bool:
        self._context()
        return True

    def find_contact(self, email: str) -> dict[str, Any] | None:
        data = {
            "relations": [],
            "findInput": {
                "tenantId": self.tenant_id,
                "organizationId": self.organization_id,
                "primaryEmail": email,
            },
        }
        response = self._request("GET", self.settings.gauzy_contact_path + "/", params={"data": json.dumps(data)})
        return next(
            (item for item in self._items(response) if str(item.get("primaryEmail", "")).lower() == email.lower()),
            None,
        )

    def ensure_contact(self, customer: dict[str, Any], property_data: dict[str, Any]) -> dict[str, Any]:
        existing = self.find_contact(customer["email"])
        if existing:
            return existing
        address = property_data.get("service_address", {})
        notes = (
            "Floodman customer synchronized from RoomFlow. "
            f"Primary service property: {address.get('street','')}, {address.get('city','')}, "
            f"{address.get('state','')} {address.get('postal_code','')}"
        )
        payload = {
            "tenantId": self.tenant_id,
            "organizationId": self.organization_id,
            "name": f"{customer['first_name']} {customer['last_name']}",
            "primaryEmail": customer["email"],
            "primaryPhone": customer["phone"],
            "contactType": "CLIENT",
            "notes": notes,
            "tags": [],
        }
        return self._request("POST", self.settings.gauzy_contact_path + "/", json=payload)

    @staticmethod
    def _property_project_code(job: dict[str, Any]) -> str:
        raw = str(job.get("roomflow_job_id") or job.get("id") or "property")
        safe = "".join(char for char in raw.upper() if char.isalnum())
        return f"RF-{safe[-24:] or 'PROPERTY'}"

    def find_property_project(self, code: str) -> dict[str, Any] | None:
        if not self.settings.gauzy_create_property_projects:
            return None
        try:
            response = self._request(
                "GET",
                self.settings.gauzy_project_path + "/",
                params={
                    "tenantId": self.tenant_id,
                    "organizationId": self.organization_id,
                    "take": 250,
                },
            )
        except ProviderError as exc:
            if exc.status_code in {400, 403, 404}:
                return None
            raise
        return next((item for item in self._items(response) if str(item.get("code") or "") == code), None)

    def ensure_property_project(
        self,
        job: dict[str, Any],
        *,
        contact_id: str,
    ) -> dict[str, Any] | None:
        """Create one Gauzy project per RoomFlow job/property when the API permits it.

        Gauzy projects give the service property a native home for tasks, employee time,
        invoice items, payments, expenses, and reports. The workflow remains usable if a
        Gauzy deployment disables project creation; callers may continue with a contact-only
        mapping and surface the project warning for review.
        """
        if not self.settings.gauzy_create_property_projects:
            return None
        code = self._property_project_code(job)
        existing = self.find_property_project(code)
        if existing:
            return existing

        property_data = job.get("property") or {}
        address = property_data.get("service_address") or {}
        address_line = ", ".join(
            filter(
                None,
                [
                    str(address.get("street") or "").strip(),
                    str(address.get("city") or "").strip(),
                    " ".join(
                        filter(
                            None,
                            [str(address.get("state") or "").strip(), str(address.get("postal_code") or "").strip()],
                        )
                    ).strip(),
                ],
            )
        )
        customer = job.get("customer") or {}
        customer_name = " ".join(
            filter(None, [str(customer.get("first_name") or "").strip(), str(customer.get("last_name") or "").strip()])
        ).strip()
        project_name = address_line or f"{customer_name or 'Floodman customer'} property"
        payload = {
            "tenantId": self.tenant_id,
            "organizationId": self.organization_id,
            "name": project_name[:255],
            "code": code,
            "description": (
                f"Floodman service property synchronized from RoomFlow. "
                f"RoomFlow job: {job.get('roomflow_job_id')}. Customer: {customer_name}."
            )[:5000],
            "organizationContactId": contact_id,
            "billing": "FLAT_FEE",
            "budgetType": "COST",
            "currency": str(job.get("currency") or "USD").upper(),
            "status": "OPEN",
            "owner": "CLIENT",
            "public": False,
            "billable": True,
            "taskListType": "GRID",
            "projectUrl": str(getattr(self.settings, "roomflow_public_url", "") or "") or None,
        }
        return dict(self._request("POST", self.settings.gauzy_project_path + "/", json=payload))

    @staticmethod
    def _money(cents: int) -> float:
        return float((Decimal(cents) / Decimal(100)).quantize(Decimal("0.01")))

    def find_estimate(self, invoice_number: int) -> dict[str, Any] | None:
        # Gauzy supports filtering the invoice collection. We still verify every returned
        # field because deployments can differ slightly by release.
        data = {
            "relations": ["invoiceItems", "payments"],
            "findInput": {
                "tenantId": self.tenant_id,
                "organizationId": self.organization_id,
                "invoiceNumber": invoice_number,
                "isEstimate": True,
            },
        }
        try:
            response = self._request("GET", self.settings.gauzy_invoice_path, params={"data": json.dumps(data)})
        except ProviderError as exc:
            if exc.status_code in {400, 404}:
                return None
            raise
        return next(
            (
                item
                for item in self._items(response)
                if int(item.get("invoiceNumber", -1)) == int(invoice_number) and bool(item.get("isEstimate", True))
            ),
            None,
        )

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        data = {
            "relations": ["invoiceItems", "payments"],
            "findInput": {
                "tenantId": self.tenant_id,
                "organizationId": self.organization_id,
            },
        }
        return self._request(
            "GET", f"{self.settings.gauzy_invoice_path}/{invoice_id}", params={"data": json.dumps(data)}
        )

    @staticmethod
    def _cents(value: Any) -> int:
        return int((Decimal(str(value or 0)) * Decimal(100)).quantize(Decimal("1")))

    def create_estimate(self, job: dict[str, Any], contact_id: str, project_id: str | None = None) -> dict[str, Any]:
        existing = self.find_estimate(int(job["invoice_number"]))
        estimate = job["estimate"]
        existing_items: list[dict[str, Any]] | None = None
        if existing:
            invoice_id = str(existing.get("id") or "")
            if not invoice_id:
                raise ProviderError("gauzy", "existing estimate did not include id", details=existing)
            existing = self.get_invoice(invoice_id)
            if self._cents(existing.get("totalValue")) != int(job["total_cents"]):
                raise ProviderError(
                    "gauzy", "existing estimate number has a different total and requires review", details=existing
                )
            raw_items = existing.get("invoiceItems")
            if not isinstance(raw_items, list):
                raise ProviderError(
                    "gauzy", "existing estimate response did not expose invoiceItems; refusing a blind retry", details=existing
                )
            existing_items = [dict(item) for item in raw_items if isinstance(item, dict)]
            if existing_items:
                existing_total = sum(self._cents(item.get("totalValue")) for item in existing_items)
                expected_line_total = sum(int(line["line_total_cents"]) for line in estimate["lines"] )
                if len(existing_items) != len(estimate["lines"]) or existing_total != expected_line_total:
                    raise ProviderError(
                        "gauzy", "existing estimate has partial or mismatched line items and requires review", details=existing
                    )
                return existing

        now = datetime.now(UTC).date().isoformat()
        due = estimate["payment_schedule"]["deposit_due_date"]
        customer = job["customer"]
        payload = {
            "tenantId": self.tenant_id,
            "organizationId": self.organization_id,
            "fromOrganizationId": self.from_organization_id,
            "invoiceNumber": job["invoice_number"],
            "invoiceDate": now,
            "dueDate": due,
            "status": "DRAFT",
            "totalValue": self._money(job["total_cents"]),
            "currency": job["currency"],
            "paid": False,
            "terms": estimate.get("terms", ""),
            "internalNote": estimate.get("internal_note", ""),
            "organizationContactId": contact_id,
            "organizationContactName": f"{customer['first_name']} {customer['last_name']}",
            "toContactId": contact_id,
            "isEstimate": True,
            "isAccepted": False,
            "invoiceType": "DETAILED_ITEMS",
            "sentTo": customer["email"],
            "discountType": "FLAT",
            "discountValue": self._money(estimate.get("discount_cents", 0)),
            "taxType": "FLAT",
            "tax": self._money(estimate.get("tax_cents", 0)),
            "tax2Type": "FLAT",
            "tax2": 0,
            "tags": [],
        }
        if existing:
            created = existing
            invoice_id = existing["id"]
        else:
            created = self._request("POST", self.settings.gauzy_invoice_path, json=payload)
            invoice_id = created.get("id")
            if not invoice_id:
                raise ProviderError("gauzy", "estimate create response did not include id", details=created)
        items = []
        for line in estimate["lines"]:
            item = {
                "tenantId": self.tenant_id,
                "organizationId": self.organization_id,
                "invoiceId": invoice_id,
                "description": f"{line.get('name') or line.get('description') or 'Line item'}\n{line.get('description','')}".strip(),
                "price": self._money(line["unit_price_cents"]),
                "quantity": float(line["quantity"]),
                "totalValue": self._money(line["line_total_cents"]),
                "applyTax": False,
                "applyDiscount": False,
            }
            if project_id:
                item["projectId"] = project_id
            items.append(item)
        self._request("POST", f"/invoice-item/bulk/{invoice_id}", json={"list": items})
        return created

    def void_estimate(self, estimate_id: str) -> None:
        self._request("PUT", f"{self.settings.gauzy_invoice_path}/{estimate_id}/action", json={"status": "VOID"})

    def promote_estimate_to_invoice(self, estimate_id: str, *, note: str) -> dict[str, Any]:
        """Accept and convert the Gauzy estimate record into the invoice ledger record.

        Gauzy models estimates and invoices with one entity. This keeps the identifier stable,
        which prevents duplicate ledgers after webhook retries.
        """
        self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{estimate_id}/action",
            json={"status": "ACCEPTED", "isAccepted": True},
        )
        return self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{estimate_id}",
            json={
                "isEstimate": False,
                "isAccepted": True,
                "status": "DRAFT",
                "internalNote": note[:5000],
            },
        )

    def add_adjustment_line(self, invoice_id: str, *, description: str, amount_cents: int) -> None:
        self._request(
            "POST",
            f"/invoice-item/bulk/{invoice_id}",
            json={
                "list": [{
                    "tenantId": self.tenant_id,
                    "organizationId": self.organization_id,
                    "invoiceId": invoice_id,
                    "description": description[:5000],
                    "price": self._money(amount_cents),
                    "quantity": 1,
                    "totalValue": self._money(amount_cents),
                    "applyTax": False,
                    "applyDiscount": False,
                }]
            },
        )

    def update_invoice_total(self, invoice_id: str, *, total_cents: int, note: str) -> dict[str, Any]:
        return self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{invoice_id}",
            json={"totalValue": self._money(total_cents), "internalNote": note[:5000]},
        )

    def find_payment_by_marker(self, invoice_id: str, marker: str) -> dict[str, Any] | None:
        data = {
            "relations": [],
            "findInput": {
                "tenantId": self.tenant_id,
                "organizationId": self.organization_id,
                "invoiceId": invoice_id,
            },
        }
        response = self._request(
            "GET", self.settings.gauzy_payment_path + "/", params={"data": json.dumps(data)}
        )
        return next((item for item in self._items(response) if marker in str(item.get("note") or "")), None)

    def record_payment(
        self,
        *,
        invoice_id: str,
        contact_id: str,
        amount_cents: int,
        currency: str,
        payment_date: str,
        note: str,
        provider_reference: str,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        marker = f"[square:{provider_reference}]"
        existing = self.find_payment_by_marker(invoice_id, marker)
        if existing:
            return existing
        payload = {
            "tenantId": self.tenant_id,
            "organizationId": self.organization_id,
            "invoiceId": invoice_id,
            "organizationContactId": contact_id,
            "amount": self._money(amount_cents),
            "currency": currency,
            "paymentDate": payment_date,
            "paymentMethod": "ONLINE",
            "note": f"{marker} {note}"[:5000],
            "overdue": False,
            "tags": [],
        }
        if project_id:
            payload["projectId"] = project_id
        return self._request("POST", self.settings.gauzy_payment_path + "/", json=payload)

    def update_invoice_payment_status(self, invoice_id: str, *, paid_cents: int, total_cents: int) -> None:
        if paid_cents <= 0:
            status = "VIEWED"
        elif paid_cents < total_cents:
            status = "PARTIALLY_PAID"
        elif paid_cents == total_cents:
            status = "FULLY_PAID"
        else:
            status = "OVERPAID"
        self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{invoice_id}/action",
            json={
                "status": status,
                "paid": paid_cents >= total_cents,
                "alreadyPaid": self._money(paid_cents),
                "amountDue": self._money(max(0, total_cents - paid_cents)),
            },
        )

    def issue_final_invoice(self, invoice_id: str, *, due_date: str, note: str) -> dict[str, Any]:
        """Mark the Gauzy ledger invoice as sent and due upon receipt."""
        updated = self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{invoice_id}",
            json={
                "dueDate": due_date,
                "status": "SENT",
                "isEstimate": False,
                "isAccepted": True,
                "internalNote": note[:5000],
            },
        )
        self._request(
            "PUT",
            f"{self.settings.gauzy_invoice_path}/{invoice_id}/action",
            json={"status": "SENT", "paid": False},
        )
        return updated

    def generate_invoice_link(self, invoice_id: str) -> str | None:
        response = self._request("PUT", f"{self.settings.gauzy_invoice_path}/generate/{invoice_id}")
        token = response.get("token")
        if not token:
            return None
        origin = str(getattr(self.settings, "gauzy_public_url", "") or "").rstrip("/")
        return f"{origin}/#/share/invoices/{token}"
