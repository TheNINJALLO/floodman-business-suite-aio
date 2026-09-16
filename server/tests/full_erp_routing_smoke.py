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
    assert "location = /api/auth/login" in nginx
    assert "proxy_pass http://127.0.0.1:8700/office/api/erp/login" in nginx
    assert "return 302 /login?next=/office;" in nginx
    assert "error_page 401 =302 /login?next=/roomflow/;" in nginx

    # External HTTPS origins must not be rewritten to HTTP merely because the
    # final proxy hop into Nginx is plain HTTP.
    assert "map $http_x_forwarded_proto $fm_public_scheme" in nginx
    assert "~*^https$ https;" in nginx
    assert "listen 0.0.0.0:${SERVER_PORT} default_server;" in nginx

    print("Floodman full ERP authentication routing smoke test passed")


if __name__ == "__main__":
    run()
