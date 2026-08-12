import base64

import pytest

from app.security import (
    AuthenticationError,
    create_portal_token,
    decode_portal_token,
    internal_headers,
    privacy_hash,
    verify_internal_request,
    verify_square_webhook,
)


def test_internal_hmac_round_trip() -> None:
    secret = b"s" * 32
    body = b'{"ok":true}'
    headers = internal_headers("v1", secret, body, timestamp=1_700_000_000)
    assert verify_internal_request(headers, body, {"v1": secret}, 300, now=1_700_000_200) == "v1"


def test_internal_hmac_rejects_modified_body() -> None:
    secret = b"s" * 32
    headers = internal_headers("v1", secret, b"one", timestamp=100)
    with pytest.raises(AuthenticationError):
        verify_internal_request(headers, b"two", {"v1": secret}, 300, now=100)


def test_portal_token_round_trip_and_expiry() -> None:
    secret = b"p" * 32
    token = create_portal_token("job-1", 2, secret, ttl_seconds=60, now=100)
    claims = decode_portal_token(token, secret, now=159)
    assert claims.job_id == "job-1"
    assert claims.version == 2
    with pytest.raises(AuthenticationError):
        decode_portal_token(token, secret, now=161)


def test_square_signature_uses_exact_url_and_body() -> None:
    import hashlib
    import hmac

    key = "signature-key"
    url = "https://api.example.com/webhooks/square"
    body = b'{"event_id":"1"}'
    signature = base64.b64encode(hmac.new(key.encode(), url.encode() + body, hashlib.sha256).digest()).decode()
    assert verify_square_webhook(key, url, body, signature)
    assert not verify_square_webhook(key, url + "/", body, signature)


def test_privacy_hash_is_keyed() -> None:
    assert privacy_hash(b"a" * 32, "203.0.113.1") == privacy_hash(b"a" * 32, "203.0.113.1")
    assert privacy_hash(b"a" * 32, "203.0.113.1") != privacy_hash(b"b" * 32, "203.0.113.1")


def test_twilio_signature_round_trip_and_exact_url() -> None:
    from app.security import twilio_signature, verify_twilio_webhook

    token = "auth-token"
    url = "https://api.floodman.com/webhooks/twilio/inbound"
    params = {"Body": "Balance?", "From": "+13135550199", "MessageSid": "SM123"}
    signature = twilio_signature(token, url, params)
    assert verify_twilio_webhook(token, url, params, signature)
    assert not verify_twilio_webhook(token, url + "/", params, signature)
    assert not verify_twilio_webhook(token, url, {**params, "Body": "Changed"}, signature)
