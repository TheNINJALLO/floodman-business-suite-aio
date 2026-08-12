from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Mapping


class AuthenticationError(ValueError):
    pass


def body_signature(secret: bytes, timestamp: str, body: bytes) -> str:
    return base64.b64encode(hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).digest()).decode()


def verify(headers: Mapping[str, str], body: bytes, keys: Mapping[str, bytes], max_age: int) -> str:
    key_id = headers.get("x-floodman-key-id", "")
    timestamp = headers.get("x-floodman-timestamp", "")
    received = headers.get("x-floodman-signature", "")
    if key_id not in keys or not timestamp or not received:
        raise AuthenticationError("Missing or unknown internal authentication headers")
    try:
        issued = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("Invalid timestamp") from exc
    if abs(int(time.time()) - issued) > max_age:
        raise AuthenticationError("Expired internal request")
    expected = body_signature(keys[key_id], timestamp, body)
    if not hmac.compare_digest(received, expected):
        raise AuthenticationError("Invalid internal signature")
    return key_id


def signed_headers(keys: Mapping[str, bytes], body: bytes) -> dict[str, str]:
    key_id = next(iter(keys))
    timestamp = str(int(time.time()))
    return {
        "x-floodman-key-id": key_id,
        "x-floodman-timestamp": timestamp,
        "x-floodman-signature": body_signature(keys[key_id], timestamp, body),
        "content-type": "application/json",
    }
