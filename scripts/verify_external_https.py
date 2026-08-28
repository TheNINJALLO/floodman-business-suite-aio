#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "launcher" / "mobile-start.sh"
EGG = ROOT / "deployment" / "pterodactyl" / "egg-floodman-operations-mobile-v4.7.1.json"

EXPECTED_URLS = {
    "FLOODMAN_PUBLIC_URL": "https://floodman.oninetwork.com",
    "FLOODMAN_DOCUMENSO_URL": "https://sign.oninetwork.com",
    "FLOODMAN_CUSTOMER_PUBLIC_URL": "https://floodman.oninetwork.com/customer",
    "FLOODMAN_MOBILE_API_PUBLIC_URL": "https://api.oninetwork.com/mobile-api",
    "FLOODMAN_API_PUBLIC_URL": "https://api.oninetwork.com",
    "FLOODMAN_ENGINEERING_URL": "https://lab.oninetwork.com",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run() -> None:
    launcher = LAUNCHER.read_text(encoding="utf-8")
    lowered = launcher.lower()
    for marker in (
        "tailscale_",
        "tailscaled",
        "pkgs.tailscale.com",
        "tailscale serve",
        "tailscale funnel",
        "tskey-",
        ":8443",
        ":8444",
        ":8445",
        ":8446",
        ":8447",
        "127.0.0.1:9010",
    ):
        require(marker not in lowered, f"launcher retains removed network marker: {marker}")

    for value in EXPECTED_URLS.values():
        require(value in launcher, f"launcher is missing canonical URL: {value}")

    for marker in (
        "listen 0.0.0.0:${FLOODMAN_API_PORT};",
        "proxy_pass http://127.0.0.1:8700;",
        "proxy_pass http://127.0.0.1:8701;",
        "--host 127.0.0.1 --port 8701",
        "--host 0.0.0.0 --port \"$ENGINEERING_PORT\"",
        "export HOSTNAME=0.0.0.0",
        "--listen \"127.0.0.1:${MAILPIT_PORT}\"",
    ):
        require(marker in launcher, f"launcher is missing external HTTPS topology marker: {marker}")

    egg = json.loads(EGG.read_text(encoding="utf-8"))
    variables = {item["env_variable"]: item for item in egg["variables"]}
    require("TAILSCALE_HOSTNAME" not in variables, "egg still exposes TAILSCALE_HOSTNAME")
    for name, expected in EXPECTED_URLS.items():
        require(name in variables, f"egg is missing {name}")
        require(variables[name]["default_value"] == expected, f"egg default is wrong for {name}")
        require("https" in variables[name]["rules"], f"egg does not enforce HTTPS for {name}")

    nginx = (ROOT / "server" / "aio" / "nginx.conf.template").read_text(encoding="utf-8")
    require("listen 0.0.0.0:${SERVER_PORT} default_server;" in nginx, "Hub is not proxy-reachable")
    require("map $http_x_forwarded_proto $fm_public_scheme" in nginx, "forwarded HTTPS is not preserved")

    android = (ROOT / "apps" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    ios_project = (ROOT / "apps" / "ios" / "project.yml").read_text(encoding="utf-8")
    ios_client = (
        ROOT / "apps" / "ios" / "FloodmanOperations" / "Networking" / "APIClient.swift"
    ).read_text(encoding="utf-8")
    native_url = "https://api.oninetwork.com/mobile-api/"
    require(native_url in android, "Android fallback API URL is stale")
    require(native_url in ios_project, "Apple project API URL is stale")
    require(native_url in ios_client, "Apple fallback API URL is stale")
    android_properties = (ROOT / "apps" / "android" / "gradle.properties").read_text(encoding="utf-8")
    android_security = (ROOT / "apps" / "android" / "docs" / "SECURITY.md").read_text(encoding="utf-8")
    require(".ts.net" not in android_properties, "Android build example retains a Tailscale origin")
    require(".ts.net" not in android_security, "Android security guide retains a Tailscale origin")

    hub_config = (ROOT / "server" / "hub" / "hub-config.js.template").read_text(encoding="utf-8")
    suite = (ROOT / "server" / "aio" / "start-suite.sh").read_text(encoding="utf-8")
    for retired_port in ("8443", "8444", "8445", "8446", "8447"):
        require(retired_port not in hub_config, f"Hub config retains retired port {retired_port}")
        require(retired_port not in suite, f"suite startup retains retired port {retired_port}")

    for removed in (
        ROOT / "server" / "tailscale" / "README.txt",
        ROOT / "server" / "tailscale" / "STABLE_VERSION",
        ROOT / "deployment" / "env" / "tailscale.env.example",
        ROOT / "deployment" / "tailscale" / "README.md",
        ROOT / "deployment" / "tailscale" / "serve-map.txt",
    ):
        require(not removed.exists(), f"retired deployment input still exists: {removed.relative_to(ROOT)}")

    print("Floodman external HTTPS/no-Tailscale contract verification passed")


if __name__ == "__main__":
    run()
