from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Address(StrictModel):
    street: str = Field(min_length=1, max_length=200)
    street2: str | None = Field(default=None, max_length=200)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=2, max_length=50)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)


class CustomerInput(StrictModel):
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=40)
    billing_address: Address | None = None
    timezone: str = Field(default="America/Detroit", min_length=3, max_length=80)
    sms_consent: Literal["UNKNOWN", "OPTED_IN", "OPTED_OUT"] = "UNKNOWN"
    sms_consent_captured_at: datetime | None = None
    sms_consent_source: str = Field(default="UNSPECIFIED", max_length=120)
    sms_consent_disclosure_version: str | None = Field(default=None, max_length=120)
    sms_consent_disclosure_text: str | None = Field(default=None, max_length=2000)
    sms_consent_evidence_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def verify_sms_consent_evidence(self) -> "CustomerInput":
        if self.sms_consent == "OPTED_IN":
            missing = []
            if self.sms_consent_captured_at is None:
                missing.append("sms_consent_captured_at")
            if not self.sms_consent_disclosure_version:
                missing.append("sms_consent_disclosure_version")
            if not self.sms_consent_disclosure_text:
                missing.append("sms_consent_disclosure_text")
            if self.sms_consent_source == "UNSPECIFIED":
                missing.append("sms_consent_source")
            if missing:
                raise ValueError("OPTED_IN SMS consent requires: " + ", ".join(missing))
        return self

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PropertyInput(StrictModel):
    service_address: Address
    property_name: str | None = Field(default=None, max_length=150)
    property_type: str | None = Field(default=None, max_length=80)
    claim_number: str | None = Field(default=None, max_length=100)
    insurer: str | None = Field(default=None, max_length=150)


class EstimateLine(StrictModel):
    line_id: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=250)
    description: str = Field(default="", max_length=5000)
    quantity: Decimal = Field(gt=0, max_digits=14, decimal_places=4)
    unit_price_cents: int = Field(ge=0)
    line_total_cents: int = Field(ge=0)
    taxable: bool = False

    @model_validator(mode="after")
    def verify_total(self) -> "EstimateLine":
        calculated = int((self.quantity * Decimal(self.unit_price_cents)).quantize(Decimal("1"), ROUND_HALF_UP))
        if calculated != self.line_total_cents:
            raise ValueError(
                f"line_total_cents mismatch for {self.line_id}: expected {calculated}, got {self.line_total_cents}"
            )
        return self


class SignatureField(StrictModel):
    field_type: Literal["SIGNATURE", "INITIALS", "DATE", "NAME", "EMAIL", "TEXT", "CHECKBOX"]
    page: int = Field(ge=1)
    position_x: Decimal = Field(ge=0, le=100)
    position_y: Decimal = Field(ge=0, le=100)
    width: Decimal = Field(gt=0, le=100)
    height: Decimal = Field(gt=0, le=100)
    required: bool = True


class SigningDocument(StrictModel):
    pdf_url: HttpUrl
    title: str = Field(min_length=1, max_length=250)
    fields: list[SignatureField] = Field(min_length=1, max_length=40)


class PaymentSchedule(StrictModel):
    deposit_cents: int | None = Field(default=None, ge=0)
    deposit_percent: Decimal | None = Field(default=None, gt=0, lt=100, decimal_places=4)
    deposit_due_date: date
    balance_due_date: date

    @model_validator(mode="after")
    def one_deposit_method(self) -> "PaymentSchedule":
        if (self.deposit_cents is None) == (self.deposit_percent is None):
            raise ValueError("Provide exactly one of deposit_cents or deposit_percent")
        if self.balance_due_date < self.deposit_due_date:
            raise ValueError("balance_due_date cannot precede deposit_due_date")
        return self

    def calculate_deposit(self, total_cents: int) -> int:
        if self.deposit_cents is not None:
            result = self.deposit_cents
        else:
            result = int((Decimal(total_cents) * self.deposit_percent / Decimal(100)).quantize(
                Decimal("1"), ROUND_HALF_UP
            ))
        if result < 0 or result > total_cents:
            raise ValueError("Deposit must be between zero and the estimate total")
        return result


class SyncEstimateRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    organization_id: str = Field(min_length=1, max_length=100)
    roomflow_job_id: str = Field(min_length=1, max_length=150)
    roomflow_estimate_id: str = Field(min_length=1, max_length=150)
    revision: int = Field(ge=1)
    invoice_number: int = Field(ge=1)
    currency: Literal["USD"] = "USD"
    customer: CustomerInput
    property: PropertyInput
    lines: list[EstimateLine] = Field(min_length=1, max_length=500)
    tax_cents: int = Field(default=0, ge=0)
    discount_cents: int = Field(default=0, ge=0)
    total_cents: int = Field(gt=0)
    terms: str = Field(default="", max_length=20000)
    internal_note: str = Field(default="", max_length=5000)
    authorization: SigningDocument
    payment_schedule: PaymentSchedule

    @model_validator(mode="after")
    def verify_estimate_total(self) -> "SyncEstimateRequest":
        calculated = sum(item.line_total_cents for item in self.lines) + self.tax_cents - self.discount_cents
        if calculated != self.total_cents:
            raise ValueError(f"Estimate total mismatch: expected {calculated}, got {self.total_cents}")
        self.payment_schedule.calculate_deposit(self.total_cents)
        return self


class ChangeOrderRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    revision: int = Field(ge=1)
    delta_cents: int
    revised_total_cents: int = Field(ge=0)
    reason: str = Field(min_length=1, max_length=5000)
    document: SigningDocument


class CompletionRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    revision: int = Field(ge=1)
    document: SigningDocument
    completed_on: date
    notes: str = Field(default="", max_length=5000)


class StartWorkRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)


class AiReportInput(StrictModel):
    target_id: str
    target_name: str
    report_id: str
    report: dict
    change_summary: dict
    generated_at: str


class ArHoldRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    hold_type: Literal["MANUAL", "DISPUTE", "CALLBACK", "WRONG_NUMBER", "LEGAL", "PAYMENT_REVIEW"] = "MANUAL"
    reason: str = Field(min_length=3, max_length=4000)


class ArResumeRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    reason: str = Field(default="Staff resumed automated reminders", max_length=1000)


class SmsConsentRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    status: Literal["UNKNOWN", "OPTED_IN", "OPTED_OUT"]
    source: str = Field(default="STAFF", max_length=120)
    disclosure_version: str | None = Field(default=None, max_length=120)


class ManualReplyRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    body: str = Field(min_length=1, max_length=1500)


class StaffAlertUpdateRequest(StrictModel):
    idempotency_key: str = Field(min_length=12, max_length=200)
    status: Literal["ACKNOWLEDGED", "RESOLVED"]
