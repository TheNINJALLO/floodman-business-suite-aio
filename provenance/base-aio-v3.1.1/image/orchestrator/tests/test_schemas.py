from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.schemas import EstimateLine, PaymentSchedule, SyncEstimateRequest


def base_payload() -> dict:
    return {
        "idempotency_key": "roomflow-job-12345-r1",
        "organization_id": "floodman",
        "roomflow_job_id": "job-1",
        "roomflow_estimate_id": "estimate-1",
        "revision": 1,
        "invoice_number": 1001,
        "currency": "USD",
        "customer": {"first_name": "Jane", "last_name": "Doe", "email": "jane@example.com", "phone": "3135550199"},
        "property": {"service_address": {"street": "1 Main", "city": "Detroit", "state": "MI", "postal_code": "48201"}},
        "lines": [{"line_id": "l1", "name": "Drain", "quantity": "2", "unit_price_cents": 12500, "line_total_cents": 25000}],
        "tax_cents": 1500,
        "discount_cents": 500,
        "total_cents": 26000,
        "authorization": {
            "pdf_url": "https://example.com/work-auth.pdf",
            "title": "Work Authorization",
            "fields": [{"field_type": "SIGNATURE", "page": 1, "position_x": 10, "position_y": 80, "width": 30, "height": 8}],
        },
        "payment_schedule": {"deposit_percent": "30", "deposit_due_date": "2026-08-05", "balance_due_date": "2026-08-30"},
    }


def test_estimate_math_and_deposit() -> None:
    request = SyncEstimateRequest.model_validate(base_payload())
    assert request.payment_schedule.calculate_deposit(request.total_cents) == 7800


def test_estimate_total_mismatch_rejected() -> None:
    payload = base_payload()
    payload["total_cents"] += 1
    with pytest.raises(ValidationError):
        SyncEstimateRequest.model_validate(payload)


def test_line_rounding_is_integer_cents() -> None:
    line = EstimateLine(line_id="x", name="x", quantity=Decimal("1.5"), unit_price_cents=101, line_total_cents=152)
    assert line.line_total_cents == 152


def test_exactly_one_deposit_method() -> None:
    with pytest.raises(ValidationError):
        PaymentSchedule(
            deposit_cents=100,
            deposit_percent=Decimal("10"),
            deposit_due_date="2026-08-05",
            balance_due_date="2026-08-06",
        )


def test_zero_value_estimate_rejected() -> None:
    payload = base_payload()
    payload["lines"] = [{"line_id": "free", "name": "Free", "quantity": "1", "unit_price_cents": 0, "line_total_cents": 0}]
    payload["tax_cents"] = 0
    payload["discount_cents"] = 0
    payload["total_cents"] = 0
    with pytest.raises(ValidationError):
        SyncEstimateRequest.model_validate(payload)


def test_opted_in_sms_requires_auditable_evidence() -> None:
    payload = base_payload()
    payload["customer"]["sms_consent"] = "OPTED_IN"
    with pytest.raises(ValidationError):
        SyncEstimateRequest.model_validate(payload)


def test_opted_in_sms_with_disclosure_is_accepted() -> None:
    payload = base_payload()
    payload["customer"].update({
        "sms_consent": "OPTED_IN",
        "sms_consent_captured_at": "2026-08-04T12:00:00-04:00",
        "sms_consent_source": "ROOMFLOW_WORK_AUTHORIZATION",
        "sms_consent_disclosure_version": "sms-v1",
        "sms_consent_disclosure_text": "Transactional Floodman text consent with STOP and HELP disclosures.",
    })
    request = SyncEstimateRequest.model_validate(payload)
    assert request.customer.sms_consent == "OPTED_IN"
