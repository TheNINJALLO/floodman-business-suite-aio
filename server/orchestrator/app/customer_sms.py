"""Validated, server-to-server customer consent synchronization."""
from datetime import UTC, datetime, timedelta

from pydantic import AwareDatetime, Field, model_validator
from typing import Literal

from .schemas import StrictModel


class CustomerSmsConsent(StrictModel):
    idempotency_key: str = Field(pattern=r"^[a-f0-9-]{36}$")
    organization_id: str = Field(min_length=1, max_length=100)
    contact_id: str = Field(min_length=1, max_length=150)
    phone_e164: str = Field(pattern=r"^\+1[2-9][0-9]{2}[2-9][0-9]{6}$")
    status: Literal["OPTED_IN", "OPTED_OUT"]
    captured_at: AwareDatetime
    disclosure_version: str = Field(min_length=1, max_length=120)
    disclosure_text: str = Field(min_length=100, max_length=2000)

    @model_validator(mode="after")
    def validate_time(self):
        if self.captured_at > datetime.now(UTC) + timedelta(minutes=5):
            raise ValueError("Consent cannot have a future capture time")
        return self


def event_is_newer(current, captured_at):
    """Delayed retries must not restore permission after a later withdrawal."""
    if not current:
        return True
    # opted_* timestamps in the legacy table reflect processing time, not the
    # time the customer made the choice. A delayed opt-in sync must not make a
    # later, already captured withdrawal look older.
    times = [current["captured_at"]] if current.get("captured_at") else [current.get(key) for key in ("opted_in_at", "opted_out_at")]
    timestamps = []
    for value in times:
        if value:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
            timestamps.append(parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed)
    return not timestamps or captured_at > max(timestamps)


def may_resume_existing_consent(current):
    evidence = (current or {}).get("evidence") or {}
    return bool(current and current.get("disclosure_version") and isinstance(evidence, dict)
                and evidence.get("disclosure_text"))
