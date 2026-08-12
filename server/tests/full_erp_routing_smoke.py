from __future__ import annotations

from pathlib import Path


def run() -> None:
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "pwa" / "erp.html").read_text(encoding="utf-8")
    nginx = (root / "aio" / "nginx.conf.template").read_text(encoding="utf-8")

    # The ERP endpoint returns HTTP 200 with JSON false when a browser is not
    # authenticated. The launcher must interpret the response body and open the
    # login route rather than blindly opening the dashboard/server-down screen.
    assert "fetch(`/api/auth/authenticated" in launcher
    assert "payload === true" in launcher
    assert "pages/dashboard" in launcher
    assert "auth/login" in launcher
    assert "window.location.replace(target(isAuthenticated))" in launcher
    assert "requested === 'login'" in launcher
    assert "requested === 'dashboard'" in launcher
    assert "response.status >= 500" in launcher

    # The browser guard must be served and injected into the genuine Angular
    # index page, not merely generated and left unused on disk.
    assert "location = /full-erp" in nginx
    assert "location = /floodman-boot-guard.js" in nginx
    assert "location = /floodman-status.html" in nginx
    assert "location = /floodman-login" in nginx
    assert "location = /erp-login" in nginx
    assert "location = /erp-home" in nginx
    assert '/floodman-boot-guard.js?release=${HUB_RELEASE}' in nginx
    assert "proxy_pass http://127.0.0.1:3000" in nginx

    # Private Tailscale HTTPS ports must not be rewritten to HTTP merely because
    # the final loopback hop into Nginx is plain HTTP.
    assert "map $http_host $fm_tls_port" in nginx
    assert "~*:844[3-7]$ 1;" in nginx
    assert "~^1\\| https;" in nginx

    print("Floodman full ERP authentication routing smoke test passed")


if __name__ == "__main__":
    run()
