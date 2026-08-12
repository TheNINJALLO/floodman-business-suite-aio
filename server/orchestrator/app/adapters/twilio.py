from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings
from .http import ProviderError, request_json


class TwilioClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.twilio_base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            verify=settings.twilio_verify_tls,
            auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            headers={"accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def healthcheck(self) -> bool:
        if not self.settings.twilio_enabled:
            return True
        request_json(
            self.client,
            "twilio",
            "GET",
            f"/Accounts/{self.settings.twilio_account_sid}.json",
            attempts=1,
        )
        return True

    def send_sms(self, *, to: str, body: str) -> dict[str, Any]:
        if not self.settings.twilio_enabled:
            raise ProviderError("twilio", "SMS is disabled")
        payload: dict[str, str] = {
            "To": to,
            "Body": body,
            "StatusCallback": self.settings.twilio_status_webhook_url,
            "MessagingServiceSid": self.settings.twilio_messaging_service_sid,
        }
        if not self.settings.twilio_messaging_service_sid and self.settings.twilio_from_number:
            payload.pop("MessagingServiceSid", None)
            payload["From"] = self.settings.twilio_from_number
        result = request_json(
            self.client,
            "twilio",
            "POST",
            f"/Accounts/{self.settings.twilio_account_sid}/Messages.json",
            data=payload,
            attempts=1,
        )
        if not result.get("sid"):
            raise ProviderError("twilio", "message response did not include sid", details=result)
        return result
