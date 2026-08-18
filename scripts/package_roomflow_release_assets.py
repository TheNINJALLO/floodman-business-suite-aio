#!/usr/bin/env python3
"""Export the reviewed RoomFlow pin into the network-independent release bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "roomflow" / "source"
BUNDLE = ROOT / "server" / "roomflow" / "release-assets"
PIN_FILE = ROOT / "vendor" / "roomflow" / "PINNED_COMMIT"
UPSTREAM_FILES = (
    "index.html", "app.js", "ar-estimator.js", "cost-catalog.js", "cost-engine.js",
    "cost-tests.js", "cost-ui.js", "document-workflow.js", "jobs.json", "migration.js",
    "renderer3d.js", "spatial-engine.js", "styles.css", "user-guide.html", "work-order.js",
    "catalog/floodman-products.json", "config.js", "roomflow-integrations.js",
    "supabase-service.js", "townsquare-integration.js", "supabase_schema.sql",
    "supabase_phase1_email_tracker_catalog.sql",
    "supabase/migrations/20260803020000_shared_job_snapshots.sql",
)


def git(*arguments: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", "-c", f"safe.directory={SOURCE}", "-C", str(SOURCE), "-c", "core.longpaths=true", *arguments],
        check=True,
        capture_output=True,
        text=not binary,
    )
    return result.stdout


def sha256(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--browser-assets-dir",
        type=Path,
        default=ROOT / "apps" / "android" / "app" / "src" / "main" / "assets" / "roomflow" / "vendor",
    )
    args = parser.parse_args()
    pin = PIN_FILE.read_text(encoding="utf-8").strip()
    if str(git("rev-parse", "HEAD")).strip() != pin:
        raise SystemExit("RoomFlow source checkout does not match PINNED_COMMIT")
    changed = str(git("diff", "--name-only", "HEAD", "--", *UPSTREAM_FILES)).strip()
    if changed:
        raise SystemExit(f"Reviewed RoomFlow packaging inputs have local changes:\n{changed}")

    provenance = json.loads((BUNDLE / "ASSET-SOURCES.json").read_text(encoding="utf-8"))
    if provenance.get("roomflow_commit") != pin:
        raise SystemExit("ASSET-SOURCES.json does not match PINNED_COMMIT")
    for relative in UPSTREAM_FILES:
        destination = BUNDLE / "upstream" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(git("show", f"{pin}:{relative}", binary=True))
    (BUNDLE / "PINNED_COMMIT").write_text(pin + "\n", encoding="utf-8")

    for item in provenance.get("browser_assets", []):
        name = str(item["file"])
        source = args.browser_assets_dir.resolve() / name
        if not source.is_file() or sha256(source) != item["sha256"]:
            raise SystemExit(f"Approved browser asset is missing or changed: {source}")
        destination = BUNDLE / "vendor" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    manifest_files = sorted(path for path in BUNDLE.rglob("*") if path.is_file() and path.name != "SHA256SUMS")
    rows = [f"{sha256(path)}  {path.relative_to(BUNDLE).as_posix()}" for path in manifest_files]
    (BUNDLE / "SHA256SUMS").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"Packaged {len(manifest_files)} RoomFlow release files from {pin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
