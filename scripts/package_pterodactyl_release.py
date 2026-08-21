#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
LAUNCHER = ROOT / "launcher" / "mobile-start.sh"
RELEASES = ROOT / "deployment" / "releases"
EGG = ROOT / "deployment" / "pterodactyl" / "egg-floodman-operations-mobile-v4.7.1.json"
BASE_IMAGE = (
    "ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@"
    "sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5"
)
ZIP_TIMESTAMP = (2026, 8, 21, 0, 0, 0)

EXCLUDED_RUNTIME_PATHS = {
    "MANIFEST.sha256",
    "requirements-dev.txt",
    "source-v3.8.0.json",
}
EXCLUDED_RUNTIME_PREFIXES = ("requirements/",)
OBSOLETE_EGG_VARIABLES = {
    "FLOODMAN_SOURCE_MODE",
    "FLOODMAN_SOURCE_ARCHIVE",
    "FLOODMAN_SOURCE_URL",
    "FLOODMAN_SOURCE_SHA256",
    "FLOODMAN_FORCE_SOURCE_REAPPLY",
    "FLOODMAN_PUBLIC_HOST",
    "FLOODMAN_PUBLIC_SCHEME",
    "FLOODMAN_PUBLIC_URL",
    "FLOODMAN_DOCUMENSO_URL",
    "FLOODMAN_MAILPIT_URL",
    "FLOODMAN_ENGINEERING_URL",
    "FLOODMAN_API_PUBLIC_URL",
    "ROOMFLOW_WEB_URL",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_server_files() -> list[str]:
    command = [
        "git",
        "-c",
        f"safe.directory={ROOT}",
        "ls-files",
        "--",
        "server",
    ]
    result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)
    values: list[str] = []
    for value in result.stdout.splitlines():
        if not value.startswith("server/"):
            continue
        relative = value.removeprefix("server/")
        if relative in EXCLUDED_RUNTIME_PATHS or relative.startswith(EXCLUDED_RUNTIME_PREFIXES):
            continue
        path = SERVER / relative
        if not path.is_file():
            raise RuntimeError(f"Tracked runtime source is missing: {value}")
        values.append(relative)
    return sorted(values)


def runtime_manifest(files: list[str] | None = None) -> bytes:
    rows = []
    for relative in files or tracked_server_files():
        rows.append(f"{sha256_file(SERVER / relative)}  ./{relative}")
    return ("\n".join(rows) + "\n").encode("utf-8")


