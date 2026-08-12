from __future__ import annotations

import socket

import pytest

from app.adapters.safe_fetch import UnsafeUrl, validate_document_url


def _private_dns(*args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("172.20.0.5", 0))]


def test_private_document_host_is_rejected_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    with pytest.raises(UnsafeUrl, match="non-public"):
        validate_document_url("https://local-lab/files/test.pdf", ("local-lab",))


def test_local_lab_can_explicitly_allow_http_private_document_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _private_dns)
    validate_document_url(
        "http://127.0.0.1:9003/files/test.pdf",
        ("127.0.0.1",),
        require_https=False,
        allow_private=True,
    )
