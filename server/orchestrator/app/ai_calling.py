from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

CallEventType = Literal[
    "call-started", "caller-identified", "transcript-updated", "call-ended", "call-failed"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CallerDetails(StrictModel):
    name: str = Field(default="", max_length=200)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=40)
    phone_verified: bool = False


class PropertyDetails(StrictModel):
    name: str = Field(default="", max_length=200)
    property_type: str = Field(default="", max_length=80)
    street: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=50)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)
    insurer: str = Field(default="", max_length=200)
    claim_number: str = Field(default="", max_length=100)


class AppointmentDetails(StrictModel):
    requested: bool = False
    requested_window: str = Field(default="", max_length=300)
    confirmed: bool = False
    appointment_id: str = Field(default="", max_length=100)


class ConsentDetails(StrictModel):
    sms_status: Literal["UNKNOWN", "OPTED_IN", "OPTED_OUT"] = "UNKNOWN"
    email_status: Literal["UNKNOWN", "OPTED_IN", "OPTED_OUT"] = "UNKNOWN"
    disclosure_version: str = Field(default="", max_length=120)
    evidence_id: str = Field(default="", max_length=200)


class AiCallEvent(StrictModel):
    provider: str = Field(min_length=1, max_length=80)
    provider_call_id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=200)
    event_type: CallEventType
    event_sequence: int = Field(ge=0)
    organization_id: str = Field(min_length=1, max_length=100)
    workspace_id: str = Field(min_length=1, max_length=100)
    occurred_at: datetime
    caller: CallerDetails = Field(default_factory=CallerDetails)
    property: PropertyDetails = Field(default_factory=PropertyDetails)
    service_reason: str = Field(default="", max_length=2000)
    summary: str = Field(default="", max_length=5000)
    requested_services: list[str] = Field(default_factory=list, max_length=30)
    urgency: Literal["NORMAL", "PRIORITY", "URGENT", "EMERGENCY"] = "NORMAL"
    appointment: AppointmentDetails = Field(default_factory=AppointmentDetails)
    consent: ConsentDetails = Field(default_factory=ConsentDetails)
    transcript_available: bool = False
    transcript_reference: str = Field(default="", max_length=500)
    identity_ambiguous: bool = False
    failure_reason: str = Field(default="", max_length=500)
    review_reasons: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def event_requirements(self) -> AiCallEvent:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        self.occurred_at = self.occurred_at.astimezone(UTC)
        if self.event_type == "call-failed" and not self.failure_reason:
            raise ValueError("call-failed requires failure_reason")
        if self.event_type == "transcript-updated" and not (
            self.transcript_available or self.summary or self.transcript_reference
        ):
            raise ValueError("transcript-updated requires a summary or approved transcript reference")
        return self


class AiCallingProvider(Protocol):
    name: str

    def normalize(self, payload: dict[str, Any]) -> AiCallEvent: ...


class DeterministicAiCallingProvider:
    """Local/lab adapter with no model calls and a strict canonical payload."""

    name = "deterministic"

    def normalize(self, payload: dict[str, Any]) -> AiCallEvent:
        event = AiCallEvent.model_validate(payload)
        if event.provider != self.name:
            raise ValueError("provider does not match deterministic adapter")
        return event


def provider_for(name: str) -> AiCallingProvider:
    if name == "deterministic":
        return DeterministicAiCallingProvider()
    raise ValueError(f"Unsupported AI calling provider {name!r}")


def event_dedupe_key(event: AiCallEvent) -> str:
    """Stable replay key includes the provider call ID and event type."""

    return f"{event.provider_call_id}:{event.event_type}:{event.event_sequence}:{event.event_id}"


def event_order_decision(last_sequence: int, event: AiCallEvent) -> Literal["ACCEPT", "STALE"]:
    return "STALE" if event.event_sequence <= last_sequence else "ACCEPT"


def next_call_status(event: AiCallEvent, *, review_reasons: list[str] | None = None) -> str:
    if event.event_type == "call-failed" or event.identity_ambiguous or review_reasons:
        return "REVIEW_REQUIRED"
    if event.event_type == "call-ended":
        return "COMPLETED"
    return "ACTIVE"


def stable_projection_ids(provider: str, provider_call_id: str) -> dict[str, str]:
    namespace = f"floodman:ai-call:{provider}:{provider_call_id}"
    return {
        key: str(uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:{key}"))
        for key in (
            "intake_id", "customer_id", "property_id", "job_id", "roomflow_job_id",
            "estimate_id", "note_id", "task_id", "appointment_id",
        )
    }
