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
EGG = ROOT / "deployment" / "pterodactyl" / "egg-floodman-operations-mobile-v4.7.2.json"
BASE_IMAGE = (
    "ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@"
    "sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5"
)
ZIP_TIMESTAMP = (2026, 9, 8, 0, 0, 0)
RUNTIME_SOURCE_COMMIT = "65d097f911ced8aec0edec129d535492ab4663f2"
RUNTIME_SOURCE_URL = (
    "https://raw.githubusercontent.com/TheNINJALLO/floodman-business-suite-aio/"
    f"{RUNTIME_SOURCE_COMMIT}/deployment/releases/floodman-operations-runtime-v4.7.2.zip"
)

EXCLUDED_RUNTIME_PATHS = {
    "MANIFEST.sha256",
    "requirements-dev.txt",
    "source-v3.8.0.json",
}
EXCLUDED_RUNTIME_PREFIXES = ("requirements/", "tailscale/")
REMOVED_EGG_VARIABLES = {
    "FLOODMAN_SOURCE_MODE",
    "FLOODMAN_SOURCE_ARCHIVE",
    "FLOODMAN_SOURCE_URL",
    "FLOODMAN_SOURCE_SHA256",
    "FLOODMAN_FORCE_SOURCE_REAPPLY",
    "FLOODMAN_PUBLIC_HOST",
    "FLOODMAN_PUBLIC_SCHEME",
    "FLOODMAN_MAILPIT_URL",
    "ROOMFLOW_WEB_URL",
    "TAILSCALE_HOSTNAME",
}

EXTERNAL_URL_VARIABLES = (
    (
        "Main Floodman URL",
        "FLOODMAN_PUBLIC_URL",
        "https://floodman.oninetwork.com",
        "HTTPS origin for the staff Hub, ERP, CRM, PWA, RoomFlow, and customer routes. Protect staff paths in the external proxy.",
    ),
    (
        "Floodman Signing URL",
        "FLOODMAN_DOCUMENSO_URL",
        "https://sign.oninetwork.com",
        "HTTPS origin mapped to signing port 9001. Disable public signup and protect signing administration in the external proxy.",
    ),
    (
        "Customer Portal URL",
        "FLOODMAN_CUSTOMER_PUBLIC_URL",
        "https://floodman.oninetwork.com/customer",
        "Public HTTPS base for customer messages, documents, payments, and token links.",
    ),
    (
        "Native Mobile API URL",
        "FLOODMAN_MOBILE_API_PUBLIC_URL",
        "https://api.oninetwork.com/mobile-api",
        "Public HTTPS base used by Android and Apple apps. Map api.oninetwork.com to port 9004.",
    ),
    (
        "Workflow API URL",
        "FLOODMAN_API_PUBLIC_URL",
        "https://api.oninetwork.com",
        "HTTPS origin for provider webhooks and the authenticated workflow API on port 9004.",
    ),
    (
        "Engineering URL",
        "FLOODMAN_ENGINEERING_URL",
        "https://lab.oninetwork.com",
        "HTTPS origin mapped to port 9003. Keep this hostname restricted to approved staff.",
    ),
)


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


