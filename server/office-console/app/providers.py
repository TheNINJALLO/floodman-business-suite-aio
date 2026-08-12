from __future__ import annotations

import asyncio
import json
import smtplib
import uuid
from email.message import EmailMessage
from datetime import UTC, date, datetime
from typing import Any

import httpx

from .config import Settings
from .security import SignedClient


class ProviderClient:
    """Narrow provider bridge for the owner console.

    Production secrets remain outside the browser. The local Office service can
    exercise the mock workflow, inspect the real full-suite apps, and mirror
    owner-created records into the Floodman ERP-compatible local provider.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.orchestrator = SignedClient.from_key_string(settings.orchestrator_url, settings.internal_hmac_keys)
        self.competitor = SignedClient.from_key_string(settings.competitor_url, settings.ai_hmac_keys)

    async def local_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> Any:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.request(method, f"{self.settings.local_lab_url}{path}", json=payload)
        if response.is_error:
            raise RuntimeError(f"Local provider {method} {path} returned {response.status_code}: {response.text[:800]}")
        return response.json() if response.content else {}

    async def local_multipart(
        self,
        path: str,
        *,
        data: dict[str, str],
        filename: str,
        content: bytes,
        content_type: str = "application/pdf",
    ) -> Any:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.settings.local_lab_url}{path}",
                data=data,
                files={"files": (filename, content, content_type)},
            )
        if response.is_error:
            raise RuntimeError(f"Local provider POST {path} returned {response.status_code}: {response.text[:800]}")
        return response.json() if response.content else {}

    async def lab_state(self) -> dict[str, Any]:
        return dict(await self.local_request("GET", "/api/state"))

    async def _simple_status(self, url: str, *, expect_json: bool = False) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            response = await client.get(url)
        response.raise_for_status()
        result: dict[str, Any] = {"url": str(response.url), "status_code": response.status_code}
        if expect_json:
            try:
                result["body"] = response.json()
            except Exception:
                result["body"] = response.text[:200]
        return result

    async def send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        html: str | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> dict[str, Any]:
        message = EmailMessage()
        sender = self.settings.gauzy_admin_email or "office@floodman.com"
        message["From"] = f"Floodman Office <{sender}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        for filename, content, content_type in attachments or []:
            main, _, subtype = str(content_type or "application/octet-stream").partition("/")
            message.add_attachment(content, maintype=main or "application", subtype=subtype or "octet-stream", filename=filename)

        def deliver() -> None:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as client:
                client.send_message(message)

        await asyncio.to_thread(deliver)
        return {"status": "SENT", "to": to, "subject": subject, "attachments": len(attachments or [])}

    async def connection_tests(self) -> dict[str, Any]:
        async def run(name: str, function: Any) -> tuple[str, dict[str, Any]]:
            started = datetime.now(UTC)
            try:
                detail = await function()
                return name, {
                    "status": "CONNECTED",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
                    "detail": detail,
                }
            except Exception as exc:
                return name, {
                    "status": "FAILED",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
                    "detail": str(exc),
                }

        async def gauzy_real() -> Any:
            return await self.gauzy_context()

        async def square() -> Any:
            return await self.local_request("GET", f"/square/v2/locations/{self.settings.square_location_id}")

        async def documenso_mock() -> Any:
            state = await self.lab_state()
            return {"mode": "local mock", "documents": len(state.get("envelopes") or [])}

        async def twilio() -> Any:
            return await self.local_request(
                "GET", f"/twilio/2010-04-01/Accounts/{self.settings.twilio_account_sid}.json"
            )

        pairs = await asyncio.gather(
            run("orchestrator", lambda: self._simple_status(f"{self.settings.orchestrator_url}/health/ready", expect_json=True)),
            run("gauzy_workflow_bridge", gauzy_real),
            run("gauzy_full_ui", lambda: self._simple_status(self.settings.gauzy_health_url)),
            run("square", square),
            run("documenso_workflow_bridge", documenso_mock),
            run("documenso_full_ui", lambda: self._simple_status(self.settings.documenso_health_url, expect_json=True)),
            run("twilio", twilio),
            run("messaging_ai", lambda: self._simple_status(f"{self.settings.messaging_ai_url}/health/live", expect_json=True)),
            run("competitor_intelligence", lambda: self._simple_status(f"{self.settings.competitor_url}/health/ready", expect_json=True)),
            run("mailpit", lambda: self._simple_status(self.settings.mailpit_health_url)),
        )
        values = dict(pairs)
        values["smtp"] = {
            "status": "CONNECTED",
            "checked_at": datetime.now(UTC).isoformat(),
            "latency_ms": 0,
            "detail": f"Local capture at {self.settings.smtp_host}:{self.settings.smtp_port}",
        }
        values["roomflow"] = {
            "status": "READY",
            "checked_at": datetime.now(UTC).isoformat(),
            "latency_ms": 0,
            "detail": self.settings.roomflow_sync_endpoint,
        }
        return values

    # ------------------------------------------------------------------
    # Local Floodman ERP-compatible CRUD used by the unified owner UI
    # ------------------------------------------------------------------
    async def create_contact(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.local_request("POST", "/gauzy/organization-contact/", payload))

    async def create_invoice(self, payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
        invoice = dict(await self.local_request("POST", "/gauzy/invoices", payload))
        if items:
            await self.local_request("POST", f"/gauzy/invoice-item/bulk/{invoice['id']}", {"list": items})
            invoice = dict(await self.local_request("GET", f"/gauzy/invoices/{invoice['id']}"))
        return invoice

    async def update_invoice(self, invoice_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.local_request("PUT", f"/gauzy/invoices/{invoice_id}", payload))

    async def record_payment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.local_request("POST", "/gauzy/payments/", payload))

    async def create_signing_document(
        self,
        *,
        filename: str,
        content: bytes,
        title: str,
        external_id: str,
        recipient_name: str,
        recipient_email: str,
    ) -> dict[str, Any]:
        spec = {
            "title": title,
            "externalId": external_id,
            "recipients": [{"name": recipient_name, "email": recipient_email, "role": "SIGNER"}],
        }
        created = dict(await self.local_multipart(
            "/documenso/envelope/create",
            data={"payload": json.dumps(spec, separators=(",", ":"))},
            filename=filename,
            content=content,
        ))
        envelope_id = str(created.get("id") or (created.get("envelope") or {}).get("id") or "")
        if not envelope_id:
            raise RuntimeError("Signing provider did not return an envelope ID.")
        distributed = await self.local_request("POST", f"/documenso/envelope/{envelope_id}/distribute", {})
        return dict(distributed or created)

    async def get_signing_envelope(self, envelope_id: str) -> dict[str, Any]:
        return dict(await self.local_request("GET", f"/documenso/envelope/{envelope_id}"))

    async def download_signing_item(self, item_id: str) -> bytes:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(f"{self.settings.local_lab_url}/documenso/envelope/item/{item_id}/download")
        if response.is_error:
            raise RuntimeError(
                f"Floodman signing download returned {response.status_code}: {response.text[:800]}"
            )
        return bytes(response.content)

    async def send_sms(self, phone: str, body: str) -> dict[str, Any]:
        url = f"{self.settings.local_lab_url}/twilio/2010-04-01/Accounts/{self.settings.twilio_account_sid}/Messages.json"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, data={"To": phone, "Body": body, "MessagingServiceSid": "MGLOCALFLOODMAN"})
        if response.is_error:
            raise RuntimeError(f"Local Twilio simulator returned {response.status_code}: {response.text[:800]}")
        return dict(response.json())


    # ------------------------------------------------------------------
    # Square customer, card-on-file, and invoice bridge
    # ------------------------------------------------------------------
    async def square_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = 45.0,
    ) -> Any:
        headers = {
            "Square-Version": self.settings.square_version,
            "Content-Type": "application/json",
        }
        if self.settings.square_access_token:
            headers["Authorization"] = f"Bearer {self.settings.square_access_token}"
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=self.settings.square_verify_tls,
            follow_redirects=True,
        ) as client:
            response = await client.request(
                method,
                f"{self.settings.square_base_url}{path}",
                headers=headers,
                json=payload,
                params=params,
            )
        if response.is_error:
            detail = response.text[:1200]
            raise RuntimeError(f"Payment processor {method} {path} returned {response.status_code}: {detail}")
        return response.json() if response.content else {}

    async def ensure_square_customer(self, contact: dict[str, Any]) -> dict[str, Any]:
        existing_id = str(contact.get("square_customer_id") or "").strip()
        if existing_id:
            return {"id": existing_id}

        email = str(contact.get("email") or contact.get("primaryEmail") or "").strip().lower()
        phone = str(contact.get("phone") or contact.get("primaryPhone") or "").strip()
        if email:
            search = await self.square_request(
                "POST",
                "/v2/customers/search",
                {"query": {"filter": {"email_address": {"exact": email}}}, "limit": 10},
            )
            matches = list(search.get("customers") or [])
            if matches:
                return dict(matches[0])

        first_name = str(contact.get("first_name") or "").strip()
        last_name = str(contact.get("last_name") or "").strip()
        if not first_name and not last_name:
            parts = str(contact.get("name") or "").strip().split(None, 1)
            first_name = parts[0] if parts else "Customer"
            last_name = parts[1] if len(parts) > 1 else ""
        payload = {
            "idempotency_key": str(uuid.uuid4()),
            "given_name": first_name or "Customer",
            "family_name": last_name or None,
            "company_name": str(contact.get("company") or "").strip() or None,
            "email_address": email or None,
            "phone_number": phone or None,
            "reference_id": str(contact.get("id") or "") or None,
            "note": "Floodman Operations customer file",
        }
        created = await self.square_request("POST", "/v2/customers", {k: v for k, v in payload.items() if v is not None})
        customer = dict(created.get("customer") or {})
        if not customer.get("id"):
            raise RuntimeError("The payment processor did not return a customer ID.")
        return customer

    async def list_square_cards(self, customer_id: str) -> list[dict[str, Any]]:
        if not customer_id:
            return []
        value = await self.square_request("GET", "/v2/cards", params={"customer_id": customer_id})
        cards = [dict(item) for item in value.get("cards") or []]
        return [item for item in cards if bool(item.get("enabled", True))]

    async def disable_square_card(self, card_id: str) -> dict[str, Any]:
        value = await self.square_request("POST", f"/v2/cards/{card_id}/disable", {})
        return dict(value.get("card") or value)

    async def get_square_invoice(self, invoice_id: str) -> dict[str, Any]:
        value = await self.square_request("GET", f"/v2/invoices/{invoice_id}")
        return dict(value.get("invoice") or {})

    async def create_and_publish_square_invoice(
        self,
        invoice: dict[str, Any],
        contact: dict[str, Any],
        *,
        card_id: str | None = None,
        allow_customer_to_save_card: bool = True,
    ) -> dict[str, Any]:
        customer = await self.ensure_square_customer(contact)
        customer_id = str(customer.get("id") or "")
        if not customer_id:
            raise RuntimeError("The payment customer mapping is missing.")

        line_items: list[dict[str, Any]] = []
        for item in invoice.get("line_items") or []:
            quantity = item.get("quantity") or 1
            unit_amount = int(item.get("unit_price_cents") or 0)
            line_items.append({
                "name": str(item.get("description") or item.get("name") or "Floodman service")[:255],
                "quantity": str(quantity),
                "base_price_money": {"amount": unit_amount, "currency": str(invoice.get("currency") or "USD")},
                "note": str(item.get("note") or "")[:500] or None,
            })
        line_items = [{k: v for k, v in item.items() if v is not None} for item in line_items]
        order_value = await self.square_request(
            "POST",
            "/v2/orders",
            {
                "idempotency_key": str(uuid.uuid4()),
                "order": {
                    "location_id": self.settings.square_location_id,
                    "customer_id": customer_id,
                    "reference_id": str(invoice.get("id") or "")[:40],
                    "line_items": line_items,
                },
            },
        )
        order = dict(order_value.get("order") or {})
        order_id = str(order.get("id") or "")
        if not order_id:
            raise RuntimeError("The payment processor did not return an order ID.")

        automatic = bool(card_id)
        email = str(contact.get("email") or contact.get("primaryEmail") or "").strip()
        if automatic and not email:
            raise RuntimeError("Automatic card-on-file invoices require a customer email address.")
        payment_request: dict[str, Any] = {
            "request_type": "BALANCE",
            "due_date": date.today().isoformat(),
            "automatic_payment_source": "CARD_ON_FILE" if automatic else "NONE",
        }
        if automatic:
            payment_request["card_id"] = str(card_id)
        invoice_payload = {
            "location_id": self.settings.square_location_id,
            "order_id": order_id,
            "primary_recipient": {"customer_id": customer_id},
            "invoice_number": str(invoice.get("invoice_number") or "")[:20] or None,
            "delivery_method": "EMAIL" if email else "SHARE_MANUALLY",
            "payment_requests": [payment_request],
            "accepted_payment_methods": {
                "card": True,
                "square_gift_card": False,
                "bank_account": True,
                "buy_now_pay_later": False,
                "cash_app_pay": False,
            },
            "store_payment_method_enabled": bool(allow_customer_to_save_card and not automatic),
            "description": str(invoice.get("title") or "Floodman service invoice")[:1000],
        }
        invoice_payload = {k: v for k, v in invoice_payload.items() if v is not None}
        created_value = await self.square_request(
            "POST",
            "/v2/invoices",
            {"idempotency_key": str(uuid.uuid4()), "invoice": invoice_payload},
        )
        created = dict(created_value.get("invoice") or {})
        square_invoice_id = str(created.get("id") or "")
        if not square_invoice_id:
            raise RuntimeError("The payment processor did not return an invoice ID.")
        published_value = await self.square_request(
            "POST",
            f"/v2/invoices/{square_invoice_id}/publish",
            {"version": int(created.get("version") or 0), "idempotency_key": str(uuid.uuid4())},
            timeout=90.0,
        )
        published = dict(published_value.get("invoice") or {})
        return {"customer": customer, "order": order, "invoice": published or created}

    def square_payment_configuration(self) -> dict[str, Any]:
        environment = str(self.settings.square_environment or "local").lower()
        sdk_url = self.settings.square_web_sdk_url
        if not sdk_url:
            sdk_url = "https://sandbox.web.squarecdn.com/v1/square.js" if environment == "sandbox" else "https://web.squarecdn.com/v1/square.js"
        live = bool(
            self.settings.payments_enabled
            and environment in {"sandbox", "production"}
            and self.settings.square_application_id
            and self.settings.square_access_token
            and self.settings.square_location_id
        )
        return {
            "environment": environment,
            "application_id": self.settings.square_application_id,
            "location_id": self.settings.square_location_id,
            "sdk_url": sdk_url,
            "live": live,
            "local_mock": environment == "local" or self.settings.square_base_url.startswith("http://127.0.0.1"),
        }

    async def create_square_payment(
        self,
        *,
        source_id: str,
        amount_cents: int,
        currency: str,
        reference_id: str,
        note: str,
        customer_id: str | None = None,
        order_id: str | None = None,
        customer_initiated: bool = True,
        seller_keyed_in: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if amount_cents <= 0:
            raise RuntimeError("Payment amount must be greater than zero.")
        config = self.square_payment_configuration()
        if config["local_mock"]:
            return {
                "id": f"FPAY-{uuid.uuid4()}",
                "status": "COMPLETED",
                "amount_money": {"amount": int(amount_cents), "currency": currency},
                "source_type": "CARD",
                "card_details": {
                    "card": {"card_brand": "VISA", "last_4": "1111", "exp_month": 12, "exp_year": 2030},
                    "entry_method": "KEYED" if seller_keyed_in else "ON_FILE",
                },
                "receipt_url": "",
                "reference_id": reference_id,
                "note": note,
                "created_at": datetime.now(UTC).isoformat(),
                "customer_id": customer_id,
                "local_mock": True,
            }
        payload: dict[str, Any] = {
            "source_id": source_id,
            "idempotency_key": idempotency_key or str(uuid.uuid4()),
            "amount_money": {"amount": int(amount_cents), "currency": currency},
            "autocomplete": True,
            "location_id": self.settings.square_location_id,
            "reference_id": str(reference_id)[:40],
            "note": str(note)[:500],
            "customer_details": {
                "customer_initiated": bool(customer_initiated),
                "seller_keyed_in": bool(seller_keyed_in),
            },
        }
        if customer_id:
            payload["customer_id"] = customer_id
        if order_id:
            payload["order_id"] = order_id
        value = await self.square_request("POST", "/v2/payments", payload, timeout=90.0)
        payment = dict(value.get("payment") or {})
        if not payment.get("id"):
            raise RuntimeError("The payment processor did not return a payment ID.")
        if str(payment.get("status") or "").upper() not in {"COMPLETED", "APPROVED"}:
            raise RuntimeError(f"Payment was not completed. Status: {payment.get('status') or 'unknown'}")
        return payment

    async def create_square_card_from_payment(self, *, payment_id: str, customer_id: str) -> dict[str, Any]:
        if not payment_id or not customer_id:
            raise RuntimeError("Payment and customer identifiers are required to save a payment method.")
        config = self.square_payment_configuration()
        if config["local_mock"]:
            return {
                "id": f"FCARD-{uuid.uuid4()}", "customer_id": customer_id, "enabled": True,
                "card_brand": "VISA", "last_4": "1111", "exp_month": 12, "exp_year": 2030,
            }
        value = await self.square_request(
            "POST",
            "/v2/cards",
            {
                "idempotency_key": str(uuid.uuid4()),
                "source_id": payment_id,
                "card": {"customer_id": customer_id},
            },
            timeout=60.0,
        )
        card = dict(value.get("card") or {})
        if not card.get("id"):
            raise RuntimeError("The payment processor did not return a saved payment method ID.")
        return card

    async def get_square_payment(self, payment_id: str) -> dict[str, Any]:
        if not payment_id:
            return {}
        config = self.square_payment_configuration()
        if config["local_mock"]:
            return {"id": payment_id, "status": "COMPLETED"}
        value = await self.square_request("GET", f"/v2/payments/{payment_id}")
        return dict(value.get("payment") or {})

    # ------------------------------------------------------------------
    # Floodman ERP identity and synchronization bridge
    # ------------------------------------------------------------------
    async def authenticate_gauzy_member(self, email: str, password: str) -> dict[str, Any]:
        """Validate a staff login against the Floodman ERP without storing the password.

        This provides one credential set for the Floodman ERP and specialized Floodman modules. Office
        still issues its own short-lived session cookie so the upstream applications
        remain independently upgradeable.
        """
        normalized_email = str(email or "").strip().lower()
        if not normalized_email or not password:
            raise RuntimeError("Floodman ERP email and password are required.")
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.post(
                f"{self.settings.gauzy_base_url}/auth/login",
                json={"email": normalized_email, "password": password},
            )
            if response.is_error:
                raise RuntimeError("Floodman ERP did not accept that email and password.")
            login = dict(response.json() or {})
            token = str(
                login.get("token")
                or login.get("access_token")
                or login.get("accessToken")
                or (login.get("data") or {}).get("token")
                or ""
            )
            if not token:
                raise RuntimeError("Floodman ERP login succeeded but did not return an access token.")
            headers = {"Authorization": f"Bearer {token}"}
            user = dict(login.get("user") or (login.get("data") or {}).get("user") or {})
            try:
                me_response = await client.get(
                    f"{self.settings.gauzy_base_url}/user/me",
                    headers=headers,
                    params={"relations": "role,tenant", "includeEmployee": "true", "includeOrganization": "true"},
                )
                if not me_response.is_error and isinstance(me_response.json(), dict):
                    user = dict(me_response.json())
            except Exception:
                pass

        employee = user.get("employee") or {}
        role_value = user.get("role") or (employee.get("user") or {}).get("role") or login.get("role") or {}
        if isinstance(role_value, dict):
            raw_gauzy_role = str(role_value.get("name") or role_value.get("role") or "")
        else:
            raw_gauzy_role = str(role_value or "")
        gauzy_role = raw_gauzy_role.strip().upper().replace(" ", "_").replace("-", "_")
        tenant_id = str(
            user.get("tenantId")
            or (user.get("tenant") or {}).get("id")
            or login.get("tenantId")
            or (login.get("tenant") or {}).get("id")
            or ""
        )
        organization_id = str(
            employee.get("organizationId")
            or (employee.get("organization") or {}).get("id")
            or user.get("organizationId")
            or ""
        )
        expected_tenant = self._configured_gauzy_id(self.settings.gauzy_tenant_id)
        expected_organization = self._configured_gauzy_id(self.settings.gauzy_organization_id)
        actual_email = str(user.get("email") or normalized_email).strip().lower()
        configured_owner_email = str(self.settings.gauzy_admin_email or "").strip().lower()
        # Some Floodman ERP builds omit the role relation from the login payload even for
        # a verified Super Administrator. The configured installation Owner is a
        # trusted fallback only after Floodman ERP has accepted that exact email/password.
        is_admin = gauzy_role in {"SUPER_ADMIN", "ADMIN"} or (
            bool(configured_owner_email) and actual_email == configured_owner_email
        )
        if expected_tenant and tenant_id and expected_tenant != tenant_id:
            raise RuntimeError("That Floodman account belongs to another workspace.")
        if expected_organization and organization_id and expected_organization != organization_id and not is_admin:
            raise RuntimeError("That Floodman account is not assigned to the active organization.")
        if actual_email != normalized_email:
            raise RuntimeError("Floodman ERP returned a different account identity than the supplied email.")
        first_name = str(user.get("firstName") or user.get("first_name") or "").strip()
        last_name = str(user.get("lastName") or user.get("last_name") or "").strip()
        name = str(user.get("name") or " ".join(part for part in (first_name, last_name) if part) or actual_email).strip()
        suggested_role = "VIEWER"
        if is_admin:
            suggested_role = "ADMIN"
        elif "MANAGER" in gauzy_role:
            suggested_role = "OFFICE_MANAGER"
        elif gauzy_role in {"EMPLOYEE", "USER"}:
            suggested_role = "TECHNICIAN"
        return {
            "email": actual_email,
            "name": name,
            "gauzy_user_id": str(user.get("id") or ""),
            "gauzy_employee_id": str(employee.get("id") or ""),
            "gauzy_role": gauzy_role or "USER",
            "tenant_id": tenant_id,
            "organization_id": organization_id,
            "suggested_office_role": suggested_role,
            "is_gauzy_admin": is_admin,
        }

    async def _gauzy_login(self) -> tuple[str, dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.post(
                f"{self.settings.gauzy_base_url}/auth/login",
                json={"email": self.settings.gauzy_admin_email, "password": self.settings.gauzy_admin_password},
            )
        if response.is_error:
            raise RuntimeError(f"Floodman ERP login returned {response.status_code}: {response.text[:600]}")
        payload = response.json()
        token = str(
            payload.get("token")
            or payload.get("access_token")
            or payload.get("accessToken")
            or (payload.get("data") or {}).get("token")
            or ""
        )
        if not token:
            raise RuntimeError("Floodman ERP login did not return an access token.")
        return token, dict(payload)

    @staticmethod
    def _configured_gauzy_id(value: str | None) -> str:
        candidate = str(value or "").strip()
        return "" if candidate.upper() in {"", "AUTO", "DISCOVER"} else candidate

    async def gauzy_context(self) -> dict[str, Any]:
        token, login = await self._gauzy_login()
        headers = {"Authorization": f"Bearer {token}"}
        tenant_id = self._configured_gauzy_id(self.settings.gauzy_tenant_id)
        organization_id = self._configured_gauzy_id(self.settings.gauzy_organization_id)
        user: dict[str, Any] = dict(login.get("user") or (login.get("data") or {}).get("user") or {})
        tenant_id = tenant_id or str(
            login.get("tenantId")
            or (login.get("tenant") or {}).get("id")
            or user.get("tenantId")
            or (user.get("tenant") or {}).get("id")
            or ""
        )
        organizations: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            try:
                response = await client.get(
                    f"{self.settings.gauzy_base_url}/user/me",
                    headers=headers,
                    params={"relations": "role,tenant", "includeEmployee": "true", "includeOrganization": "true"},
                )
                if not response.is_error:
                    user = dict(response.json() or {})
                    tenant_id = tenant_id or str(user.get("tenantId") or (user.get("tenant") or {}).get("id") or "")
                    employee = user.get("employee") or {}
                    organization_id = organization_id or str(employee.get("organizationId") or "")
            except Exception:
                pass
            try:
                params: dict[str, str] = {}
                if tenant_id:
                    params["tenantId"] = tenant_id
                response = await client.get(f"{self.settings.gauzy_base_url}/organization/", headers=headers, params=params)
                if not response.is_error:
                    value = response.json()
                    organizations = list(value.get("items") or value if isinstance(value, list) else [])
                    if not organization_id and organizations:
                        organization_id = str(organizations[0].get("id") or "")
            except Exception:
                pass
        return {
            "connected": True,
            "user": user or login.get("user") or {},
            "tenant_id": tenant_id,
            "organization_id": organization_id,
            "from_organization_id": self._configured_gauzy_id(self.settings.gauzy_from_organization_id) or organization_id,
            "organizations": organizations,
            "sync_enabled": self.settings.gauzy_sync_enabled,
            "api_url": self.settings.gauzy_base_url,
            "web_url": self.settings.gauzy_web_url,
        }

    async def _gauzy_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        params: dict[str, Any] | None = None,
    ) -> Any:
        token, _login = await self._gauzy_login()
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.request(
                method,
                f"{self.settings.gauzy_base_url}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                params=params,
            )
        if response.is_error:
            raise RuntimeError(f"Floodman ERP {method} {path} returned {response.status_code}: {response.text[:800]}")
        return response.json() if response.content else {}

    @staticmethod
    def _provider_items(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            rows = value
        elif isinstance(value, dict):
            rows = value.get("items") or value.get("data") or []
        else:
            rows = []
        return [dict(item) for item in rows if isinstance(item, dict)]

    async def full_gauzy_find_contact(
        self, email: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        normalized = str(email or "").strip().lower()
        if not normalized:
            return None
        data = {
            "relations": [],
            "findInput": {
                "tenantId": context.get("tenant_id"),
                "organizationId": context.get("organization_id"),
                "primaryEmail": normalized,
            },
        }
        response = await self._gauzy_request(
            "GET", "/organization-contact/", params={"data": json.dumps(data)}
        )
        return next(
            (
                item
                for item in self._provider_items(response)
                if str(item.get("primaryEmail") or "").strip().lower() == normalized
            ),
            None,
        )

    async def full_gauzy_create_contact(self, record: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        tenant_id = str(context.get("tenant_id") or "")
        organization_id = str(context.get("organization_id") or "")
        if not tenant_id or not organization_id:
            raise RuntimeError("Floodman ERP tenant and organization IDs are required before synchronization.")
        existing = await self.full_gauzy_find_contact(
            str(record.get("email") or record.get("primaryEmail") or ""), context
        )
        if existing:
            return existing
        payload = {
            "tenantId": tenant_id,
            "organizationId": organization_id,
            "name": record.get("name") or " ".join(filter(None, [record.get("first_name"), record.get("last_name")])),
            "primaryEmail": record.get("email") or record.get("primaryEmail") or None,
            "primaryPhone": record.get("phone") or record.get("primaryPhone") or None,
            "notes": record.get("notes") or "",
            "contactType": "CLIENT",
        }
        return dict(await self._gauzy_request("POST", "/organization-contact/", payload))

    async def full_gauzy_find_project(
        self, code: str, context: dict[str, Any]
    ) -> dict[str, Any] | None:
        response = await self._gauzy_request(
            "GET",
            "/organization-projects/",
            params={
                "tenantId": context.get("tenant_id"),
                "organizationId": context.get("organization_id"),
                "take": 500,
            },
        )
        return next(
            (item for item in self._provider_items(response) if str(item.get("code") or "") == code),
            None,
        )

    async def full_gauzy_create_project(
        self,
        record: dict[str, Any],
        context: dict[str, Any],
        *,
        contact_id: str,
    ) -> dict[str, Any]:
        tenant_id = str(context.get("tenant_id") or "")
        organization_id = str(context.get("organization_id") or "")
        if not tenant_id or not organization_id:
            raise RuntimeError("Floodman ERP tenant and organization IDs are required before project synchronization.")
        address = ", ".join(
            part for part in [
                str(record.get("street") or record.get("service_street") or "").strip(),
                str(record.get("city") or record.get("service_city") or "").strip(),
                " ".join(
                    part for part in [str(record.get("state") or record.get("service_state") or "").strip(), str(record.get("postal_code") or record.get("service_postal_code") or "").strip()] if part
                ),
            ] if part
        )
        legacy_id = str(record.get("legacy_property_id") or record.get("legacyPropertyId") or record.get("id") or "property")
        safe_code = "".join(char for char in legacy_id.upper() if char.isalnum())
        code = f"FM-{safe_code[-24:] or 'PROPERTY'}"
        existing = await self.full_gauzy_find_project(code, context)
        if existing:
            return existing
        property_id = str(record.get("id") or record.get("legacy_property_id") or "")
        public_url = str(getattr(self.settings, "public_url", "") or "http://localhost:9000").rstrip("/")
        roomflow_url = str(
            getattr(self.settings, "roomflow_web_url", "")
            or "https://theninjallo.github.io/roomflow/"
        ).rstrip("/")
        office_property_url = (
            f"{public_url}/office/properties/{property_id}"
            if property_id else public_url
        )
        description = str(
            record.get("notes")
            or f"Floodman service property imported or created in Floodman Office. Address: {address}."
        ).strip()
        description += (
            f"\nFloodman record: {office_property_url}"
            f"\nRoomFlow estimator: {roomflow_url}"
        )
        payload = {
            "tenantId": tenant_id,
            "organizationId": organization_id,
            "name": (record.get("name") or address or "Floodman service property")[:255],
            "code": code,
            "description": description[:5000],
            "projectUrl": office_property_url,
            "organizationContactId": contact_id,
            "billing": "FLAT_FEE",
            "budgetType": "COST",
            "currency": str(record.get("currency") or "USD").upper(),
            "status": "OPEN",
            "owner": "CLIENT",
            "public": False,
            "billable": True,
            "taskListType": "GRID",
        }
        return dict(await self._gauzy_request("POST", "/organization-projects/", payload))

    async def full_gauzy_find_invoice(
        self,
        invoice_number: int,
        context: dict[str, Any],
        *,
        is_estimate: bool,
    ) -> dict[str, Any] | None:
        data = {
            "relations": ["invoiceItems", "payments"],
            "findInput": {
                "tenantId": context.get("tenant_id"),
                "organizationId": context.get("organization_id"),
                "invoiceNumber": invoice_number,
                "isEstimate": is_estimate,
            },
        }
        response = await self._gauzy_request(
            "GET", "/invoices", params={"data": json.dumps(data)}
        )
        return next(
            (
                item
                for item in self._provider_items(response)
                if int(item.get("invoiceNumber") or -1) == int(invoice_number)
                and bool(item.get("isEstimate")) is bool(is_estimate)
            ),
            None,
        )

    async def full_gauzy_create_invoice(
        self,
        record: dict[str, Any],
        context: dict[str, Any],
        *,
        contact_id: str,
        is_estimate: bool,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = str(context.get("tenant_id") or "")
        organization_id = str(context.get("organization_id") or "")
        from_organization_id = str(context.get("from_organization_id") or organization_id)
        if not tenant_id or not organization_id or not from_organization_id:
            raise RuntimeError("Floodman ERP tenant, organization, and from-organization IDs are required.")
        raw_number = str(record.get("estimate_number") or record.get("invoice_number") or "0")
        digits = "".join(char for char in raw_number if char.isdigit())
        invoice_number = int(digits[-9:] or "1")
        date_value = record.get("issued_at") or record.get("created_at") or datetime.now(UTC).isoformat()
        due_value = record.get("due_at") or date_value
        total_cents = int(record.get("total_cents") or round(float(record.get("totalValue") or 0) * 100))
        status = str(record.get("status") or "DRAFT").upper()
        if is_estimate:
            status = {
                "PAID": "ACCEPTED",
                "FULLY_PAID": "ACCEPTED",
                "PARTIALLY_PAID": "ACCEPTED",
                "OVERDUE": "SENT",
                "CANCELLED": "VOID",
            }.get(status, status)
            if status not in {"DRAFT", "SENT", "VIEWED", "ACCEPTED", "REJECTED", "VOID"}:
                status = "DRAFT"
        else:
            status = {
                "PAID": "FULLY_PAID",
                "OVERDUE": "SENT",
                "CANCELLED": "VOID",
                "REFUNDED": "VOID",
            }.get(status, status)
            if status not in {"DRAFT", "SENT", "VIEWED", "FULLY_PAID", "PARTIALLY_PAID", "OVERPAID", "VOID"}:
                status = "DRAFT"
        existing = await self.full_gauzy_find_invoice(
            invoice_number, context, is_estimate=is_estimate
        )
        if existing:
            existing_total = int(round(float(existing.get("totalValue") or 0) * 100))
            if existing_total != total_cents:
                raise RuntimeError(
                    f"Floodman ERP already has invoice number {invoice_number} with a different total"
                )
            existing_contact = str(existing.get("organizationContactId") or existing.get("toContactId") or "")
            if existing_contact and existing_contact != contact_id:
                raise RuntimeError(
                    f"Floodman ERP already has invoice number {invoice_number} for another contact"
                )
            return existing
        payload = {
            "tenantId": tenant_id,
            "organizationId": organization_id,
            "fromOrganizationId": from_organization_id,
            "invoiceNumber": invoice_number,
            "invoiceDate": date_value,
            "dueDate": due_value,
            "status": status,
            "totalValue": total_cents / 100,
            "currency": str(record.get("currency") or "USD").upper(),
            "paid": (not is_estimate) and int(record.get("balance_cents") or total_cents) == 0,
            "terms": record.get("terms") or "Payment is due upon receipt.",
            "organizationContactId": contact_id,
            "organizationContactName": record.get("contact_name") or record.get("organizationContactName") or "",
            "toContactId": contact_id,
            "isEstimate": is_estimate,
            "isAccepted": is_estimate and status == "ACCEPTED",
            "invoiceType": "DETAILED_ITEMS",
            "sentTo": record.get("contact_email") or record.get("sentTo") or "",
        }
        created = dict(await self._gauzy_request("POST", "/invoices", payload))
        invoice_id = str(created.get("id") or "")
        line_items = record.get("line_items") or record.get("invoiceItems") or []
        if invoice_id and line_items:
            items = []
            for item in line_items:
                unit_cents = int(item.get("unit_price_cents") or round(float(item.get("price") or 0) * 100))
                line_cents = int(item.get("line_total_cents") or round(float(item.get("totalValue") or 0) * 100))
                row = {
                    "tenantId": tenant_id,
                    "organizationId": organization_id,
                    "invoiceId": invoice_id,
                    "description": item.get("description") or item.get("name") or "Line item",
                    "price": unit_cents / 100,
                    "quantity": float(item.get("quantity") or 1),
                    "totalValue": line_cents / 100,
                    "applyTax": False,
                    "applyDiscount": False,
                }
                if project_id:
                    row["projectId"] = project_id
                items.append(row)
            await self._gauzy_request("POST", f"/invoice-item/bulk/{invoice_id}", {"list": items})
        return created

    async def full_gauzy_create_payment(
        self,
        record: dict[str, Any],
        context: dict[str, Any],
        *,
        invoice_id: str,
        contact_id: str | None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tenantId": context.get("tenant_id"),
            "organizationId": context.get("organization_id"),
            "invoiceId": invoice_id,
            "organizationContactId": contact_id,
            "amount": int(record.get("amount_cents") or 0) / 100,
            "currency": str(record.get("currency") or "USD").upper(),
            "paymentDate": record.get("payment_date") or record.get("created_at") or datetime.now(UTC).isoformat(),
            "paymentMethod": str(record.get("method") or "ONLINE").upper(),
            "note": record.get("note") or record.get("reference") or "Floodman Office synchronization",
        }
        if project_id:
            payload["projectId"] = project_id
        return dict(await self._gauzy_request("POST", "/payments/", payload))

    # ------------------------------------------------------------------
    # Competitor intelligence
    # ------------------------------------------------------------------
    async def competitor_targets(self) -> list[dict[str, Any]]:
        value = await self.competitor.request("GET", "/internal/v1/targets")
        return list(value or [])

    async def competitor_reports(self) -> list[dict[str, Any]]:
        value = await self.competitor.request("GET", "/internal/v1/reports?limit=100")
        return list(value or [])

    async def add_competitor(self, payload: dict[str, Any]) -> dict[str, Any]:
        value = await self.competitor.request("POST", "/internal/v1/targets", payload)
        return dict(value or {})

    async def competitor_target(self, target_id: str) -> dict[str, Any]:
        value = await self.competitor.request("GET", f"/internal/v1/targets/{target_id}")
        return dict(value or {})

    async def update_competitor(self, target_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        value = await self.competitor.request("PUT", f"/internal/v1/targets/{target_id}", payload)
        return dict(value or {})

    async def delete_competitor(self, target_id: str) -> dict[str, Any]:
        value = await self.competitor.request("DELETE", f"/internal/v1/targets/{target_id}")
        return dict(value or {})

    async def competitor_report(self, report_id: str) -> dict[str, Any]:
        value = await self.competitor.request("GET", f"/internal/v1/reports/{report_id}")
        return dict(value or {})

    async def run_competitor(self, target_id: str) -> dict[str, Any]:
        # A real public-site scan may need more than the default internal API
        # timeout when DNS, redirects, or several monitored pages are involved.
        value = await self.competitor.request(
            "POST",
            "/internal/v1/run",
            {"target_id": target_id},
            timeout=180.0,
        )
        return dict(value or {})

    async def commit_import(self, normalized: dict[str, Any], run_id: str) -> dict[str, Any]:
        result = await self.local_request(
            "POST",
            "/api/office/import/direct",
            {
                "run_id": run_id,
                "archive_base_url": self.settings.public_url,
                "mode": "HISTORICAL_ARCHIVE",
                "records": normalized,
            },
        )
        return dict(result or {})
