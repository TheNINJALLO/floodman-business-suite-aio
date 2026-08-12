from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx


class UnsafeTarget(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WebPage:
    url: str
    status_code: int
    content_type: str
    body: str


def _public_host(host: str) -> None:
    results = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    if not results:
        raise UnsafeTarget("Target host does not resolve")
    for result in results:
        ip = ipaddress.ip_address(result[4][0].split("%", 1)[0])
        if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
            raise UnsafeTarget("Target resolves to a non-public address")


def _host_family(host: str) -> set[str]:
    base = host[4:] if host.startswith("www.") else host
    return {base, "www." + base}



def _validate_connected_peer(response: httpx.Response) -> None:
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return
    address = stream.get_extra_info("server_addr")
    if not address:
        return
    ip = ipaddress.ip_address(str(address[0]).split("%", 1)[0])
    if any((ip.is_private, ip.is_loopback, ip.is_link_local, ip.is_multicast, ip.is_reserved, ip.is_unspecified)):
        raise UnsafeTarget("Connected target peer is not a public address")


def validate_url(url: str, *, allow_http: bool, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme not in allowed_schemes or not parsed.hostname:
        raise UnsafeTarget("Target must use an allowed web scheme")
    if parsed.username or parsed.password:
        raise UnsafeTarget("Target URL cannot contain credentials")
    host = parsed.hostname.lower().rstrip(".")
    if allowed_hosts is not None and host not in allowed_hosts:
        raise UnsafeTarget("Redirect left the configured competitor host")
    _public_host(host)
    return host


def fetch_page(url: str, *, allow_http: bool, max_bytes: int, user_agent: str, max_redirects: int = 3) -> WebPage:
    initial_host = validate_url(url, allow_http=allow_http)
    allowed_hosts = _host_family(initial_host)
    current = url
    with httpx.Client(timeout=httpx.Timeout(20, connect=8), follow_redirects=False, headers={"user-agent": user_agent}) as client:
        for _ in range(max_redirects + 1):
            validate_url(current, allow_http=allow_http, allowed_hosts=allowed_hosts)
            with client.stream("GET", current, headers={"accept": "text/html,application/xhtml+xml"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UnsafeTarget("Redirect did not include a location")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                _validate_connected_peer(response)
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                    raise UnsafeTarget(f"Unsupported competitor page type: {content_type}")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise UnsafeTarget("Competitor page exceeded configured size limit")
                    chunks.append(chunk)
                body = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                return WebPage(str(response.url), response.status_code, content_type, body)
    raise UnsafeTarget("Competitor page exceeded redirect limit")
