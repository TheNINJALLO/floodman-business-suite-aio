#!/usr/bin/env python3
"""Verify the pinned RoomFlow checkout, package inputs, and import schema contract."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from validate_roomflow_web import CLOUD_RUNTIME, CORE_RUNTIME, validate
from verify_roomflow_release_assets import main as verify_release_assets

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "vendor" / "roomflow" / "source"
PIN_FILE = ROOT / "vendor" / "roomflow" / "PINNED_COMMIT"
RELEASE_SOURCE = ROOT / "server" / "roomflow" / "release-assets" / "upstream"


def require(condition: bool, message: str, problems: list[str]) -> None:
    if not condition:
        problems.append(message)


def git(*arguments: str) -> str:
    command = [
        "git",
        "-c",
        f"safe.directory={SOURCE}",
        "-C",
        str(SOURCE),
        "-c",
        "core.longpaths=true",
        *arguments,
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f"git exited {result.returncode}")
    return result.stdout.strip()


def main() -> int:
    problems: list[str] = []
    pin = PIN_FILE.read_text(encoding="utf-8").strip()
    require(bool(re.fullmatch(r"[0-9a-f]{40}", pin)), "PINNED_COMMIT is not a full SHA-1", problems)
    require(verify_release_assets() == 0, "network-independent RoomFlow release assets failed verification", problems)
    if (SOURCE / ".git").exists():
        try:
            require(git("rev-parse", "HEAD") == pin, "RoomFlow checkout does not match PINNED_COMMIT", problems)
            reviewed = (*CORE_RUNTIME, *CLOUD_RUNTIME, "supabase_schema.sql", "supabase_phase1_email_tracker_catalog.sql", "supabase/migrations/20260803020000_shared_job_snapshots.sql")
            require(not git("diff", "--name-only", "HEAD", "--", *reviewed), "reviewed RoomFlow packaging inputs have local changes", problems)
        except RuntimeError as exc:
            problems.append(f"RoomFlow Git verification failed: {exc}")
    problems.extend(validate(RELEASE_SOURCE, "server", []))

    server_prepare = (ROOT / "server" / "roomflow" / "prepare-roomflow.py").read_text(encoding="utf-8")
    require(f'ROOMFLOW_COMMIT = "{pin}"' in server_prepare, "server RoomFlow preparation pin differs", problems)
    require("RELEASE_ASSETS" in server_prepare and "download(" not in server_prepare, "server RoomFlow preparation is not release-asset-only", problems)
    for platform in ("android", "ios"):
        script_path = ROOT / "apps" / platform / "scripts" / "prepare-roomflow-assets.sh"
        script = script_path.read_text(encoding="utf-8")
        normalized_script = script.replace("\\", "")
        require("vendor/roomflow/PINNED_COMMIT" in script, f"{platform} preparation does not read the shared pin", problems)
        require("server/roomflow/release-assets" in script and "curl " not in script, f"{platform} preparation is not network-independent", problems)
        for runtime_file in CORE_RUNTIME:
            if "/" not in runtime_file:
                require(runtime_file in script, f"{platform} preparation omits {runtime_file}", problems)
        for cloud_file in CLOUD_RUNTIME:
            require(cloud_file in normalized_script, f"{platform} preparation does not explicitly handle {cloud_file}", problems)
        require("validate_roomflow_web.py" in script, f"{platform} preparation lacks bundle validation", problems)
        require("floodman-roomflow.json" in script, f"{platform} preparation lacks package-visible provenance metadata", problems)

    lock_path = ROOT / "vendor" / "UPSTREAMS.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock_text = json.dumps(lock, sort_keys=True)
    require(pin in lock_text, "UPSTREAMS.lock.json does not contain the RoomFlow pin", problems)

    schema = (RELEASE_SOURCE / "supabase_schema.sql").read_text(encoding="utf-8", errors="replace").lower()
    phase = (RELEASE_SOURCE / "supabase_phase1_email_tracker_catalog.sql").read_text(encoding="utf-8", errors="replace").lower()
    snapshots = (RELEASE_SOURCE / "supabase" / "migrations" / "20260803020000_shared_job_snapshots.sql").read_text(
        encoding="utf-8", errors="replace"
    ).lower()
    schema_by_table = {
        "organizations": schema,
        "organization_members": schema,
        "customers": schema,
        "jobs": schema,
        "job_layouts": schema,
        "job_pricing": schema,
        "estimate_catalog_items": phase,
        "estimates": phase,
        "estimate_lines": phase,
        "job_project_snapshots": snapshots,
        "job_costing_snapshots": snapshots,
    }
    importer = (ROOT / "server" / "office-console" / "app" / "roomflow_supabase.py").read_text(encoding="utf-8")
    for table, definition in schema_by_table.items():
        require(table in definition, f"upstream schema lacks {table}", problems)
        require(f'"{table}"' in importer, f"Floodman importer does not query {table}", problems)
        require(f"alter table public.{table} enable row level security" in definition, f"upstream schema lacks RLS for {table}", problems)
    require('"authorization"' in importer.lower() and "bearer {self.access_token}" in importer.lower(), "importer does not send the signed-in user token", problems)
    require("uuid.uuid5" in importer and "roomflow_source_id" in importer, "importer lacks stable source identity mapping", problems)

    if problems:
        for problem in sorted(set(problems)):
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"RoomFlow pin verified: {pin}")
    print(f"RoomFlow bundled runtime files verified: {len(list(RELEASE_SOURCE.rglob('*')))}")
    print("Server, Android, iOS, upstream schema, RLS, and importer contracts agree.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
