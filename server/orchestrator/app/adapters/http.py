from __future__ import annotations

import random
import time
from typing import Any

import httpx


class ProviderError(RuntimeError):
    def __init__(self, provider: str, message: str, status_code: int | None = None, details: Any = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code
        self.details = details


def request_json(
    client: httpx.Client,
    provider: str,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    retry_statuses: set[int] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    retry_statuses = retry_statuses or {408, 425, 429, 500, 502, 503, 504}
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            response = client.request(method, url, **kwargs)
            if response.status_code in retry_statuses and attempt + 1 < attempts:
                retry_after = response.headers.get("retry-after")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else min(15.0, (2 ** attempt) + random.random())
                time.sleep(delay)
                continue
            if response.is_error:
                try:
                    details: Any = response.json()
                except Exception:
                    details = response.text[:2000]
                raise ProviderError(provider, "request failed", response.status_code, details)
            if response.status_code == 204 or not response.content:
                return {}
            data = response.json()
            if not isinstance(data, dict):
                raise ProviderError(provider, "expected a JSON object response", response.status_code)
            return data
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                break
            time.sleep(min(15.0, (2 ** attempt) + random.random()))
    raise ProviderError(provider, f"transport failure: {last_error}")
