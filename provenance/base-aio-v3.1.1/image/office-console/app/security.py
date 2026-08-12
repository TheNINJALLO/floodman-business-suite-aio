from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import httpx


class SignedRequestError(RuntimeError):
    pass


def parse_first_key(value: str) -> tuple[str, bytes]:
    for raw in value.split(","):
        entry = raw.strip()
        if not entry or ":" not in entry:
            continue
        key_id, encoded = entry.split(":", 1)
        try:
            secret = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise SignedRequestError(f"HMAC key {key_id!r} is not valid base64") from exc
        if len(secret) < 16:
            raise SignedRequestError(f"HMAC key {key_id!r} is too short")
        return key_id, secret
    raise SignedRequestError("No HMAC signing key is configured")


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str).encode("utf-8")


@dataclass(frozen=True)
class SignedClient:
    base_url: str
    key_id: str
    secret: bytes
    timeout_seconds: float = 20.0

    @classmethod
    def from_key_string(cls, base_url: str, keys: str) -> "SignedClient":
        key_id, secret = parse_first_key(keys)
        return cls(base_url.rstrip("/"), key_id, secret)

    def headers(self, body: bytes) -> dict[str, str]:
        timestamp = str(int(time.time()))
        digest = hmac.new(self.secret, timestamp.encode("ascii") + b"." + body, hashlib.sha256).digest()
        return {
            "x-floodman-key-id": self.key_id,
            "x-floodman-timestamp": timestamp,
            "x-floodman-signature": base64.b64encode(digest).decode("ascii"),
            "content-type": "application/json",
        }

    async def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = b"" if payload is None else canonical_json(payload)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                content=body if body else None,
                headers=self.headers(body),
            )
        if response.is_error:
            raise SignedRequestError(f"{method} {path} returned {response.status_code}: {response.text[:600]}")
        if not response.content:
            return {}
        return response.json()
