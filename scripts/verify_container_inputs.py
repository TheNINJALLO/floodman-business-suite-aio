#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBLEMS: list[str] = []
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")

EXPECTED_IMAGES = {
    "FLOODMAN_BASE_IMAGE": "ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5",
    "GAUZY_API_IMAGE": "ghcr.io/ever-co/gauzy-api:latest@sha256:b99003e2c3f575b615a693af6d94887ae6a9de31c5a488f5dcc64800ec14a33e",
    "GAUZY_WEB_IMAGE": "ghcr.io/ever-co/gauzy-webapp:latest@sha256:dfe1ae5e057c12ebaff562310c9b670d9fde71fae481f1891194454da1bd57b4",
    "DOCUMENSO_IMAGE": "documenso/documenso:v2.11.0@sha256:d9b9a21841e28ebf08d747706e15319a485aa19afea09ab1c926b025c2ce4a18",
    "MAILPIT_IMAGE": "axllent/mailpit:latest@sha256:d5ecbb067db3705fa953d79e1b7f81ef84038df67aba6c52825d8c02a1ea748a",
}

ACTION_REFS = {
    "actions/checkout": "11d5960a326750d5838078e36cf38b85af677262",
    "docker/setup-buildx-action": "8d2750c68a42422c14e847fe6c8ac0403b4cbd6f",
    "docker/login-action": "c94ce9fb468520275223c153574b00df6fe4bcc9",
    "docker/build-push-action": "10e90e3645eae34f1e60eeb005ba3a3d33f178e8",
    "actions/upload-artifact": "ea165f8d65b6e75b540449e92b4886f43607fa02",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        PROBLEMS.append(message)


def image_args(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"ARG\s+([A-Z][A-Z0-9_]*)=(\S+)", line.strip())
        if match and match.group(1).endswith("_IMAGE"):
            values[match.group(1)] = match.group(2)
    return values


active = {}
for dockerfile in (ROOT / "containers" / "derivative" / "Dockerfile", ROOT / "containers" / "base-aio" / "Dockerfile"):
    active.update(image_args(dockerfile))

for name, expected in EXPECTED_IMAGES.items():
    actual = active.get(name)
    require(actual == expected, f"{name} does not match the reviewed release digest")
    require(bool(actual and DIGEST.search(actual)), f"{name} is not pinned by sha256 digest")

derivative = (ROOT / "containers" / "derivative" / "Dockerfile").read_text(encoding="utf-8")
require('rm -rf "/opt/pydeps/${service}"' in derivative, "derivative build can retain stale Python target packages")
require("COPY server/requirements/" in derivative and "COPY --chown=container:container server/" in derivative, "derivative build does not use the reviewed server source layout")
for token in ('org.opencontainers.image.version="4.6.7"', 'org.opencontainers.image.authors="Josh Aldrich"', "EXPRESS_SESSION_SECRET=", "JWT_SECRET=", "JWT_REFRESH_TOKEN_SECRET="):
    require(token in derivative, f"derivative image metadata is missing {token}")

for requirement in sorted((ROOT / "server" / "requirements").glob("*.txt")):
    for number, line in enumerate(requirement.read_text(encoding="utf-8").splitlines(), 1):
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        require("==" in value and not any(token in value for token in (">=", "<=", "~=", " @ ")), f"unfixed direct requirement {requirement.relative_to(ROOT)}:{number}: {value}")

constraint_count = 0
for service in ("orchestrator", "messaging-ai", "competitor-intel", "office-console", "local-lab"):
    constraint = ROOT / "server" / "requirements" / "constraints" / f"{service}.txt"
    require(constraint.is_file(), f"missing transitive constraint set for {service}")
    if not constraint.is_file():
        continue
    values = [line.strip() for line in constraint.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    constraint_count += len(values)
    require(bool(values), f"empty transitive constraint set for {service}")
    for number, value in enumerate(values, 1):
        require(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+", value) is not None, f"unfixed constraint {constraint.relative_to(ROOT)}:{number}: {value}")

for dockerfile in (ROOT / "containers" / "derivative" / "Dockerfile", ROOT / "containers" / "base-aio" / "Dockerfile"):
    text = dockerfile.read_text(encoding="utf-8")
    require('-c "/tmp/floodman-requirements/constraints/${service}.txt"' in text, f"{dockerfile.relative_to(ROOT)} does not enforce transitive constraints")

locked = json.loads((ROOT / "vendor" / "UPSTREAMS.lock.json").read_text(encoding="utf-8"))
locked_images = {component.get("image") for component in locked.get("components", []) if component.get("image")}
for image in EXPECTED_IMAGES.values():
    require(image in locked_images, f"UPSTREAMS.lock.json does not record {image}")

dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
for token in ("**", "!containers/derivative/Dockerfile", "!containers/base-aio/Dockerfile", "!server/**", "server/**/.env", "server/**/office-state.json", "server/**/data/", "server/roomflow/current/"):
    require(token in dockerignore, f".dockerignore is missing {token}")

workflow = (ROOT / ".github" / "workflows" / "build-server-image.yml").read_text(encoding="utf-8")
for action, commit in ACTION_REFS.items():
    require(f"{action}@{commit}" in workflow, f"server workflow does not pin {action} to {commit}")
for token in ("platforms: linux/amd64", "pull: true", "no-cache: true", "provenance: true", "sbom: true", "steps.build.outputs.digest", "BUILD-INPUT-SHA256SUMS.txt"):
    require(token in workflow, f"server workflow is missing {token}")

if PROBLEMS:
    for problem in PROBLEMS:
        print(f"ERROR: {problem}")
    print(f"Container input verification failed with {len(PROBLEMS)} problem(s).")
    sys.exit(1)

print(f"Container inputs verified: 5 image digests, fixed direct Python requirements, {constraint_count} transitive version constraints, restricted build context, and 5 immutable workflow actions.")
print("Historical containers/base-aio/Dockerfile.legacy-v3.1.1 is retained as provenance and is not an active build input.")
