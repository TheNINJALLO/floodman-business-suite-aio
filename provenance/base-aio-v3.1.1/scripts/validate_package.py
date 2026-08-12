#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
import pathlib
import re
import sys

import yaml


def fail(message: str) -> None:
    raise SystemExit(f"VALIDATION FAILED: {message}")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    egg_path = root / "egg-floodman-business-suite-aio.json"
    dockerfile = root / "image" / "Dockerfile"
    workflow = root / ".github" / "workflows" / "build-aio.yml"

    for path in (egg_path, dockerfile, workflow, root / "image" / "aio" / "start-suite.sh"):
        if not path.is_file():
            fail(f"missing required file: {path.relative_to(root)}")

    egg = json.loads(egg_path.read_text(encoding="utf-8"))
    if egg.get("meta", {}).get("version") != "PTDL_v2":
        fail("egg is not PTDL_v2")
    if "FLOODMAN_SUITE_READY" not in egg.get("config", {}).get("startup", ""):
        fail("egg readiness marker is missing")
    images = egg.get("docker_images") or {}
    if "ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1" not in images.values():
        fail("egg does not reference the expected versioned GHCR image")
    variables = {item["env_variable"]: item for item in egg.get("variables", [])}
    required = {
        "FLOODMAN_OWNER_FIRST_NAME",
        "FLOODMAN_OWNER_LAST_NAME",
        "FLOODMAN_OWNER_EMAIL",
        "FLOODMAN_OWNER_PASSWORD",
        "DOCUMENSO_PORT",
        "MAILPIT_PORT",
        "ENGINEERING_PORT",
        "FLOODMAN_API_PORT",
        "FLOODMAN_ENFORCE_9000_PORT_SCHEME",
    }
    missing = sorted(required - variables.keys())
    if missing:
        fail(f"egg variables missing: {', '.join(missing)}")

    expected_ports = {
        "DOCUMENSO_PORT": "9001",
        "MAILPIT_PORT": "9002",
        "ENGINEERING_PORT": "9003",
        "FLOODMAN_API_PORT": "9004",
    }
    for key, expected in expected_ports.items():
        actual = str(variables[key].get("default_value"))
        if actual != expected:
            fail(f"{key} default must be {expected}, got {actual}")
    if str(variables["FLOODMAN_ENFORCE_9000_PORT_SCHEME"].get("default_value")).lower() != "true":
        fail("9000 port-scheme enforcement must default to true")


    df = dockerfile.read_text(encoding="utf-8")
    for required_text in (
        "USER container",
        "WORKDIR /home/container",
        "ENTRYPOINT [\"/opt/floodman/aio/pterodactyl-entrypoint.sh\"]",
        "documenso/documenso:v2.11.0",
        "ghcr.io/ever-co/gauzy-api:latest",
    ):
        if required_text not in df:
            fail(f"Dockerfile missing required statement: {required_text}")
    forbidden = ("/var/run/docker.sock", "dockerd", "docker:dind", "--privileged")
    all_text = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in (root / "image").rglob("*") if path.is_file())
    for token in forbidden:
        if token in all_text:
            fail(f"unsafe nested-Docker token found: {token}")

    workflow_data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    if not isinstance(workflow_data, dict) or "jobs" not in workflow_data:
        fail("GitHub Actions workflow is invalid")

    shell_files = list((root / "image" / "aio").glob("*.sh"))
    if len(shell_files) < 10:
        fail("expected AIO process wrapper scripts")
    for path in shell_files:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("#!/bin/sh"):
            fail(f"shell script lacks POSIX shebang: {path.name}")
        if "\r\n" in text:
            fail(f"shell script has CRLF line endings: {path.name}")

    python_files = []
    for component in ("orchestrator", "messaging-ai", "competitor-intel", "office-console", "local-lab"):
        python_files.extend((root / "image" / component / "app").rglob("*.py"))
    for path in python_files:
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            fail(f"Python syntax error in {path.relative_to(root)}: {exc}")

    baseline = root / "image" / "database" / "init" / "00-floodman-baseline.sql"
    if "baseline_version, application_name" not in baseline.read_text(encoding="utf-8"):
        fail("fixed Floodman baseline marker is missing")
    if (root / "image" / "orchestrator" / "migrations").exists():
        fail("runtime Floodman migration directory must not be present")

    start = (root / "image" / "aio" / "start-suite.sh").read_text(encoding="utf-8")
    if 'export DEMO="false"' not in start:
        fail("Gauzy non-demo mode is not enforced")
    if "supervisord -n" not in start:
        fail("single-container supervisor startup is missing")
    if 'DOCUMENSO_PORT:=9001' not in start or 'MAILPIT_PORT:=9002' not in start or 'ENGINEERING_PORT:=9003' not in start or 'FLOODMAN_API_PORT:=9004' not in start:
        fail("start-suite defaults do not use the 9000-series scheme")
    if 'FLOODMAN_ENFORCE_9000_PORT_SCHEME:=true' not in start:
        fail("start-suite does not default to enforcing the 9000-series scheme")
    if 'primary Pterodactyl allocation must be 9000' not in start:
        fail("start-suite lacks a clear primary-allocation error")
    if 'EXPOSE 9000 9001 9002 9003 9004' not in df:
        fail("Dockerfile does not expose the 9000-series public ports")

    print(
        json.dumps(
            {
                "status": "passed",
                "egg_variables": len(variables),
                "python_files": len(python_files),
                "shell_files": len(shell_files),
                "runtime_model": "single Pterodactyl container, no nested Docker",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
