from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from ..security import internal_headers
from .http import ProviderError, request_json


class MessagingAIClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = httpx.Client(
            base_url=settings.messaging_ai_service_url,
            timeout=httpx.Timeout(45.0, connect=10.0),
            headers={"accept": "application/json"},
        )

    def close(self) -> None:
        self.client.close()

    def healthcheck(self) -> bool:
        if not self.settings.messaging_ai_enabled:
            return True
        result = request_json(self.client, "messaging-ai", "GET", "/health/live", attempts=1)
        return result.get("status") == "ok"

    def classify(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.settings.messaging_ai_enabled:
            raise ProviderError("messaging-ai", "service is disabled")
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        key_id, secret = next(iter(self.settings.ai_hmac_keys.items()))
        response = request_json(
            self.client,
            "messaging-ai",
            "POST",
            "/internal/v1/classify",
            content=body,
            headers=internal_headers(key_id, secret, body),
            attempts=2,
        )
        return response
