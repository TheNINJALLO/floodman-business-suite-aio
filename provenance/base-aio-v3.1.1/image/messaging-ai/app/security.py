from __future__ import annotations

import base64
import hmac
import time
from hashlib import sha256
from typing import Mapping


class AuthenticationError(ValueError):
    pass


def verify(headers: Mapping[str, str], body: bytes, keys: Mapping[str, bytes], max_age: int) -> str:
    key_id = headers.get("x-floodman-key-id", "")
    timestamp = headers.get("x-floodman-timestamp", "")
    signature = headers.get("x-floodman-signature", "")
    if not key_id or not timestamp or not signature or key_id not in keys:
        raise AuthenticationError("Missing or unknown internal authentication")
    try:
        issued = int(timestamp)
    except ValueError as exc:
        raise AuthenticationError("Invalid timestamp") from exc
    if abs(int(time.time()) - issued) > max_age:
        raise AuthenticationError("Signature expired")
    digest = hmac.new(keys[key_id], timestamp.encode("ascii") + b"." + body, sha256).digest()
    expected = base64.b64encode(digest).decode("ascii")
    if not hmac.compare_digest(signature, expected):
        raise AuthenticationError("Invalid signature")
    return key_id
