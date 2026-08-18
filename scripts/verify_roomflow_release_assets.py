#!/usr/bin/env python3
"""Verify the network-independent RoomFlow runtime and approved browser libraries."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath

from validate_roomflow_web import validate

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "server" / "roomflow" / "release-assets"
PIN_FILE = ROOT / "vendor" / "roomflow" / "PINNED_COMMIT"
MANIFEST = BUNDLE / "SHA256SUMS"
PROVENANCE = BUNDLE / "ASSET-SOURCES.json"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    problems: list[str] = []
    pin = PIN_FILE.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", pin):
        problems.append("vendor/roomflow/PINNED_COMMIT is not a full commit hash")
    if not MANIFEST.is_file():
        problems.append("release asset manifest is missing")
    declared: dict[str, str] = {}
    if MANIFEST.is_file():
        for line_number, line in enumerate(MANIFEST.read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split("  ", 1)
            if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
                problems.append(f"invalid release asset manifest row {line_number}")
                continue
            relative = PurePosixPath(parts[1])
            if relative.is_absolute() or ".." in relative.parts or relative.as_posix() in declared:
                problems.append(f"unsafe or duplicate release asset path: {relative}")
                continue
            declared[relative.as_posix()] = parts[0]
    actual = {
        path.relative_to(BUNDLE).as_posix(): digest(path)
        for path in BUNDLE.rglob("*")
        if path.is_file() and path != MANIFEST
    }
    for relative in sorted(set(declared) | set(actual)):
        if relative not in actual:
            problems.append(f"release asset is missing: {relative}")
        elif relative not in declared:
            problems.append(f"release asset is not declared: {relative}")
        elif actual[relative] != declared[relative]:
            problems.append(f"release asset checksum differs: {relative}")

    try:
        provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        if provenance.get("roomflow_commit") != pin:
            problems.append("release asset provenance does not match PINNED_COMMIT")
        for item in provenance.get("browser_assets", []):
            relative = f"vendor/{item.get('file', '')}"
            if actual.get(relative) != item.get("sha256"):
                problems.append(f"approved browser asset differs: {relative}")
    except (OSError, ValueError, TypeError) as exc:
        problems.append(f"release asset provenance is invalid: {exc}")

    if (BUNDLE / "upstream").is_dir():
        problems.extend(validate(BUNDLE / "upstream", "server", []))
    else:
        problems.append("release asset upstream directory is missing")

    if problems:
        for problem in sorted(set(problems)):
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"RoomFlow offline release assets verified: {pin}")
    print(f"Checksummed release files: {len(actual)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
