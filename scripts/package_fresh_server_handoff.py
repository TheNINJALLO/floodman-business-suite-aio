#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import os
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASES = ROOT / "deployment" / "releases"
RUNTIME = RELEASES / "floodman-operations-runtime-v4.7.1.zip"
LAUNCHER = ROOT / "launcher" / "mobile-start.sh"
EGG = ROOT / "deployment" / "pterodactyl" / "egg-floodman-operations-mobile-v4.7.1.json"
GUIDE = ROOT / "deployment" / "pterodactyl" / "FRESH-SERVER-SETUP-v4.7.1-WEB007.md"
BUNDLE_NAME = "floodman-operations-new-server-v4.7.1-web007-20260828.zip"
CHECKSUM_NAME = "SHA256SUMS-WEB007-20260828"
ZIP_TIMESTAMP = (2026, 8, 28, 0, 0, 0)
EXPECTED = {
    RUNTIME: "2775227e411ae5ecbc80d9eee88509864971d5988f1510af77e4fdc9bce9b989",
    LAUNCHER: "bc3adee529c84e79ab1db03ff169b89e40339e22970eea4873e4650768a3d0fd",
    EGG: "d1e8b08e7793f8d659c310362795a17cb89040ea3f27f58762e207c1e1c4931f",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def info(name: str, mode: int = 0o644) -> zipfile.ZipInfo:
    value = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    value.create_system = 3
    value.external_attr = (mode & 0xFFFF) << 16
    value.compress_type = zipfile.ZIP_DEFLATED
    return value


def main() -> None:
    for path, expected in EXPECTED.items():
        if not path.is_file():
            raise SystemExit(f"Missing required handoff component: {path.relative_to(ROOT)}")
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(
                f"Refusing to mix handoff components: {path.relative_to(ROOT)} is {actual}, expected {expected}"
            )
    if not GUIDE.is_file():
        raise SystemExit(f"Missing setup guide: {GUIDE.relative_to(ROOT)}")

    members = {
        "floodman-operations-runtime-v4.7.1.zip": RUNTIME.read_bytes(),
        "mobile-start.sh": LAUNCHER.read_bytes(),
        "egg-floodman-operations-mobile-v4.7.1.json": EGG.read_bytes(),
        "README-FIRST.md": GUIDE.read_bytes(),
    }
    sums = "".join(
        f"{hashlib.sha256(content).hexdigest()}  {name}\n"
        for name, content in sorted(members.items())
    ).encode("utf-8")
    members["SHA256SUMS"] = sums

    destination = RELEASES / BUNDLE_NAME
    with tempfile.NamedTemporaryFile(dir=RELEASES, suffix=".zip", delete=False) as handle:
        temporary = Path(handle.name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, content in sorted(members.items()):
                archive.writestr(info(name, 0o755 if name == "mobile-start.sh" else 0o644), content, compresslevel=9)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    with zipfile.ZipFile(destination) as archive:
        if set(archive.namelist()) != set(members):
            raise SystemExit("Fresh-server bundle member set changed during packaging")
        for name, content in members.items():
            if archive.read(name) != content:
                raise SystemExit(f"Fresh-server bundle member is stale: {name}")

    bundle_hash = sha256(destination)
    checksum_file = RELEASES / CHECKSUM_NAME
    checksum_file.write_text(f"{bundle_hash}  {BUNDLE_NAME}\n", encoding="utf-8")
    print(f"Packaged {destination.relative_to(ROOT)}")
    print(f"SHA-256: {bundle_hash}")
    print(f"Verified {len(members)} matched handoff members and wrote {checksum_file.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
