from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CallerProjection(StrictModel):
    name: str = Field(default="", max_length=200)
    first_name: str = Field(default="", max_length=100)
    last_name: str = Field(default="", max_length=100)
    company: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=40)
    phone_e164: str = Field(default="", max_length=40)
    phone_verified: bool = False


class PropertyProjection(StrictModel):
    name: str = Field(default="", max_length=200)
    property_type: str = Field(default="", max_length=80)
    street: str = Field(default="", max_length=200)
    city: str = Field(default="", max_length=100)
    state: str = Field(default="", max_length=50)
    postal_code: str = Field(default="", max_length=20)
    country: str = Field(default="US", min_length=2, max_length=2)
    insurer: str = Field(default="", max_length=200)
    claim_number: str = Field(default="", max_length=100)


class StableProjectionIds(StrictModel):
    customer_id: str = Field(min_length=1, max_length=100)
    property_id: str = Field(min_length=1, max_length=100)
    job_id: str = Field(min_length=1, max_length=100)
    roomflow_job_id: str = Field(min_length=1, max_length=100)
    estimate_id: str = Field(min_length=1, max_length=100)
    note_id: str = Field(min_length=1, max_length=100)
    task_id: str = Field(min_length=1, max_length=100)
    appointment_id: str = Field(min_length=1, max_length=100)


class CallIntakeProjectionRequest(StrictModel):
    intake_id: str = Field(min_length=1, max_length=100)
    organization_id: str = Field(min_length=1, max_length=100)
    workspace_id: str = Field(min_length=1, max_length=100)
    provider: str = Field(min_length=1, max_length=80)
    provider_call_id: str = Field(min_length=1, max_length=200)
    event_type: Literal[
        "call-started", "caller-identified", "transcript-updated", "call-ended", "call-failed"
    ]
    event_sequence: int = Field(ge=0)
    status: Literal["ACTIVE", "COMPLETED", "REVIEW_REQUIRED"]
    occurred_at: datetime
    started_at: datetime | None = None
    ended_at: datetime | None = None
    caller: CallerProjection = Field(default_factory=CallerProjection)
    property: PropertyProjection = Field(default_factory=PropertyProjection)
    service_reason: str = Field(default="", max_length=2000)
    summary: str = Field(default="", max_length=5000)
    requested_services: list[str] = Field(default_factory=list, max_length=30)
    urgency: str = Field(default="NORMAL", max_length=40)
    appointment: dict[str, str | bool | None] = Field(default_factory=dict)
    consent: dict[str, str | bool | None] = Field(default_factory=dict)
    transcript_available: bool = False
    transcript_reference: str = Field(default="", max_length=500)
    failure_reason: str = Field(default="", max_length=500)
    review_reasons: list[str] = Field(default_factory=list, max_length=20)
    proposed_ids: StableProjectionIds


class CallIntakeLinksRequest(StrictModel):
    gauzy_contact_id: str = Field(default="", max_length=200)
    gauzy_project_id: str = Field(default="", max_length=200)
