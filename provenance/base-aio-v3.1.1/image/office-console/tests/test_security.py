from __future__ import annotations

import base64

from app.security import SignedClient, canonical_json, parse_first_key


def test_key_and_canonical_json() -> None:
    raw = base64.b64encode(b"a" * 32).decode()
    key_id, secret = parse_first_key(f"v1:{raw}")
    assert key_id == "v1"
    assert secret == b"a" * 32
    assert canonical_json({"b": 2, "a": 1}) == b'{"a":1,"b":2}'
    client = SignedClient.from_key_string("http://example", f"v1:{raw}")
    headers = client.headers(b"{}")
    assert headers["x-floodman-key-id"] == "v1"
    assert headers["x-floodman-signature"]
