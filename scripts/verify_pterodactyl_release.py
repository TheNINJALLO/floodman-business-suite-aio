#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

import package_pterodactyl_release as package

ROOT = Path(__file__).resolve().parents[1]
PROBLEMS: list[str] = []


def require(condition: bool, message: str) -> None:
    if not condition:
        PROBLEMS.append(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


version = (package.SERVER / "VERSION").read_text(encoding="utf-8").strip()
files = package.tracked_server_files()
archive_root = f"floodman-operations-v{version}"
runtime = package.RELEASES / f"floodman-operations-runtime-v{version}.zip"
release_launcher = package.RELEASES / f"mobile-start-v{version}.sh"
launcher_bytes = package.LAUNCHER.read_bytes()
launcher_text = package.LAUNCHER.read_text(encoding="utf-8")

# Every fixed-string preflight against the packaged overlay must match the
# corresponding tracked source. This catches stale launcher assertions before
# they can turn an otherwise valid Pterodactyl update into a restart loop.
overlay_check = re.compile(
    r'''^grep -Fq (?P<quote>['"])(?P<marker>.*?)(?P=quote) "\$overlay_root/(?P<relative>[^"]+)"'''
)
overlay_preflight_count = 0
for number, line in enumerate(launcher_text.splitlines(), 1):
    match = overlay_check.match(line)
    if not match:
        continue
    overlay_preflight_count += 1
    relative = match.group("relative")
    source = package.SERVER / relative
    require(source.is_file(), f"Launcher overlay preflight line {number} targets missing server/{relative}")
    if source.is_file():
        require(
            match.group("marker") in source.read_text(encoding="utf-8"),
            f"Launcher overlay preflight line {number} is stale for server/{relative}: {match.group('marker')!r}",
        )

require(runtime.is_file(), f"Missing {runtime.relative_to(ROOT)}")
require(release_launcher.is_file(), f"Missing {release_launcher.relative_to(ROOT)}")
if release_launcher.is_file():
    require(release_launcher.read_bytes() == launcher_bytes, "Deployment launcher is not byte-identical to launcher/mobile-start.sh")

if runtime.is_file():
    with zipfile.ZipFile(runtime) as archive:
        names = archive.namelist()
        for name in names:
            path = PurePosixPath(name)
            require(not path.is_absolute() and ".." not in path.parts, f"Unsafe ZIP member: {name}")
            require(path.parts and path.parts[0] == archive_root, f"ZIP member outside reviewed root: {name}")
        packed_files = {
            name.removeprefix(f"{archive_root}/")
            for name in names
            if not name.endswith("/") and name != f"{archive_root}/MANIFEST.sha256"
        }
        require(packed_files == set(files), "Runtime ZIP file set does not match the reviewed tracked-server selection")
        manifest_name = f"{archive_root}/MANIFEST.sha256"
        require(manifest_name in names, "Runtime ZIP is missing its internal manifest")
        if manifest_name in names:
            require(archive.read(manifest_name) == package.runtime_manifest(files), "Runtime ZIP internal manifest is stale")
        for relative in files:
            member = f"{archive_root}/{relative}"
            if member in names:
                require(
                    archive.read(member) == (package.SERVER / relative).read_bytes(),
                    f"Runtime ZIP content is stale: {relative}",
                )
        lowered = "\n".join(names).lower()
        for forbidden in ("clients.csv", "office-state.json", "/.env", "/data/", "/logs/", "/uploads/", "/backups/"):
            require(forbidden not in lowered, f"Runtime ZIP includes forbidden state path containing {forbidden}")

egg = json.loads(package.EGG.read_text(encoding="utf-8"))
require(egg.get("startup") == "bash ./mobile-start.sh", "Pterodactyl egg startup is not the reviewed launcher")
require(list(egg.get("docker_images", {}).values()) == [package.BASE_IMAGE], "Pterodactyl egg image is not the reviewed immutable base")
expected_installer = package.build_installer_script(launcher_text, version)
require(egg.get("scripts", {}).get("installation", {}).get("script") == expected_installer, "Pterodactyl egg embeds a stale launcher")
variables = {value.get("env_variable"): value for value in egg.get("variables", [])}
require(not (set(variables) & package.REMOVED_EGG_VARIABLES), "Pterodactyl egg retains removed source or Tailscale variables")
for _, env_variable, default_value, _ in package.EXTERNAL_URL_VARIABLES:
    require(env_variable in variables, f"Pterodactyl egg does not expose {env_variable}")
    require(
        variables.get(env_variable, {}).get("default_value") == default_value,
        f"Pterodactyl egg has the wrong default for {env_variable}",
    )
for marker in ("TAILSCALE_", "tailscaled", "pkgs.tailscale.com", "tailscale serve", "tailscale funnel"):
    require(marker.lower() not in launcher_text.lower(), f"Canonical launcher retains removed Tailscale marker: {marker}")
require(
    variables.get("FLOODMAN_OWNER_PASSWORD", {}).get("default_value") == "REPLACE_ME_12345!",
    "Pterodactyl egg does not use the rejected Owner password placeholder",
)

sums = package.RELEASES / "SHA256SUMS"
require(sums.is_file(), "Missing deployment/releases/SHA256SUMS")
if sums.is_file():
    recorded: dict[str, str] = {}
    for number, line in enumerate(sums.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split(None, 1)
        require(len(parts) == 2, f"Malformed SHA256SUMS line {number}")
        if len(parts) == 2:
            recorded[parts[1].lstrip("* ")] = parts[0].lower()
    expected_names = {
        f"floodman-operations-runtime-v{version}.zip",
        f"mobile-start-v{version}.sh",
    }
    require(set(recorded) == expected_names, "SHA256SUMS file set does not match deployment/releases")
    for name, expected in recorded.items():
        path = package.RELEASES / name
        if path.is_file():
            require(sha256(path) == expected, f"SHA-256 mismatch for deployment/releases/{name}")

if PROBLEMS:
    for problem in PROBLEMS:
        print(f"ERROR: {problem}")
    print(f"Pterodactyl release verification failed with {len(PROBLEMS)} problem(s).")
    sys.exit(1)

print(
    f"Pterodactyl release verified: current v{version} launcher, pinned base egg, "
    f"{len(files)} runtime files, {overlay_preflight_count} overlay preflights, "
    "internal manifest, and 2 deployable checksums."
)