def zip_info(name: str, *, directory: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    mode = 0o755 if directory or name.endswith(".sh") else 0o644
    info.external_attr = (mode & 0xFFFF) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def package_runtime(version: str) -> tuple[Path, int]:
    files = tracked_server_files()
    archive_root = f"floodman-operations-v{version}"
    destination = RELEASES / f"floodman-operations-runtime-v{version}.zip"
    directories = {f"{archive_root}/"}
    for relative in [*files, "MANIFEST.sha256"]:
        parent = PurePosixPath(relative).parent
        while str(parent) != ".":
            directories.add(f"{archive_root}/{parent.as_posix()}/")
            parent = parent.parent

    RELEASES.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=RELEASES, suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for directory in sorted(directories):
                archive.writestr(zip_info(directory, directory=True), b"", compresslevel=9)
            for relative in files:
                archive.writestr(
                    zip_info(f"{archive_root}/{relative}"),
                    (SERVER / relative).read_bytes(),
                    compresslevel=9,
                )
            archive.writestr(
                zip_info(f"{archive_root}/MANIFEST.sha256"),
                runtime_manifest(files),
                compresslevel=9,
            )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination, len(files)


def build_installer_script(launcher: str, version: str) -> str:
    sentinel = "FLOODMAN_LAUNCHER_V4610"
    if sentinel in launcher:
        raise RuntimeError(f"Launcher unexpectedly contains reserved heredoc marker {sentinel}")
    return f"""#!/bin/ash
set -eu
apk add --no-cache ca-certificates coreutils curl unzip >/dev/null
mkdir -p /mnt/server/data /mnt/server/config /mnt/server/backups /mnt/server/diagnostics /mnt/server/logs
cat > /mnt/server/mobile-start.sh <<'{sentinel}'
{launcher.rstrip()}
{sentinel}
chmod 0755 /mnt/server/mobile-start.sh
cat > /mnt/server/README-MOBILE.txt <<'README'
Floodman Operations v{version} Pterodactyl installer

Before the first start:
1. Upload floodman-operations-runtime-v{version}.zip to the server root. Do not extract it.
2. Set the company and Owner fields in Startup. Replace every example value.
3. Confirm primary allocation 9000 and additional allocations 9001 through 9004.
4. Create config/tailscale-auth-key.txt with a one-off, non-ephemeral Tailscale auth key.
5. Keep the Startup command as: bash ./mobile-start.sh

Persistent data and generated secrets remain under data/ and config/.
README
echo 'Floodman Operations v{version} launcher installed. Upload the matching runtime ZIP and configure Startup/Tailscale before pressing Start.'
"""


def tailscale_hostname_variable() -> dict[str, object]:
    return {
        "name": "Tailscale Hostname",
        "description": "Private MagicDNS machine name. Authentication uses config/tailscale-auth-key.txt and is never stored in an environment variable.",
        "env_variable": "TAILSCALE_HOSTNAME",
        "default_value": "floodman-operations",
        "user_viewable": True,
        "user_editable": True,
        "rules": "required|regex:/^[a-zA-Z0-9][a-zA-Z0-9-]{0,62}$/",
        "field_type": "text",
    }


def update_egg(version: str, launcher: str) -> None:
    egg = json.loads(EGG.read_text(encoding="utf-8"))
    egg["name"] = f"Floodman Operations AIO v{version}"
    egg["description"] = (
        f"Floodman Operations staging AIO v{version}. Installs the matched cumulative launcher and requires "
        f"floodman-operations-runtime-v{version}.zip in the server root. Staff surfaces remain private through Tailscale."
    )
    egg["docker_images"] = {"Floodman AIO base 3.2.2 (pinned)": BASE_IMAGE}
    egg["startup"] = "bash ./mobile-start.sh"
    egg["scripts"]["installation"]["script"] = build_installer_script(launcher, version)

    variables = [
        value
        for value in egg.get("variables", [])
        if value.get("env_variable") not in OBSOLETE_EGG_VARIABLES
    ]
    for value in variables:
        if value.get("env_variable") == "FLOODMAN_OWNER_PASSWORD":
            value["default_value"] = "REPLACE_ME_12345!"
            value["description"] = (
                "Required Owner password. Replace the example before first start; Floodman rejects known placeholder values."
            )
    if not any(value.get("env_variable") == "TAILSCALE_HOSTNAME" for value in variables):
        insert_at = next(
            (index + 1 for index, value in enumerate(variables) if value.get("env_variable") == "TZ"),
            len(variables),
        )
        variables.insert(insert_at, tailscale_hostname_variable())
    egg["variables"] = variables
    EGG.write_text(json.dumps(egg, indent=2) + "\n", encoding="utf-8")


def write_release_checksums(version: str) -> Path:
    destination = RELEASES / "SHA256SUMS"
    files = [
        RELEASES / f"floodman-operations-runtime-v{version}.zip",
        RELEASES / f"mobile-start-v{version}.sh",
    ]
    destination.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8",
    )
    return destination


def main() -> None:
    version = (SERVER / "VERSION").read_text(encoding="utf-8").strip()
    if version != "4.7.1":
        raise SystemExit(f"This reviewed packager is fixed to v4.7.1; found {version!r}")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    if "[Floodman Mobile v4.7.1]" not in launcher:
        raise SystemExit("Canonical launcher does not identify Floodman Mobile v4.7.1")

    release_launcher = RELEASES / f"mobile-start-v{version}.sh"
    shutil.copyfile(LAUNCHER, release_launcher)
    runtime, count = package_runtime(version)
    update_egg(version, launcher)
    checksums = write_release_checksums(version)
    print(f"Packaged {runtime.relative_to(ROOT)} with {count} tracked runtime files plus its internal manifest.")
    print(f"Synchronized {release_launcher.relative_to(ROOT)} and {EGG.relative_to(ROOT)}.")
    print(f"Wrote {checksums.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
