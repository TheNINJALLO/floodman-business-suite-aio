from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Mapping


class AuthenticationError(ValueError):
    pass


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def privacy_hash(secret: bytes, value: str) -> str:
    """Keyed, non-reversible hash for low-value telemetry such as IP/user-agent fingerprints."""
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign_internal_body(secret: bytes, timestamp: str, body: bytes) -> str:
    digest = hmac.new(secret, timestamp.encode("ascii") + b"." + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_internal_request(
    headers: Mapping[str, str], body: bytes, keyring: Mapping[str, bytes], max_age_seconds: int, now: int | None = None
) -> str:
    key_id = headers.get("x-floodman-key-id", "")
    timestamp = headers.get("x-floodman-timestamp", "")
    received = headers.get("x-floodman-signature", "")
    if not key_id or not timestamp or not received:
        raise AuthenticationError("Missing internal authentication headers")
    secret = keyring.get(key_id)
    if secret is None:
        raise AuthenticationError("Unknown internal key id")
    try:
        issued_at = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("Invalid internal timestamp") from exc
    current = int(time.time()) if now is None else now
    if abs(current - issued_at) > max_age_seconds:
        raise AuthenticationError("Internal signature has expired")
    expected = sign_internal_body(secret, timestamp, body)
    if not hmac.compare_digest(received, expected):
        raise AuthenticationError("Invalid internal signature")
    return key_id


def internal_headers(key_id: str, secret: bytes, body: bytes, timestamp: int | None = None) -> dict[str, str]:
    ts = str(int(time.time()) if timestamp is None else timestamp)
    return {
        "x-floodman-key-id": key_id,
        "x-floodman-timestamp": ts,
        "x-floodman-signature": sign_internal_body(secret, ts, body),
        "content-type": "application/json",
    }


def verify_square_webhook(signature_key: str, notification_url: str, body: bytes, received: str) -> bool:
    digest = hmac.new(
        signature_key.encode("utf-8"), notification_url.encode("utf-8") + body, hashlib.sha256
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return bool(received) and hmac.compare_digest(received, expected)


def verify_shared_secret(received: str, expected: str) -> bool:
    return bool(received) and bool(expected) and hmac.compare_digest(received.encode(), expected.encode())


@dataclass(frozen=True, slots=True)
class PortalClaims:
    job_id: str
    version: int
    expires_at: int


def create_portal_token(job_id: str, version: int, secret: bytes, ttl_seconds: int, now: int | None = None) -> str:
    issued = int(time.time()) if now is None else now
    payload = json.dumps(
        {"job_id": job_id, "version": version, "exp": issued + ttl_seconds},
        separators=(",", ":"), sort_keys=True,
    ).encode()
    encoded = _b64url_encode(payload)
    signature = _b64url_encode(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def decode_portal_token(token: str, secret: bytes, now: int | None = None) -> PortalClaims:
    try:
        encoded, received = token.split(".", 1)
        expected = _b64url_encode(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(received, expected):
            raise AuthenticationError("Invalid portal token")
        payload = json.loads(_b64url_decode(encoded))
        claims = PortalClaims(
            job_id=str(payload["job_id"]), version=int(payload["version"]), expires_at=int(payload["exp"])
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise AuthenticationError("Malformed portal token") from exc
    current = int(time.time()) if now is None else now
    if claims.expires_at < current:
        raise AuthenticationError("Portal token has expired")
    return claims


def twilio_signature(auth_token: str, url: str, params: Mapping[str, object]) -> str:
    """Calculate Twilio's x-www-form-urlencoded webhook signature.

    Twilio signs the exact configured public URL followed by every POST field sorted
    by field name, using HMAC-SHA1 and the account Auth Token.
    """
    value = url
    for key in sorted(params):
        raw = params[key]
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        for item in values:
            value += f"{key}{'' if item is None else item}"
    digest = hmac.new(auth_token.encode("utf-8"), value.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("ascii")


def verify_twilio_webhook(auth_token: str, url: str, params: Mapping[str, object], received: str) -> bool:
    expected = twilio_signature(auth_token, url, params)
    return bool(received) and hmac.compare_digest(received, expected)
