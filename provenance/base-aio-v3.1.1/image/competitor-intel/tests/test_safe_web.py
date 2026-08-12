import socket

import pytest

from app.safe_web import UnsafeTarget, validate_url


def test_rejects_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))])
    with pytest.raises(UnsafeTarget):
        validate_url("https://example.com", allow_http=False)


def test_allows_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))])
    assert validate_url("https://example.com", allow_http=False) == "example.com"


def test_rejects_http_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(UnsafeTarget):
        validate_url("http://example.com", allow_http=False)