def build_installer_script(launcher: str, version: str, runtime_sha256: str) -> str:
    sentinel = "FLOODMAN_LAUNCHER_V4610"
    if sentinel in launcher:
        raise RuntimeError(f"Launcher unexpectedly contains reserved heredoc marker {sentinel}")
    return f"""#!/bin/ash
set -eu
apk add --no-cache ca-certificates coreutils curl unzip >/dev/null
mkdir -p /mnt/server/data /mnt/server/config /mnt/server/backups /mnt/server/diagnostics /mnt/server/logs
runtime_path='/mnt/server/floodman-operations-runtime-v{version}.zip'
runtime_temp="$runtime_path.download"
runtime_url='{RUNTIME_SOURCE_URL}'
runtime_sha256='{runtime_sha256}'
if [ -f "$runtime_path" ]; then
  printf '%s  %s\n' "$runtime_sha256" "$runtime_path" | sha256sum -c - >/dev/null \
    || {{ echo 'Existing Floodman runtime ZIP does not match this egg. Refusing to overwrite it.' >&2; exit 1; }}
  echo 'Verified the existing Floodman runtime ZIP.'
else
  rm -f "$runtime_temp"
  trap 'rm -f "$runtime_temp"' EXIT INT TERM
  curl --fail --location --retry 3 --connect-timeout 15 --max-time 300 \
    "$runtime_url" --output "$runtime_temp"
  printf '%s  %s\n' "$runtime_sha256" "$runtime_temp" | sha256sum -c - >/dev/null \
    || {{ echo 'Downloaded Floodman runtime ZIP failed SHA-256 verification.' >&2; exit 1; }}
  mv "$runtime_temp" "$runtime_path"
  trap - EXIT INT TERM
  echo 'Downloaded and verified the pinned Floodman runtime ZIP.'
fi
cat > /mnt/server/mobile-start.sh <<'{sentinel}'
{launcher.rstrip()}
{sentinel}
chmod 0755 /mnt/server/mobile-start.sh
cat > /mnt/server/README-MOBILE.txt <<'README'
Floodman Operations v{version} Pterodactyl installer

Before the first start:
1. Confirm floodman-operations-runtime-v{version}.zip is present. The installer downloads and verifies it when missing.
2. Set the company and Owner fields in Startup. Replace every example value.
3. Confirm primary allocation 9000 and additional allocations 9001 through 9004.
4. Set all six external HTTPS URLs and configure the four proxy hostnames before first start.
5. Keep Mailpit port 9002 private and keep the Startup command as: bash ./mobile-start.sh

Persistent data and generated secrets remain under data/ and config/.
README
echo 'Floodman Operations v{version} launcher and verified runtime installed. Configure Startup/external HTTPS before pressing Start.'
"""


def external_url_variable(
    name: str, env_variable: str, default_value: str, description: str
) -> dict[str, object]:
    return {
        "name": name,
        "description": description,
        "env_variable": env_variable,
        "default_value": default_value,
        "user_viewable": True,
        "user_editable": True,
        "rules": r"required|url|regex:/^https:\/\/[A-Za-z0-9.-]+(?::[0-9]+)?(?:\/[^\s?#]*)?$/",
        "field_type": "text",
    }


def update_egg(version: str, launcher: str, runtime_sha256: str) -> None:
    egg = json.loads(EGG.read_text(encoding="utf-8"))
    egg["name"] = f"Floodman Operations AIO v{version}"
    egg["description"] = (
        f"Floodman Operations staging AIO v{version}. Installs the matched cumulative launcher and downloads "
        f"the pinned, checksum-verified runtime ZIP when it is missing. TLS and staff access policy are supplied by an external HTTPS proxy."
    )
    egg["docker_images"] = {"Floodman AIO base 3.2.2 (pinned)": BASE_IMAGE}
    egg["startup"] = "bash ./mobile-start.sh"
    egg["scripts"]["installation"]["script"] = build_installer_script(launcher, version, runtime_sha256)

    variables = [
        value
        for value in egg.get("variables", [])
        if value.get("env_variable") not in REMOVED_EGG_VARIABLES
    ]
    for value in variables:
        if value.get("env_variable") == "FLOODMAN_OWNER_PASSWORD":
            value["default_value"] = "REPLACE_ME_12345!"
            value["description"] = (
                "Required Owner password. Replace the example before first start; Floodman rejects known placeholder values."
            )
    existing = {value.get("env_variable") for value in variables}
    insert_at = next(
        (index + 1 for index, value in enumerate(variables) if value.get("env_variable") == "TZ"),
        len(variables),
    )
    additions = [
        external_url_variable(name, env_variable, default_value, description)
        for name, env_variable, default_value, description in EXTERNAL_URL_VARIABLES
        if env_variable not in existing
    ]
    variables[insert_at:insert_at] = additions
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
    if version != "4.7.2":
        raise SystemExit(f"This reviewed packager is fixed to v4.7.2; found {version!r}")
    launcher = LAUNCHER.read_text(encoding="utf-8")
    if "[Floodman Mobile v4.7.2]" not in launcher:
        raise SystemExit("Canonical launcher does not identify Floodman Mobile v4.7.2")

    release_launcher = RELEASES / f"mobile-start-v{version}.sh"
    shutil.copyfile(LAUNCHER, release_launcher)
    runtime, count = package_runtime(version)
    update_egg(version, launcher, sha256_file(runtime))
    checksums = write_release_checksums(version)
    print(f"Packaged {runtime.relative_to(ROOT)} with {count} tracked runtime files plus its internal manifest.")
    print(f"Synchronized {release_launcher.relative_to(ROOT)} and {EGG.relative_to(ROOT)}.")
    print(f"Wrote {checksums.relative_to(ROOT)}.")


if __name__ == "__main__":
    main()
