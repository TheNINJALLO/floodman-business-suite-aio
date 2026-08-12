from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeUrl(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FetchedDocument:
    url: str
    content_type: str
    body: bytes


def _validate_host(hostname: str, *, allow_private: bool = False) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrl("Document hostname could not be resolved") from exc
    if not addresses:
        raise UnsafeUrl("Document hostname has no addresses")
    for result in addresses:
        raw = result[4][0].split("%", 1)[0]
        ip = ipaddress.ip_address(raw)
        if not allow_private and any((
            ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast,
            ip.is_reserved, ip.is_unspecified,
        )):
            raise UnsafeUrl("Document URL resolves to a non-public address")



def _validate_connected_peer(response: httpx.Response, *, allow_private: bool = False) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return
    address = stream.get_extra_info("server_addr")
    if not address:
        return
    raw = str(address[0]).split("%", 1)[0]
    ip = ipaddress.ip_address(raw)
    if not allow_private and any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
        raise UnsafeUrl("Connected document peer is not a public address")


def validate_document_url(
    url: str, allowed_hosts: tuple[str, ...], require_https: bool = True, *, allow_private: bool = False
) -> None:
    parsed = urlparse(url)
    if require_https and parsed.scheme != "https":
        raise UnsafeUrl("Document URL must use HTTPS")
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsafeUrl("Document URL is invalid")
    host = parsed.hostname.lower().rstrip(".")
    if allowed_hosts and host not in allowed_hosts:
        raise UnsafeUrl(f"Document host {host!r} is not allowlisted")
    if parsed.username or parsed.password:
        raise UnsafeUrl("Document URL cannot contain credentials")
    _validate_host(host, allow_private=allow_private)


def fetch_pdf(
    url: str,
    allowed_hosts: tuple[str, ...],
    max_bytes: int,
    *,
    verify_tls: bool = True,
    max_redirects: int = 3,
    require_https: bool = True,
    allow_private: bool = False,
) -> FetchedDocument:
    current = url
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0), verify=verify_tls, follow_redirects=False) as client:
        for _ in range(max_redirects + 1):
            validate_document_url(
                current, allowed_hosts, require_https=require_https, allow_private=allow_private
            )
            with client.stream("GET", current, headers={"accept": "application/pdf"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeUrl("Document redirect has no location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                _validate_connected_peer(response, allow_private=allow_private)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"application/pdf", "application/octet-stream"}:
                    raise UnsafeUrl(f"Expected a PDF, received {content_type or 'unknown content type'}")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeUrl("Document exceeds configured size limit")
                    chunks.append(chunk)
                body = b"".join(chunks)
                if not body.startswith(b"%PDF-"):
                    raise UnsafeUrl("Downloaded document does not have a PDF header")
                return FetchedDocument(str(response.url), content_type, body)
    raise UnsafeUrl("Document exceeded redirect limit")
