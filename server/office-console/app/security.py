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

    async def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        body = b"" if payload is None else canonical_json(payload)
        request_timeout = self.timeout_seconds if timeout is None else timeout
        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    content=body if body else None,
                    headers=self.headers(body),
                )
        except httpx.TimeoutException as exc:
            raise SignedRequestError(
                f"{method} {path} timed out after {request_timeout:g} seconds. The website scan may still be retryable."
            ) from exc
        except httpx.ConnectError as exc:
            raise SignedRequestError(f"{method} {path} could not reach the Floodman service: {exc}") from exc
        if response.is_error:
            detail = ""
            try:
                payload_value = response.json()
                if isinstance(payload_value, dict):
                    raw_detail = payload_value.get("detail")
                    if isinstance(raw_detail, list):
                        detail = "; ".join(str(item.get("msg") if isinstance(item, dict) else item) for item in raw_detail)
                    elif raw_detail is not None:
                        detail = str(raw_detail)
            except Exception:
                detail = ""
            if not detail:
                detail = response.text[:600].strip() or response.reason_phrase
            raise SignedRequestError(f"{method} {path} failed: {detail}")
        if not response.content:
            return {}
        return response.json()


def parse_keyring(value: str) -> dict[str, bytes]:
    """Parse every configured key for inbound internal-request verification."""
    result: dict[str, bytes] = {}
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise SignedRequestError("HMAC key entries must use key-id:base64-secret")
        key_id, encoded = entry.split(":", 1)
        try:
            secret = base64.b64decode(encoded, validate=True)
        except Exception as exc:
            raise SignedRequestError(f"HMAC key {key_id!r} is not valid base64") from exc
        if len(secret) < 16:
            raise SignedRequestError(f"HMAC key {key_id!r} is too short")
        result[key_id] = secret
    if not result:
        raise SignedRequestError("No HMAC verification key is configured")
    return result


def verify_signed_body(
    headers: Any,
    body: bytes,
    keys: str,
    *,
    max_age_seconds: int = 300,
    now: int | None = None,
) -> str:
    """Verify the same HMAC envelope used by the Floodman orchestrator."""
    keyring = parse_keyring(keys)
    key_id = str(headers.get("x-floodman-key-id") or "")
    timestamp = str(headers.get("x-floodman-timestamp") or "")
    received = str(headers.get("x-floodman-signature") or "")
    if not key_id or not timestamp or not received:
        raise SignedRequestError("Missing internal authentication headers")
    secret = keyring.get(key_id)
    if secret is None:
        raise SignedRequestError("Unknown internal authentication key")
    try:
        issued_at = int(timestamp)
    except ValueError as exc:
        raise SignedRequestError("Invalid internal authentication timestamp") from exc
    current = int(time.time()) if now is None else now
    if abs(current - issued_at) > max_age_seconds:
        raise SignedRequestError("Internal authentication timestamp has expired")
    expected = hmac.new(secret, timestamp.encode("ascii") + b"." + body, hashlib.sha256).digest()
    try:
        received_bytes = base64.b64decode(received, validate=True)
    except Exception as exc:
        raise SignedRequestError("Invalid internal authentication signature") from exc
    if not hmac.compare_digest(received_bytes, expected):
        raise SignedRequestError("Invalid internal authentication signature")
    return key_id
