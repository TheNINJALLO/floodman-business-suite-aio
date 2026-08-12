from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import Settings
from ..security import internal_headers


class FloodmanOfficeClient:
    """Narrow internal bridge used to attach signed PDFs to a client file."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.office_internal_url.rstrip("/")
        self.key_id, self.secret = next(iter(settings.internal_hmac_keys.items()))
        self.client = httpx.Client(timeout=30.0, follow_redirects=False)

    def close(self) -> None:
        self.client.close()

    def attach_client_file(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")
        response = self.client.post(
            f"{self.base_url}/internal/v1/client-files/attach",
            content=body,
            headers=internal_headers(self.key_id, self.secret, body),
        )
        if response.is_error:
            raise RuntimeError(
                f"Floodman client-file attachment returned {response.status_code}: {response.text[:1000]}"
            )
        return dict(response.json() or {})
