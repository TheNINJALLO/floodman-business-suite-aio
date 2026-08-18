#!/usr/bin/env python3
"""Regenerate the checked-in server, Android, and Apple source manifests."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENTS = {
    "server": ROOT / "server" / "MANIFEST.sha256",
    "apps/android": ROOT / "apps" / "android" / "SOURCE-MANIFEST.sha256",
    "apps/ios": ROOT / "apps" / "ios" / "SOURCE-MANIFEST.sha256",
}


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def component_files(component: str, manifest: Path) -> list[Path]:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT}",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            component,
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    values: list[Path] = []
    for name in result.stdout.splitlines():
        path = ROOT / name
        if path.is_file() and path.resolve() != manifest.resolve():
            values.append(path)
    return sorted(set(values), key=lambda path: path.relative_to(ROOT).as_posix())


def main() -> int:
    for component, manifest in COMPONENTS.items():
        base = ROOT / component
        files = component_files(component, manifest)
        rows = [f"{digest(path)}  ./{path.relative_to(base).as_posix()}" for path in files]
        manifest.write_text("\n".join(rows) + "\n", encoding="utf-8", newline="\n")
        print(f"{manifest.relative_to(ROOT)}: {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
