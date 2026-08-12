from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from ..config import Settings
from .http import ProviderError, request_json


def stable_idempotency(*parts: object) -> str:
    raw = "|".join(str(part) for part in parts).encode()
    return hashlib.sha256(raw).hexdigest()[:64]


class SquareClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.square_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=settings.square_verify_tls,
            headers={
                "authorization": f"Bearer {settings.square_access_token}",
                "square-version": settings.square_version,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )

    def close(self) -> None:
        self.client.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        return request_json(self.client, "square", method, path, **kwargs)

    def healthcheck(self) -> bool:
        self._request("GET", f"/v2/locations/{self.settings.square_location_id}")
        return True

    def _today(self) -> str:
        return datetime.now(ZoneInfo(self.settings.ar_timezone)).date().isoformat()

    def find_customer(self, email: str) -> dict[str, Any] | None:
        response = self._request(
            "POST",
            "/v2/customers/search",
            json={"query": {"filter": {"email_address": {"exact": email}}}, "limit": 20},
        )
        customers = response.get("customers") or []
        return next((customer for customer in customers if customer.get("email_address", "").lower() == email.lower()), None)

    def ensure_customer(self, customer: dict[str, Any], internal_id: str) -> dict[str, Any]:
        existing = self.find_customer(customer["email"])
        if existing:
            return existing
        payload = {
            "idempotency_key": stable_idempotency("customer", internal_id, customer["email"]),
            "given_name": customer["first_name"],
            "family_name": customer["last_name"],
            "email_address": customer["email"],
            "phone_number": customer["phone"],
            "reference_id": internal_id[:40],
            "note": "Created by Floodman Orchestrator from RoomFlow",
        }
        response = self._request("POST", "/v2/customers", json=payload)
        result = response.get("customer")
        if not result:
            raise ProviderError("square", "customer create response did not include customer", details=response)
        return result

    def create_order(self, job: dict[str, Any], customer_id: str) -> dict[str, Any]:
        """Legacy full-contract order used only when split final invoices are disabled."""
        lines = [
            {
                "name": line["name"][:255],
                "note": line.get("description", "")[:4000],
                "quantity": str(line["quantity"]),
                "base_price_money": {"amount": line["unit_price_cents"], "currency": job["currency"]},
            }
            for line in job["estimate"]["lines"]
        ]
        if job["estimate"].get("tax_cents", 0):
            lines.append(
                {
                    "name": "Sales tax (calculated in RoomFlow)",
                    "quantity": "1",
                    "base_price_money": {
                        "amount": job["estimate"]["tax_cents"],
                        "currency": job["currency"],
                    },
                }
            )
        order: dict[str, Any] = {
            "location_id": self.settings.square_location_id,
            "customer_id": customer_id,
            "reference_id": str(job["id"]),
            "source": {"name": "Floodman Orchestrator"},
            "line_items": lines,
        }
        discount_cents = int(job["estimate"].get("discount_cents", 0))
        if discount_cents:
            order["discounts"] = [
                {
                    "uid": "roomflow-discount",
                    "name": "Approved estimate discount",
                    "scope": "ORDER",
                    "amount_money": {"amount": discount_cents, "currency": job["currency"]},
                }
            ]
        payload = {
            "idempotency_key": stable_idempotency("order", job["id"], job["revision"]),
            "order": order,
        }
        response = self._request("POST", "/v2/orders", json=payload)
        result = response.get("order")
        if not result:
            raise ProviderError("square", "order create response did not include order", details=response)
        total = (result.get("total_money") or {}).get("amount")
        if total is None or int(total) != int(job["total_cents"]):
            raise ProviderError(
                "square",
                f"Square order total {total!r} does not match RoomFlow total {job['total_cents']}",
                details=result,
            )
        return result

    def _payment_methods(self) -> dict[str, bool]:
        return {
            "card": self.settings.square_accept_card,
            "square_gift_card": False,
            "bank_account": self.settings.square_accept_ach,
            "buy_now_pay_later": False,
            "cash_app_pay": self.settings.square_accept_cash_app,
        }

    def _create_amount_order(
        self,
        *,
        job: dict[str, Any],
        customer_id: str,
        amount_cents: int,
        name: str,
        note: str,
        reference_id: str,
        idempotency_parts: tuple[object, ...],
    ) -> dict[str, Any]:
        if amount_cents <= 0:
            raise ValueError("Square order amount must be positive")
        response = self._request(
            "POST",
            "/v2/orders",
            json={
                "idempotency_key": stable_idempotency(*idempotency_parts),
                "order": {
                    "location_id": self.settings.square_location_id,
                    "customer_id": customer_id,
                    "reference_id": reference_id[:40],
                    "source": {"name": "Floodman Orchestrator"},
                    "line_items": [
                        {
                            "name": name[:255],
                            "note": note[:4000],
                            "quantity": "1",
                            "base_price_money": {"amount": amount_cents, "currency": job["currency"]},
                        }
                    ],
                },
            },
        )
        order = response.get("order")
        if not order or int((order.get("total_money") or {}).get("amount", -1)) != amount_cents:
            raise ProviderError("square", "single-amount order total mismatch", details=response)
        return order

    def _create_and_publish_single_balance_invoice(
        self,
        *,
        job: dict[str, Any],
        customer_id: str,
        order_id: str,
        invoice_number: str,
        title: str,
        description: str,
        due_date: str,
        idempotency_parts: tuple[object, ...],
        sale_or_service_date: str | None = None,
    ) -> dict[str, Any]:
        invoice_payload: dict[str, Any] = {
            "location_id": self.settings.square_location_id,
            "order_id": order_id,
            "primary_recipient": {"customer_id": customer_id},
            "payment_requests": [
                {
                    "request_type": "BALANCE",
                    "due_date": due_date,
                    "automatic_payment_source": "NONE",
                    "tipping_enabled": False,
                }
            ],
            "delivery_method": self.settings.square_delivery_method,
            "invoice_number": invoice_number[:255],
            "title": title[:255],
            "description": description[:65536],
            "accepted_payment_methods": self._payment_methods(),
            "store_payment_method_enabled": False,
        }
        if sale_or_service_date:
            invoice_payload["sale_or_service_date"] = sale_or_service_date
        created = self._request(
            "POST",
            "/v2/invoices",
            json={
                "idempotency_key": stable_idempotency("create", *idempotency_parts),
                "invoice": invoice_payload,
            },
        )
        invoice = created.get("invoice")
        if not invoice:
            raise ProviderError("square", "invoice create response did not include invoice", details=created)
        published = self._request(
            "POST",
            f"/v2/invoices/{invoice['id']}/publish",
            json={
                "idempotency_key": stable_idempotency("publish", *idempotency_parts),
                "version": invoice["version"],
            },
        )
        result = published.get("invoice")
        if not result:
            raise ProviderError("square", "invoice publish response did not include invoice", details=published)
        return result

    def create_deposit_invoice(self, job: dict[str, Any], customer_id: str) -> dict[str, Any]:
        amount = int(job["deposit_cents"])
        if amount <= 0:
            return {"skipped": True, "amount_cents": 0}
        order = self._create_amount_order(
            job=job,
            customer_id=customer_id,
            amount_cents=amount,
            name="Floodman contract deposit",
            note=f"Deposit for Floodman job {job['roomflow_job_id']}",
            reference_id=f"{job['id']}:deposit",
            idempotency_parts=("deposit-order", job["id"], job["revision"]),
        )
        invoice = self._create_and_publish_single_balance_invoice(
            job=job,
            customer_id=customer_id,
            order_id=str(order["id"]),
            invoice_number=f"F-{job['invoice_number']}-R{job['revision']}-D",
            title="Floodman deposit",
            description="Contract deposit due upon receipt.",
            due_date=self._today(),
            idempotency_parts=("deposit-invoice", job["id"], job["revision"]),
        )
        return {"order": order, "invoice": invoice, "amount_cents": amount}

    def create_final_invoice(
        self,
        job: dict[str, Any],
        customer_id: str,
        *,
        amount_cents: int,
        completed_on: str,
    ) -> dict[str, Any]:
        if amount_cents <= 0:
            return {"skipped": True, "amount_cents": 0}
        order = self._create_amount_order(
            job=job,
            customer_id=customer_id,
            amount_cents=amount_cents,
            name="Floodman final balance",
            note=f"Final balance after completed services for job {job['roomflow_job_id']}",
            reference_id=f"{job['id']}:final",
            idempotency_parts=("final-order", job["id"], job["revision"], amount_cents),
        )
        invoice = self._create_and_publish_single_balance_invoice(
            job=job,
            customer_id=customer_id,
            order_id=str(order["id"]),
            invoice_number=f"F-{job['invoice_number']}-R{job['revision']}-FINAL",
            title="Floodman final invoice",
            description="Final invoice due upon receipt after completion of service.",
            due_date=self._today(),
            idempotency_parts=("final-invoice", job["id"], job["revision"], amount_cents),
            sale_or_service_date=completed_on,
        )
        return {"order": order, "invoice": invoice, "amount_cents": amount_cents}

    def create_and_publish_invoice(self, job: dict[str, Any], customer_id: str, order_id: str) -> dict[str, Any]:
        """Legacy combined deposit/balance invoice for optional backwards compatibility."""
        schedule = job["estimate"]["payment_schedule"]
        requests: list[dict[str, Any]] = []
        if job["deposit_cents"] > 0:
            requests.append(
                {
                    "request_type": "DEPOSIT",
                    "due_date": schedule["deposit_due_date"],
                    "fixed_amount_requested_money": {
                        "amount": job["deposit_cents"],
                        "currency": job["currency"],
                    },
                    "automatic_payment_source": "NONE",
                }
            )
        requests.append(
            {
                "request_type": "BALANCE",
                "due_date": schedule["balance_due_date"],
                "automatic_payment_source": "NONE",
                "tipping_enabled": False,
            }
        )
        payload = {
            "idempotency_key": stable_idempotency("invoice", job["id"], job["revision"]),
            "invoice": {
                "location_id": self.settings.square_location_id,
                "order_id": order_id,
                "primary_recipient": {"customer_id": customer_id},
                "payment_requests": requests,
                "delivery_method": self.settings.square_delivery_method,
                "invoice_number": f"F-{job['invoice_number']}-R{job['revision']}",
                "title": "Floodman Services",
                "description": (
                    f"Floodman job {job['roomflow_job_id']}. "
                    "Work Authorization was completed before this payment request was published."
                ),
                "accepted_payment_methods": self._payment_methods(),
                "store_payment_method_enabled": False,
            },
        }
        created = self._request("POST", "/v2/invoices", json=payload)
        invoice = created.get("invoice")
        if not invoice:
            raise ProviderError("square", "invoice create response did not include invoice", details=created)
        published = self._request(
            "POST",
            f"/v2/invoices/{invoice['id']}/publish",
            json={
                "idempotency_key": stable_idempotency("publish", job["id"], job["revision"]),
                "version": invoice["version"],
            },
        )
        result = published.get("invoice")
        if not result:
            raise ProviderError("square", "invoice publish response did not include invoice", details=published)
        return result

    def create_change_order_invoice(
        self, job: dict[str, Any], document: dict[str, Any], customer_id: str
    ) -> dict[str, Any]:
        metadata = document.get("metadata") or {}
        delta = int(metadata.get("delta_cents", 0))
        if delta <= 0:
            return {"skipped": True, "reason": "non-positive change order", "amount_cents": delta}
        revision = int(document["revision"])
        order = self._create_amount_order(
            job=job,
            customer_id=customer_id,
            amount_cents=delta,
            name=f"Signed Change Order #{revision}",
            note=str(metadata.get("reason", "Approved scope adjustment")),
            reference_id=str(document["id"]),
            idempotency_parts=("change-order-order", document["id"], revision),
        )
        invoice = self._create_and_publish_single_balance_invoice(
            job=job,
            customer_id=customer_id,
            order_id=str(order["id"]),
            invoice_number=f"F-{job['invoice_number']}-CO{revision}",
            title=f"Floodman Change Order #{revision}",
            description="Additional amount from a signed Change Order. Due upon receipt.",
            due_date=self._today(),
            idempotency_parts=("change-order-invoice", document["id"], revision),
        )
        return {"order": order, "invoice": invoice, "amount_cents": delta}

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        response = self._request("GET", f"/v2/invoices/{invoice_id}")
        invoice = response.get("invoice")
        if not invoice:
            raise ProviderError("square", "invoice response missing invoice", details=response)
        return invoice

    @staticmethod
    def summarize_invoice(invoice: dict[str, Any]) -> dict[str, Any]:
        paid_cents = 0
        deposit_paid_cents = 0
        requests = invoice.get("payment_requests") or []
        for request in requests:
            completed = int((request.get("total_completed_amount_money") or {}).get("amount", 0))
            paid_cents += completed
            if request.get("request_type") == "DEPOSIT":
                deposit_paid_cents += completed
        return {
            "invoice_id": str(invoice.get("id", "")),
            "version": int(invoice.get("version", 0)),
            "status": str(invoice.get("status", "UNKNOWN")),
            "public_url": invoice.get("public_url"),
            "paid_cents": paid_cents,
            "deposit_paid_cents": deposit_paid_cents,
            "next_payment_cents": int((invoice.get("next_payment_amount_money") or {}).get("amount", 0)),
            "payment_requests": requests,
        }
